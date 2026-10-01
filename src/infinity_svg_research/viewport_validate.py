"""Validate a metadata-normalization run using original/candidate drawing renders."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from .render_compare import _shell_path


def validate_run(report_path: Path, *, inkscape: str, size: int = 128) -> dict:
    if size < 1:
        raise ValueError("render size must be positive")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("format") != "infinity-svg-viewport-normalization":
        raise ValueError("expected a viewport-normalization report")
    run = report_path.resolve().parent
    source_root = Path(report["source_root"])
    rows = [r for r in report["files"] if r["status"] == "normalized-review-required"]
    for row in rows:
        for path, expected in [
            (source_root / row["path"], row["source_sha256"]),
            (run / "svg" / row["path"], row["candidate_sha256"]),
        ]:
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"validation input hash mismatch: {path}")
    render_root = run / f"validation-{size}"
    render_root.mkdir(exist_ok=True)
    metrics = []
    version = None
    for start in range(0, len(rows), 80):
        batch = rows[start : start + 80]
        commands = ["inkscape-version"] if start == 0 else []
        for index, row in enumerate(batch, start):
            for label, path, area in [
                ("source", source_root / row["path"], "drawing"),
                ("candidate", run / "svg" / row["path"], "drawing"),
                ("page", run / "svg" / row["path"], "page"),
            ]:
                png = render_root / f"{index:03d}-{label}.png"
                if png.exists():
                    png.unlink()
                commands.append(
                    f"file-open:{_shell_path(path)};export-area-{area};export-width:{size};"
                    f"export-background-opacity:0;export-filename:{_shell_path(png)};export-do;file-close"
                )
        result = subprocess.run(
            [inkscape, "--shell"],
            input="\n".join(commands + ["quit", ""]),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr[-1500:])
        if start == 0:
            version = next(
                (
                    line
                    for line in result.stdout.splitlines()
                    if line.startswith("Inkscape ") and not line.startswith("Inkscape interactive")
                ),
                None,
            )
        for index, row in enumerate(batch, start):
            arrays = {
                label: np.array(
                    Image.open(render_root / f"{index:03d}-{label}.png").convert("RGBA")
                )
                for label in ("source", "candidate", "page")
            }
            source, candidate, page = (arrays[label] for label in ("source", "candidate", "page"))
            if source.shape != candidate.shape:
                raise ValueError("Drawing dimensions changed: " + row["path"])
            delta = source.astype(float) - candidate.astype(float)
            border = np.concatenate([page[0, :, 3], page[-1, :, 3], page[:, 0, 3], page[:, -1, 3]])
            metrics.append(
                {
                    "path": row["path"],
                    "source_sha256": row["source_sha256"],
                    "candidate_sha256": row["candidate_sha256"],
                    "size": size,
                    "drawing_render_exact": bool(np.array_equal(source, candidate)),
                    "rgba_rmse": float(np.sqrt(np.mean(delta**2))),
                    "alpha_rmse": float(np.sqrt(np.mean(delta[:, :, 3] ** 2))),
                    "page_alpha_bbox": Image.fromarray(page[:, :, 3]).getbbox(),
                    "page_size": [int(page.shape[1]), int(page.shape[0])],
                    "page_border_max_alpha": int(border.max()),
                }
            )
        print(f"Validated {min(start + 80, len(rows))}/{len(rows)}", flush=True)
    return {
        "format": "infinity-svg-vyo-viewport-validation",
        "version": 1,
        "inkscape_version": version,
        "size": size,
        "input_hashes_verified": True,
        "normalized": len(metrics),
        "blocked": len(report["files"]) - len(metrics),
        "drawing_render_exact": sum(m["drawing_render_exact"] for m in metrics),
        "max_rgba_rmse": max((m["rgba_rmse"] for m in metrics), default=0),
        "max_alpha_rmse": max((m["alpha_rmse"] for m in metrics), default=0),
        "page_border_nonzero": sum(m["page_border_max_alpha"] > 0 for m in metrics),
        "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "method": "Compare original and normalized drawing-area renders at the same output width. Separately inspect normalized page alpha bounds. This checks unchanged drawing appearance; it does not establish Vyo-to-Army fidelity or publication approval. Nonzero page border alpha can include antialiasing at small padding and is not itself a clipping diagnosis.",
        "files": metrics,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--inkscape", default="inkscape")
    parser.add_argument("--size", type=int, default=128)
    args = parser.parse_args(argv)
    summary = validate_run(args.report, inkscape=args.inkscape, size=args.size)
    output = args.report.parent / f"validation-{args.size}.json"
    output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "files"}, indent=2))
    return 0 if summary["drawing_render_exact"] == summary["normalized"] else 1
