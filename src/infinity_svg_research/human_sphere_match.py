from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .render_compare import find_inkscape

PNG_SUFFIXES = {".png"}
SVG_SUFFIXES = {".svg"}
NOISE_TOKENS = {
    "infinity", "logo", "logos", "symbol", "symbols", "icon", "icons",
    "n1", "n2", "n3", "n4", "n5", "vyo", "vyo0", "wiki",
    "sectorial", "sectorials", "unit", "units", "troop", "troops",
}
VERSION_RE = re.compile(r"^(?:v\d+|n\d+|\d+x\d+)$")
SVG_PROFILE_TAIL_RE = re.compile(r"(?:-null)?-\d+-\d+$")


@dataclass
class ImageInventory:
    path: str
    relative_path: str
    bytes: int
    sha256: str
    width: int
    height: int
    mode: str
    has_alpha: bool
    normalized_name: str
    tokens: list[str]


@dataclass
class SvgInventory:
    path: str
    relative_path: str
    bytes: int
    sha256: str
    normalized_name: str
    tokens: list[str]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _ascii(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return normalized.encode("ascii", "ignore").decode("ascii")


def normalize_name(path: Path, *, svg: bool) -> tuple[str, list[str]]:
    stem = path.stem.lower()
    if svg:
        stem = SVG_PROFILE_TAIL_RE.sub("", stem)
        stem = re.sub(r"^reinf-", "", stem)
    stem = _ascii(stem)
    raw = re.findall(r"[a-z0-9]+", stem)
    tokens: list[str] = []
    for token in raw:
        if token in NOISE_TOKENS or VERSION_RE.match(token):
            continue
        # Wiki filenames often contain bare provenance/revision counters.
        if token.isdigit() and len(token) <= 4:
            continue
        tokens.append(token)
    return "-".join(tokens), tokens


def discover(root: Path, suffixes: set[str]) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() in suffixes else []
    return sorted(
        (p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in suffixes),
        key=lambda p: str(p).lower(),
    )


def inventory_pngs(root: Path) -> tuple[list[ImageInventory], dict[str, list[int]]]:
    rows: list[ImageInventory] = []
    duplicate_groups: dict[str, list[int]] = defaultdict(list)
    for path in discover(root, PNG_SUFFIXES):
        try:
            with Image.open(path) as im:
                width, height = im.size
                mode = im.mode
                has_alpha = "A" in im.getbands() or "transparency" in im.info
        except Exception:
            continue
        digest = sha256(path)
        normalized, tokens = normalize_name(path, svg=False)
        idx = len(rows)
        rows.append(
            ImageInventory(
                path=str(path),
                relative_path=str(path.relative_to(root)) if root.is_dir() else path.name,
                bytes=path.stat().st_size,
                sha256=digest,
                width=width,
                height=height,
                mode=mode,
                has_alpha=has_alpha,
                normalized_name=normalized,
                tokens=tokens,
            )
        )
        duplicate_groups[digest].append(idx)
    return rows, duplicate_groups


def inventory_svgs(root: Path) -> list[SvgInventory]:
    rows: list[SvgInventory] = []
    for path in discover(root, SVG_SUFFIXES):
        normalized, tokens = normalize_name(path, svg=True)
        rows.append(
            SvgInventory(
                path=str(path),
                relative_path=str(path.relative_to(root)) if root.is_dir() else path.name,
                bytes=path.stat().st_size,
                sha256=sha256(path),
                normalized_name=normalized,
                tokens=tokens,
            )
        )
    return rows


def lexical_candidates(
    svgs: list[SvgInventory],
    pngs: list[ImageInventory],
    *,
    top: int,
) -> list[list[dict[str, Any]]]:
    token_to_pngs: dict[str, list[int]] = defaultdict(list)
    token_freq = Counter()
    for index, row in enumerate(pngs):
        unique = set(row.tokens)
        for token in unique:
            token_to_pngs[token].append(index)
            token_freq[token] += 1

    def weight(token: str) -> float:
        return math.log((len(pngs) + 2) / (token_freq[token] + 1)) + 1.0

    results: list[list[dict[str, Any]]] = []
    for svg in svgs:
        candidate_ids: set[int] = set()
        for token in set(svg.tokens):
            candidate_ids.update(token_to_pngs.get(token, []))

        scored: list[dict[str, Any]] = []
        svg_set = set(svg.tokens)
        svg_weight = sum(weight(t) for t in svg_set) or 1.0
        for idx in candidate_ids:
            png = pngs[idx]
            png_set = set(png.tokens)
            shared = svg_set & png_set
            shared_weight = sum(weight(t) for t in shared)
            svg_coverage = shared_weight / svg_weight
            png_weight = sum(weight(t) for t in png_set) or 1.0
            png_coverage = shared_weight / png_weight
            seq = SequenceMatcher(None, svg.normalized_name, png.normalized_name).ratio()
            substring = float(
                bool(svg.normalized_name)
                and (
                    svg.normalized_name in png.normalized_name
                    or png.normalized_name in svg.normalized_name
                )
            )
            score = 0.58 * svg_coverage + 0.10 * png_coverage + 0.22 * seq + 0.10 * substring
            scored.append(
                {
                    "png_index": idx,
                    "lexical_score": score,
                    "svg_token_coverage": svg_coverage,
                    "png_token_coverage": png_coverage,
                    "sequence_score": seq,
                    "substring": bool(substring),
                    "shared_tokens": sorted(shared),
                }
            )
        scored.sort(key=lambda item: (-item["lexical_score"], pngs[item["png_index"]].relative_path.lower()))
        results.append(scored[:top])
    return results


def _shell_path(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    if ";" in value or "\n" in value or "\r" in value:
        raise RuntimeError(f"Inkscape shell paths cannot contain ';' or newlines: {path}")
    return value


def render_svg_batch(paths: list[Path], output_dir: Path, size: int, inkscape: str) -> float:
    if not paths:
        return 0.0
    lines = ["inkscape-version"]
    expected: list[Path] = []
    for idx, path in enumerate(paths):
        png = output_dir / f"svg-{idx:05d}.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        if png.exists():
            png.unlink()
        expected.append(png)
        lines.append(
            "; ".join(
                [
                    f"file-open:{_shell_path(path)}",
                    "export-area-page",
                    "export-background-opacity:0",
                    f"export-width:{size}",
                    f"export-filename:{_shell_path(png)}",
                    "export-do",
                    "file-close",
                ]
            )
        )
    lines.extend(["quit", ""])
    started = time.perf_counter()
    result = subprocess.run(
        [inkscape, "--shell"],
        input="\n".join(lines),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise RuntimeError(f"Inkscape shell failed: {result.stderr.strip() or result.stdout.strip()}")
    missing = [str(p) for p in expected if not p.exists()]
    if missing:
        raise RuntimeError("Missing SVG renders: " + ", ".join(missing[:10]))
    return elapsed


def _crop_content(rgba: np.ndarray) -> np.ndarray:
    alpha = rgba[:, :, 3]
    if np.any(alpha < 250) and np.any(alpha > 8):
        mask = alpha > 8
    else:
        rgb = rgba[:, :, :3].astype(np.float32)
        # For opaque images, identify pixels differing from the corner background.
        corners = np.stack([rgb[0, 0], rgb[0, -1], rgb[-1, 0], rgb[-1, -1]])
        bg = np.median(corners, axis=0)
        mask = np.linalg.norm(rgb - bg, axis=2) > 8.0
        if not np.any(mask):
            mask = np.ones(alpha.shape, dtype=bool)
    ys, xs = np.where(mask)
    if not len(xs):
        return rgba
    return rgba[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def _descriptor(path: Path, size: int = 96) -> dict[str, np.ndarray]:
    with Image.open(path) as im:
        rgba = np.asarray(im.convert("RGBA"), dtype=np.float32)
    rgba = _crop_content(rgba)
    im = Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8), "RGBA").resize((size, size), Image.Resampling.LANCZOS)
    a = np.asarray(im, dtype=np.float32) / 255.0
    alpha = a[:, :, 3]
    rgb = a[:, :, :3] * alpha[:, :, None] + (1.0 - alpha[:, :, None])
    gray = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    gx[:, 1:] = np.abs(np.diff(gray, axis=1))
    gy[1:, :] = np.abs(np.diff(gray, axis=0))
    edge = np.sqrt(gx * gx + gy * gy)
    return {"gray": gray, "edge": edge, "alpha": alpha}


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    av = a.ravel().astype(np.float64)
    bv = b.ravel().astype(np.float64)
    av -= av.mean()
    bv -= bv.mean()
    denom = np.linalg.norm(av) * np.linalg.norm(bv)
    if denom <= 1e-12:
        return 1.0 if np.allclose(av, bv) else 0.0
    return float(np.dot(av, bv) / denom)


def visual_similarity(left: dict[str, np.ndarray], right: dict[str, np.ndarray]) -> dict[str, float]:
    edge = max(0.0, _corr(left["edge"], right["edge"]))
    gray_corr = max(
        _corr(left["gray"], right["gray"]),
        _corr(left["gray"], 1.0 - right["gray"]),
        0.0,
    )
    lm = left["alpha"] > 0.5
    rm = right["alpha"] > 0.5
    union = int(np.logical_or(lm, rm).sum())
    alpha_iou = float(np.logical_and(lm, rm).sum() / union) if union else 1.0
    score = 0.60 * edge + 0.25 * gray_corr + 0.15 * alpha_iou
    return {
        "visual_score": score,
        "edge_correlation": edge,
        "gray_correlation": gray_corr,
        "alpha_iou": alpha_iou,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Match Human Sphere PNG media to Army SVG assets.")
    parser.add_argument("svg_root", type=Path)
    parser.add_argument("png_root", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("human-sphere-match"))
    parser.add_argument("--top", type=int, default=8, help="lexical candidates retained per SVG")
    parser.add_argument("--visual", action="store_true", help="render SVGs and score retained candidates visually")
    parser.add_argument("--visual-top", type=int, default=5, help="number of lexical candidates visually scored")
    parser.add_argument("--visual-size", type=int, default=256)
    parser.add_argument("--inkscape")
    args = parser.parse_args()

    started = time.perf_counter()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pngs, dup_groups = inventory_pngs(args.png_root)
    svgs = inventory_svgs(args.svg_root)
    candidates = lexical_candidates(svgs, pngs, top=max(1, args.top))

    render_seconds = 0.0
    if args.visual:
        inkscape = find_inkscape(args.inkscape)
        active_svg_indexes = [i for i, rows in enumerate(candidates) if rows[: args.visual_top]]
        render_paths = [Path(svgs[i].path) for i in active_svg_indexes]
        render_dir = args.output_dir / "svg-renders"
        render_seconds = render_svg_batch(render_paths, render_dir, args.visual_size, inkscape)
        svg_descriptors: dict[int, dict[str, np.ndarray]] = {}
        for local_idx, svg_idx in enumerate(active_svg_indexes):
            svg_descriptors[svg_idx] = _descriptor(render_dir / f"svg-{local_idx:05d}.png")
        png_descriptor_cache: dict[str, dict[str, np.ndarray]] = {}
        for svg_idx, rows in enumerate(candidates):
            left = svg_descriptors.get(svg_idx)
            if left is None:
                continue
            for row in rows[: args.visual_top]:
                png = pngs[row["png_index"]]
                desc = png_descriptor_cache.get(png.sha256)
                if desc is None:
                    desc = _descriptor(Path(png.path))
                    png_descriptor_cache[png.sha256] = desc
                row.update(visual_similarity(left, desc))
                row["combined_score"] = 0.60 * row["lexical_score"] + 0.40 * row["visual_score"]
            rows.sort(key=lambda item: (-item.get("combined_score", item["lexical_score"]), pngs[item["png_index"]].relative_path.lower()))

    exact_duplicate_groups = [indexes for indexes in dup_groups.values() if len(indexes) > 1]
    match_rows: list[dict[str, Any]] = []
    csv_rows: list[dict[str, Any]] = []
    for svg_idx, svg in enumerate(svgs):
        rows = candidates[svg_idx]
        out_candidates = []
        for rank, row in enumerate(rows, 1):
            png = pngs[row["png_index"]]
            payload = {k: v for k, v in row.items() if k != "png_index"}
            payload.update({"rank": rank, "png": asdict(png)})
            out_candidates.append(payload)
            if rank == 1:
                csv_rows.append(
                    {
                        "svg": svg.relative_path,
                        "png": png.relative_path,
                        "lexical_score": f"{row['lexical_score']:.6f}",
                        "visual_score": f"{row.get('visual_score', 0.0):.6f}" if "visual_score" in row else "",
                        "combined_score": f"{row.get('combined_score', row['lexical_score']):.6f}",
                        "shared_tokens": " ".join(row["shared_tokens"]),
                    }
                )
        match_rows.append({"svg": asdict(svg), "candidates": out_candidates})

    manifest = {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Human Sphere PNG to Army SVG candidate matching",
        "policy": {
            "lexical_first": True,
            "visual_optional": args.visual,
            "human_sphere_authority": "third-party-non-authoritative",
            "automatic_acceptance": False,
            "independence_not_assumed": True,
            "note": (
                "Candidate ranking only. Human Sphere is not a first-party source; presence or visual "
                "similarity does not establish canonical artwork. Historical/revision mismatches and "
                "possible derivative copies require review before a PNG is used as restoration evidence."
            ),
        },
        "run": {
            "svg_root": str(args.svg_root),
            "png_root": str(args.png_root),
            "svg_count": len(svgs),
            "png_count": len(pngs),
            "png_exact_duplicate_groups": len(exact_duplicate_groups),
            "png_exact_duplicate_members": sum(len(g) for g in exact_duplicate_groups),
            "svgs_with_candidates": sum(bool(rows) for rows in candidates),
            "visual": args.visual,
            "visual_size": args.visual_size if args.visual else None,
            "render_seconds": render_seconds,
            "total_seconds": time.perf_counter() - started,
        },
        "matches": match_rows,
    }
    (args.output_dir / "matches.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (args.output_dir / "png-inventory.json").write_text(
        json.dumps({"pngs": [asdict(x) for x in pngs], "duplicate_groups": exact_duplicate_groups}, indent=2),
        encoding="utf-8",
    )
    (args.output_dir / "svg-inventory.json").write_text(
        json.dumps({"svgs": [asdict(x) for x in svgs]}, indent=2), encoding="utf-8"
    )
    with (args.output_dir / "top-matches.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["svg", "png", "lexical_score", "visual_score", "combined_score", "shared_tokens"])
        writer.writeheader()
        writer.writerows(csv_rows)

    print(f"SVGs: {len(svgs)} | PNGs: {len(pngs)} | SVGs with lexical candidates: {sum(bool(r) for r in candidates)}")
    print(f"Exact PNG duplicate groups: {len(exact_duplicate_groups)}")
    if args.visual:
        print(f"Visual SVG render time: {render_seconds:.2f}s")
    print(f"Wrote {args.output_dir / 'matches.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
