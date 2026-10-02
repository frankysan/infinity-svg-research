"""Local visual review UI for Vyo/Army identity candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import threading
import time
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image

from . import vyo_identity
from .render_compare import _shell_path

REVIEWED_STATUSES = {"reviewed-match", "reviewed-design-mismatch", "confirmed-missing"}
DECISIONS = {"reuse", "cleanup", "mismatch", "unresolved", "missing"}


@dataclass(frozen=True)
class ReviewConfig:
    inventory: Path
    army_manifest: Path
    publication_manifest: Path
    decisions: Path
    army_root: Path
    vyo_root: Path
    output: Path
    cache: Path
    inkscape: str
    render_size: int = 512
    render_timeout: float = 60.0


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def safe_svg_path(root: Path, relative: str) -> Path:
    if not relative or Path(relative).suffix.casefold() != ".svg":
        raise ValueError("review assets must be SVG files")
    root = root.resolve()
    candidate = (root / Path(relative.replace("/", os.sep))).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("asset path escapes configured root") from exc
    if not candidate.is_file():
        raise FileNotFoundError(relative)
    return candidate


def _fit_square(source: Path, destination: Path, size: int) -> None:
    with Image.open(source) as image:
        rgba = image.convert("RGBA")
        bbox = rgba.getbbox()
        if bbox:
            rgba = rgba.crop(bbox)
        usable = max(1, round(size * 0.9))
        rgba.thumbnail((usable, usable), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        x = (size - rgba.width) // 2
        y = (size - rgba.height) // 2
        canvas.alpha_composite(rgba, (x, y))
        canvas.save(destination, format="PNG", optimize=True)


class PersistentInkscapeShell:
    """One long-lived Inkscape shell, serialized across HTTP render requests."""

    def __init__(
        self,
        inkscape: str,
        *,
        log_path: Path,
        timeout: float = 60.0,
        process_factory=None,
    ):
        if timeout <= 0:
            raise ValueError("render timeout must be positive")
        self.inkscape = inkscape
        self.log_path = log_path
        self.timeout = timeout
        self.lock = threading.RLock()
        self._process_factory = process_factory or subprocess.Popen
        self._process = None
        self._log = None
        self.starts = 0
        self.restarts = 0
        self.closed = False

    def start(self) -> None:
        with self.lock:
            if self.closed:
                raise RuntimeError("Inkscape renderer is closed")
            self._ensure_process_locked()

    def _ensure_process_locked(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        if self._process is not None:
            self._stop_process_locked(graceful=False)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if self._log is None:
            self._log = self.log_path.open("ab", buffering=0)
        try:
            self._process = self._process_factory(
                [self.inkscape, "--shell"],
                stdin=subprocess.PIPE,
                stdout=self._log,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            raise RuntimeError(f"failed to start Inkscape shell: {exc}") from exc
        if self._process.stdin is None:
            self._stop_process_locked(graceful=False)
            raise RuntimeError("Inkscape shell started without stdin")
        self.starts += 1

    def _stop_process_locked(self, *, graceful: bool) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.poll() is None and graceful and process.stdin is not None:
            try:
                process.stdin.write("quit\n")
                process.stdin.flush()
                process.wait(timeout=3)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                pass
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                    process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass

    def _wait_for_png_locked(self, destination: Path) -> None:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            process = self._process
            if process is None or process.poll() is not None:
                code = None if process is None else process.returncode
                raise RuntimeError(f"Inkscape shell exited during render (exit {code})")
            if destination.is_file() and destination.stat().st_size:
                try:
                    with Image.open(destination) as image:
                        image.verify()
                    return
                except (OSError, SyntaxError):
                    pass
            time.sleep(0.02)
        raise RuntimeError(f"Inkscape shell render timed out after {self.timeout:g}s")

    def _render_once_locked(self, source: Path, destination: Path, width: int) -> None:
        self._ensure_process_locked()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.unlink(missing_ok=True)
        actions = "; ".join(
            [
                f"file-open:{_shell_path(source)}",
                "export-area-drawing",
                "export-background-opacity:0",
                f"export-width:{width}",
                f"export-filename:{_shell_path(destination)}",
                "export-do",
                "file-close",
            ]
        )
        process = self._process
        assert process is not None and process.stdin is not None
        try:
            process.stdin.write(actions + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError("failed to submit render to Inkscape shell") from exc
        self._wait_for_png_locked(destination)

    def render(self, source: Path, destination: Path, *, width: int) -> None:
        if width <= 0:
            raise ValueError("render width must be positive")
        with self.lock:
            if self.closed:
                raise RuntimeError("Inkscape renderer is closed")
            last_error = None
            for attempt in range(2):
                try:
                    self._render_once_locked(source, destination, width)
                    return
                except RuntimeError as exc:
                    last_error = exc
                    self._stop_process_locked(graceful=False)
                    destination.unlink(missing_ok=True)
                    if attempt == 0:
                        self.restarts += 1
                        continue
            raise RuntimeError(
                f"Inkscape shell render failed after restart: {last_error}; see {self.log_path}"
            ) from last_error

    def close(self) -> None:
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self._stop_process_locked(graceful=True)
            if self._log is not None:
                self._log.close()
                self._log = None


def render_review_png(
    source: Path,
    cache: Path,
    *,
    renderer: PersistentInkscapeShell,
    size: int,
) -> Path:
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    key = hashlib.sha256(f"review-v1\0{digest}\0{size}".encode()).hexdigest()
    destination = cache / f"{key}.png"
    if destination.is_file():
        return destination
    cache.mkdir(parents=True, exist_ok=True)
    # Keep the cache check, Inkscape export, framing and atomic publish under the same
    # renderer lock so simultaneous HTTP requests cannot render the same source twice.
    with renderer.lock:
        if destination.is_file():
            return destination
        with tempfile.TemporaryDirectory(prefix="svg-review-", dir=cache) as directory:
            raw = Path(directory) / "raw.png"
            renderer.render(source, raw, width=size * 2)
            framed = Path(directory) / "framed.png"
            _fit_square(raw, framed, size)
            os.replace(framed, destination)
    return destination


def _rule_applies(rule: dict, row: dict) -> bool:
    if rule.get("army_paths"):
        return row["army_path"] in rule["army_paths"]
    return bool(set(row["subjects"]).intersection(rule.get("army_subjects", [])))


def _review_rule(decisions: dict, row: dict) -> tuple[int, dict] | None:
    matches = [
        (index, rule)
        for index, rule in enumerate(decisions.get("rules", []))
        if rule.get("status") in REVIEWED_STATUSES and _rule_applies(rule, row)
    ]
    if len(matches) > 1:
        raise ValueError(f"multiple reviewed rules apply to {row['army_path']}")
    return matches[0] if matches else None


def _source_for_row(row: dict) -> dict:
    return next(
        (source for source in row["source_assets"] if source["path"] == row["army_path"]),
        row["source_assets"][0],
    )


def update_decisions(report: dict, decisions: dict, payload: dict) -> dict:
    army_path = str(payload.get("army_path", ""))
    decision = str(payload.get("decision", ""))
    if decision not in DECISIONS:
        raise ValueError("invalid review decision")
    row = next((item for item in report["assets"] if item["army_path"] == army_path), None)
    if row is None:
        raise ValueError("unknown Army asset")

    updated = json.loads(json.dumps(decisions))
    updated.setdefault("rules", [])
    existing = _review_rule(updated, row)
    if existing and existing[1].get("army_paths") != [army_path]:
        raise ValueError("subject-scoped reviewed rules cannot be edited in the visual reviewer")
    if existing:
        updated["rules"].pop(existing[0])

    if decision == "unresolved":
        return updated

    evidence = str(payload.get("evidence", "")).strip()
    if not evidence:
        raise ValueError("review evidence is required")
    selected = [str(path) for path in payload.get("vyo_paths", [])]
    candidates = {candidate["path"]: candidate for candidate in row["candidates"]}
    if len(set(selected)) != len(selected) or not set(selected).issubset(candidates):
        raise ValueError("review selected an unavailable Vyo candidate")

    reasons = sorted(
        {
            str(reason).strip()
            for reason in payload.get("reasons", [])
            if str(reason).strip()
        }
    )
    if decision in {"cleanup", "mismatch"} and not reasons:
        raise ValueError("cleanup and design-mismatch decisions require at least one reason")

    if decision == "missing":
        if selected:
            raise ValueError("confirmed absence cannot select a Vyo source")
        if payload.get("confirm_missing") is not True:
            raise ValueError("confirmed absence requires explicit confirmation")
        status, action = "confirmed-missing", "reconstruct"
    else:
        if not selected:
            raise ValueError("select at least one Vyo candidate")
        status = "reviewed-design-mismatch" if decision == "mismatch" else "reviewed-match"
        action = {"reuse": "reuse", "cleanup": "minor-cleanup", "mismatch": "reconstruct"}[decision]

    rule = {
        "army_paths": [army_path],
        "status": status,
        "action": action,
        "reasons": reasons,
        "evidence": evidence,
        "review_source_assets": [
            {key: source[key] for key in ("path", "sha256")}
            for source in [_source_for_row(row)]
        ],
        "publication_approved": False,
    }
    if selected:
        rule["vyo_paths"] = selected
        rule["review_vyo_assets"] = [
            {"path": path, "sha256": candidates[path]["sha256"]} for path in selected
        ]
    if existing and status == "reviewed-design-mismatch" and existing[1].get("fallback"):
        rule["fallback"] = existing[1]["fallback"]
    updated["rules"].append(rule)
    return updated


def _exact_reviews(decisions: dict) -> dict[str, dict]:
    result = {}
    for rule in decisions.get("rules", []):
        if rule.get("status") not in REVIEWED_STATUSES or len(rule.get("army_paths", [])) != 1:
            continue
        result[rule["army_paths"][0]] = {
            "status": rule["status"],
            "action": rule.get("action"),
            "vyo_paths": rule.get("vyo_paths", []),
            "reasons": rule.get("reasons", []),
            "evidence": rule.get("evidence", ""),
        }
    return result


def public_state(report: dict, decisions: dict) -> dict:
    reviews = _exact_reviews(decisions)
    assets = []
    for row in report["assets"]:
        source = _source_for_row(row) if row["source_assets"] else None
        assets.append(
            {
                "army_path": row["army_path"],
                "scope": row["scope"],
                "subjects": row["subjects"],
                "unit_slugs": row["unit_slugs"],
                "profile_names": row["profile_names"],
                "identity_status": row["identity_status"],
                "action": row["action"],
                "evidence": row["evidence"],
                "army_source": source,
                "candidates": [
                    {
                        "path": candidate["path"],
                        "subject": candidate["subject"],
                        "tags": candidate["tags"],
                        "matched_by": candidate["matched_by"],
                        "action": candidate["action"],
                        "reasons": candidate["reasons"],
                    }
                    for candidate in row["candidates"]
                ],
                "review": reviews.get(row["army_path"]),
            }
        )
    return {"summary": report["summary"], "assets": assets}


def _run_identity(config: ReviewConfig, decisions_path: Path, output: Path) -> int:
    return vyo_identity.main(
        [
            str(config.inventory),
            str(config.army_manifest),
            str(config.publication_manifest),
            "--decisions",
            str(decisions_path),
            "--output",
            str(output),
        ]
    )


def rebuild(config: ReviewConfig) -> dict:
    config.output.mkdir(parents=True, exist_ok=True)
    if _run_identity(config, config.decisions, config.output) != 0:
        raise RuntimeError("identity rebuild failed")
    return load_json(config.output / "vyo-army-identity-map.json")


def save_review(config: ReviewConfig, report: dict, payload: dict) -> dict:
    current = load_json(config.decisions)
    updated = update_decisions(report, current, payload)
    with tempfile.TemporaryDirectory(
        prefix="vyo-review-save-", dir=config.output.parent
    ) as directory:
        staging = Path(directory)
        staged_decisions = staging / "decisions.json"
        staged_output = staging / "output"
        atomic_write_json(staged_decisions, updated)
        if _run_identity(config, staged_decisions, staged_output) != 0:
            raise RuntimeError("updated review decision failed identity validation")
        atomic_write_json(config.decisions, updated)
        config.output.mkdir(parents=True, exist_ok=True)
        for source in staged_output.iterdir():
            os.replace(source, config.output / source.name)
    return load_json(config.output / "vyo-army-identity-map.json")


class ReviewApplication:
    def __init__(self, config: ReviewConfig):
        self.config = config
        self.lock = threading.RLock()
        self.token = secrets.token_urlsafe(32)
        self.renderer = PersistentInkscapeShell(
            config.inkscape,
            log_path=config.cache / "inkscape-shell.log",
            timeout=config.render_timeout,
        )
        # Start before rebuilding the identity map so Inkscape can initialize while
        # the Python-side report work runs.
        self.renderer.start()
        try:
            self.report = rebuild(config)
        except BaseException:
            self.renderer.close()
            raise

    def state(self) -> dict:
        with self.lock:
            state = public_state(self.report, load_json(self.config.decisions))
            state["review_token"] = self.token
            return state

    def save(self, payload: dict) -> dict:
        with self.lock:
            self.report = save_review(self.config, self.report, payload)
            state = public_state(self.report, load_json(self.config.decisions))
            state["review_token"] = self.token
            return state

    def render(self, source_kind: str, relative: str) -> Path:
        root = self.config.army_root if source_kind == "army" else self.config.vyo_root
        source = safe_svg_path(root, relative)
        return render_review_png(
            source,
            self.config.cache,
            renderer=self.renderer,
            size=self.config.render_size,
        )

    def close(self) -> None:
        self.renderer.close()


class ReviewHandler(BaseHTTPRequestHandler):
    server_version = "InfinitySvgReview/1"

    @property
    def app(self) -> ReviewApplication:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _headers(self, status: HTTPStatus, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'",
        )
        self.end_headers()

    def _bytes(self, data: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._headers(status, content_type, len(data))
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, data: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._bytes(
            json.dumps(data, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json({"error": message}, status)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/state":
                self._json(self.app.state())
                return
            if parsed.path in {"/render/army", "/render/vyo"}:
                query = parse_qs(parsed.query)
                relative = query.get("path", [""])[0]
                kind = parsed.path.rsplit("/", 1)[1]
                rendered = self.app.render(kind, relative)
                self._bytes(rendered.read_bytes(), "image/png")
                return
            static = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/review.css": ("review.css", "text/css; charset=utf-8"),
                "/review.js": ("review.js", "text/javascript; charset=utf-8"),
            }.get(parsed.path)
            if static:
                package = resources.files("infinity_svg_research.vyo_review_web")
                self._bytes(package.joinpath(static[0]).read_bytes(), static[1])
                return
            self._error(HTTPStatus.NOT_FOUND, "not found")
        except FileNotFoundError as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc))
        except (RuntimeError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/review":
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        try:
            if not secrets.compare_digest(self.headers.get("X-Review-Token", ""), self.app.token):
                self._error(HTTPStatus.FORBIDDEN, "invalid review token")
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 64 * 1024:
                raise ValueError("invalid request size")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("review payload must be an object")
            self._json(self.app.save(payload))
        except (json.JSONDecodeError, RuntimeError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))


def _existing_directory(value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"directory does not exist: {value}")
    return path


def _existing_file(value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"file does not exist: {value}")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=_existing_file)
    parser.add_argument("army_manifest", type=_existing_file)
    parser.add_argument("publication_manifest", type=_existing_file)
    parser.add_argument("--decisions", type=_existing_file, required=True)
    parser.add_argument("--army-root", type=_existing_directory, required=True)
    parser.add_argument("--vyo-root", type=_existing_directory, required=True)
    parser.add_argument("--output", type=Path, default=Path("output/vyo-review"))
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--inkscape", default="inkscape")
    parser.add_argument("--render-size", type=int, default=512)
    parser.add_argument("--render-timeout", type=float, default=60.0)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if not 128 <= args.render_size <= 2048:
        parser.error("--render-size must be between 128 and 2048")
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    if args.render_timeout <= 0:
        parser.error("--render-timeout must be positive")

    output = args.output.resolve()
    cache = (args.cache or output / "render-cache").resolve()
    config = ReviewConfig(
        inventory=args.inventory,
        army_manifest=args.army_manifest,
        publication_manifest=args.publication_manifest,
        decisions=args.decisions,
        army_root=args.army_root,
        vyo_root=args.vyo_root,
        output=output,
        cache=cache,
        inkscape=args.inkscape,
        render_size=args.render_size,
        render_timeout=args.render_timeout,
    )
    app = ReviewApplication(config)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), ReviewHandler)
    server.app = app  # type: ignore[attr-defined]
    address = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Vyo visual reviewer: {address}")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping reviewer.")
    finally:
        app.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
