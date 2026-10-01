from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Literal, Sequence

import numpy as np
from PIL import Image

RendererMode = Literal["inkscape-shell", "inkscape-one-shot"]


@dataclass
class RenderMetrics:
    size: int
    width: int
    height: int
    exact: bool
    changed_pixels: int
    changed_pixel_fraction: float
    max_channel_diff: int
    rgba_rmse: float
    premultiplied_rgba_rmse: float
    white_background_rgb_rmse: float
    alpha_rmse: float
    original_png: str
    candidate_png: str
    diff_png: str | None


@dataclass
class ValidationRun:
    metrics: list[RenderMetrics]
    renderer_mode: RendererMode
    renderer_processes: int
    document_opens: int
    exports: int
    render_seconds: float
    compare_seconds: float
    total_seconds: float


@dataclass(frozen=True)
class ShellRenderJob:
    original: Path
    candidate: Path
    output_dir: Path


@dataclass
class ShellBatchTiming:
    index: int
    cases: int
    seconds: float


@dataclass
class ShellBatchRun:
    inkscape_version: str | None
    renderer_processes: int
    document_opens: int
    exports: int
    render_seconds: float
    batches: list[ShellBatchTiming]


def find_inkscape(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    executable = shutil.which("inkscape")
    if executable is None:
        raise RuntimeError("Inkscape was not found on PATH")
    return executable


def _shell_path(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    if ";" in value or "\n" in value or "\r" in value:
        raise RuntimeError(f"Inkscape shell paths cannot contain ';' or newlines: {path}")
    return value


def render_svg(svg: Path, png: Path, size: int, *, inkscape: str) -> None:
    """Reference/debug renderer: one Inkscape process for one export."""
    png.parent.mkdir(parents=True, exist_ok=True)
    command = [
        inkscape,
        str(svg),
        "--export-area-page",
        f"--export-width={size}",
        f"--export-filename={png}",
        "--export-background-opacity=0",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Inkscape failed for {svg} at {size}px (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    if not png.exists():
        raise RuntimeError(f"Inkscape reported success but did not create {png}")


def _shell_export_actions(svg: Path, outputs: list[tuple[int, Path]]) -> str:
    actions = [
        f"file-open:{_shell_path(svg)}",
        "export-area-page",
        "export-background-opacity:0",
    ]
    for size, png in outputs:
        png.parent.mkdir(parents=True, exist_ok=True)
        if png.exists():
            png.unlink()
        actions.extend(
            [
                f"export-width:{size}",
                f"export-filename:{_shell_path(png)}",
                "export-do",
            ]
        )
    actions.append("file-close")
    return "; ".join(actions)


def _job_outputs(job: ShellRenderJob, sizes: tuple[int, ...]) -> tuple[list[tuple[int, Path]], list[tuple[int, Path]]]:
    original_outputs = [(size, job.output_dir / f"original-{size}.png") for size in sizes]
    candidate_outputs = [(size, job.output_dir / f"candidate-{size}.png") for size in sizes]
    return original_outputs, candidate_outputs


def _parse_shell_version(output: str) -> str | None:
    for line in output.splitlines():
        candidate = line.strip().lstrip("> ").strip()
        if re.match(r"^Inkscape\s+\d", candidate):
            return candidate
    return None


def _run_shell_batch(
    jobs: Sequence[ShellRenderJob],
    sizes: tuple[int, ...],
    *,
    inkscape: str,
    include_version: bool,
) -> tuple[float, str | None]:
    lines: list[str] = []
    if include_version:
        # This is an Inkscape shell action, so it does not require a second process startup.
        lines.append("inkscape-version")

    expected: list[Path] = []
    for job in jobs:
        original_outputs, candidate_outputs = _job_outputs(job, sizes)
        expected.extend(path for _, path in (*original_outputs, *candidate_outputs))
        lines.append(_shell_export_actions(job.original, original_outputs))
        lines.append(_shell_export_actions(job.candidate, candidate_outputs))
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
    combined_output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if result.returncode != 0:
        raise RuntimeError(
            f"Inkscape shell failed (exit {result.returncode}): {combined_output.strip()}"
        )

    missing = [str(path) for path in expected if not path.exists()]
    if missing:
        details = combined_output.strip()
        raise RuntimeError(
            "Inkscape shell exited without creating all requested renders: "
            + ", ".join(missing)
            + (f"; output: {details}" if details else "")
        )
    return elapsed, (_parse_shell_version(combined_output) if include_version else None)


def render_svg_pairs_shell_batch(
    jobs: Sequence[ShellRenderJob],
    sizes: Iterable[int],
    *,
    inkscape: str,
    restart_every: int = 0,
) -> ShellBatchRun:
    """Render all source/candidate pairs using one shell for the run by default.

    ``restart_every`` bounds the number of cases per shell. Zero means keep a single
    Inkscape process for every case in the run.
    """
    if restart_every < 0:
        raise ValueError("restart_every must be >= 0")
    size_tuple = tuple(sizes)
    job_list = list(jobs)
    if not job_list:
        return ShellBatchRun(
            inkscape_version=None,
            renderer_processes=0,
            document_opens=0,
            exports=0,
            render_seconds=0.0,
            batches=[],
        )

    batch_size = restart_every if restart_every > 0 else len(job_list)
    batches: list[ShellBatchTiming] = []
    version: str | None = None
    total_seconds = 0.0
    process_count = 0
    for start in range(0, len(job_list), batch_size):
        batch = job_list[start : start + batch_size]
        elapsed, batch_version = _run_shell_batch(
            batch,
            size_tuple,
            inkscape=inkscape,
            include_version=(process_count == 0),
        )
        total_seconds += elapsed
        if batch_version is not None:
            version = batch_version
        batches.append(ShellBatchTiming(index=process_count, cases=len(batch), seconds=elapsed))
        process_count += 1

    return ShellBatchRun(
        inkscape_version=version,
        renderer_processes=process_count,
        document_opens=2 * len(job_list),
        exports=2 * len(size_tuple) * len(job_list),
        render_seconds=total_seconds,
        batches=batches,
    )


def render_svg_pairs_shell(
    original: Path,
    candidate: Path,
    output_dir: Path,
    sizes: tuple[int, ...],
    *,
    inkscape: str,
) -> float:
    """Compatibility helper: render one pair in one shell process."""
    run = render_svg_pairs_shell_batch(
        [ShellRenderJob(original=original, candidate=candidate, output_dir=output_dir)],
        sizes,
        inkscape=inkscape,
    )
    return run.render_seconds


def _load_rgba(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA"), dtype=np.uint8)


def _rmse(left: np.ndarray, right: np.ndarray) -> float:
    delta = left.astype(np.float64) - right.astype(np.float64)
    return float(math.sqrt(np.mean(delta * delta)))


def _premultiplied_rgba(array: np.ndarray) -> np.ndarray:
    rgba = array.astype(np.float64)
    alpha = rgba[..., 3:4] / 255.0
    rgb = rgba[..., :3] * alpha
    return np.concatenate([rgb, rgba[..., 3:4]], axis=2)


def _white_background_rgb(array: np.ndarray) -> np.ndarray:
    rgba = array.astype(np.float64)
    alpha = rgba[..., 3:4] / 255.0
    return rgba[..., :3] * alpha + 255.0 * (1.0 - alpha)


def _write_diff(left: np.ndarray, right: np.ndarray, path: Path) -> None:
    delta = np.abs(left.astype(np.int16) - right.astype(np.int16)).astype(np.uint8)
    rgb = np.maximum(delta[..., :3], delta[..., 3:4])
    rgb = np.clip(rgb.astype(np.uint16) * 8, 0, 255).astype(np.uint8)
    Image.fromarray(rgb, mode="RGB").save(path)


def compare_rendered(
    original_png: Path,
    candidate_png: Path,
    *,
    size: int,
    diff_png: Path | None,
) -> RenderMetrics:
    original = _load_rgba(original_png)
    candidate = _load_rgba(candidate_png)
    if original.shape != candidate.shape:
        raise RuntimeError(
            f"Rendered dimensions differ: {original_png}={original.shape}, "
            f"{candidate_png}={candidate.shape}"
        )

    channel_delta = np.abs(original.astype(np.int16) - candidate.astype(np.int16))
    changed_mask = np.any(channel_delta != 0, axis=2)
    changed_pixels = int(np.count_nonzero(changed_mask))
    total_pixels = int(changed_mask.size)
    exact = changed_pixels == 0

    if diff_png is not None and not exact:
        diff_png.parent.mkdir(parents=True, exist_ok=True)
        _write_diff(original, candidate, diff_png)
    elif diff_png is not None and diff_png.exists():
        diff_png.unlink()

    return RenderMetrics(
        size=size,
        width=int(original.shape[1]),
        height=int(original.shape[0]),
        exact=exact,
        changed_pixels=changed_pixels,
        changed_pixel_fraction=(changed_pixels / total_pixels if total_pixels else 0.0),
        max_channel_diff=int(channel_delta.max()) if channel_delta.size else 0,
        rgba_rmse=_rmse(original, candidate),
        premultiplied_rgba_rmse=_rmse(_premultiplied_rgba(original), _premultiplied_rgba(candidate)),
        white_background_rgb_rmse=_rmse(_white_background_rgb(original), _white_background_rgb(candidate)),
        alpha_rmse=_rmse(original[..., 3], candidate[..., 3]),
        original_png=str(original_png),
        candidate_png=str(candidate_png),
        diff_png=(str(diff_png) if diff_png is not None and diff_png.exists() else None),
    )


def compare_pair_outputs(output_dir: Path, sizes: Iterable[int]) -> tuple[list[RenderMetrics], float]:
    started = time.perf_counter()
    results: list[RenderMetrics] = []
    for size in tuple(sizes):
        original_png = output_dir / f"original-{size}.png"
        candidate_png = output_dir / f"candidate-{size}.png"
        diff_png = output_dir / f"diff-{size}.png"
        results.append(
            compare_rendered(
                original_png,
                candidate_png,
                size=size,
                diff_png=diff_png,
            )
        )
    return results, time.perf_counter() - started


def validate_svg_pair(
    original: Path,
    candidate: Path,
    output_dir: Path,
    *,
    sizes: Iterable[int] = (64, 128, 256, 1024),
    inkscape: str | None = None,
    renderer_mode: RendererMode = "inkscape-shell",
) -> ValidationRun:
    renderer = find_inkscape(inkscape)
    size_tuple = tuple(sizes)
    output_dir.mkdir(parents=True, exist_ok=True)
    total_started = time.perf_counter()

    render_started = time.perf_counter()
    if renderer_mode == "inkscape-shell":
        render_svg_pairs_shell(
            original,
            candidate,
            output_dir,
            size_tuple,
            inkscape=renderer,
        )
        renderer_processes = 1
        document_opens = 2
    elif renderer_mode == "inkscape-one-shot":
        for size in size_tuple:
            render_svg(original, output_dir / f"original-{size}.png", size, inkscape=renderer)
            render_svg(candidate, output_dir / f"candidate-{size}.png", size, inkscape=renderer)
        renderer_processes = 2 * len(size_tuple)
        document_opens = 2 * len(size_tuple)
    else:
        raise ValueError(f"Unsupported renderer mode: {renderer_mode}")
    render_seconds = time.perf_counter() - render_started

    results, compare_seconds = compare_pair_outputs(output_dir, size_tuple)

    return ValidationRun(
        metrics=results,
        renderer_mode=renderer_mode,
        renderer_processes=renderer_processes,
        document_opens=document_opens,
        exports=2 * len(size_tuple),
        render_seconds=render_seconds,
        compare_seconds=compare_seconds,
        total_seconds=time.perf_counter() - total_started,
    )


def parse_sizes(text: str) -> tuple[int, ...]:
    sizes = tuple(int(value.strip()) for value in text.split(",") if value.strip())
    if not sizes or any(value <= 0 for value in sizes):
        raise argparse.ArgumentTypeError("sizes must be positive comma-separated integers")
    return sizes


def main() -> int:
    parser = argparse.ArgumentParser(description="Render and compare two SVGs at multiple sizes.")
    parser.add_argument("original", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("render-compare"))
    parser.add_argument("--sizes", type=parse_sizes, default=(64, 128, 256, 1024))
    parser.add_argument("--inkscape")
    parser.add_argument(
        "--renderer",
        choices=("inkscape-shell", "inkscape-one-shot"),
        default="inkscape-shell",
    )
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    run = validate_svg_pair(
        args.original,
        args.candidate,
        args.output_dir,
        sizes=args.sizes,
        inkscape=args.inkscape,
        renderer_mode=args.renderer,
    )
    payload = {
        "original": str(args.original),
        "candidate": str(args.candidate),
        "exact": all(result.exact for result in run.metrics),
        "renderer": {
            "mode": run.renderer_mode,
            "processes": run.renderer_processes,
            "document_opens": run.document_opens,
            "exports": run.exports,
        },
        "timing_seconds": {
            "render": run.render_seconds,
            "compare": run.compare_seconds,
            "total": run.total_seconds,
        },
        "renders": [asdict(result) for result in run.metrics],
    }
    print(json.dumps(payload, indent=2))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0 if payload["exact"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
