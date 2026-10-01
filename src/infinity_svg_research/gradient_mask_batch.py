from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import render_compare

CLASSIFICATION = "flattened-gradient-mask"
DEFAULT_SIZES = (64, 128, 256, 512, 1024, 1600)


def _source_path(root: Path, relative_path: str) -> Path:
    parts = [part for part in re.split(r"[\\/]+", relative_path) if part]
    return root.joinpath(*parts)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_groups(scan_json: Path) -> list[dict[str, Any]]:
    document = json.loads(scan_json.read_text(encoding="utf-8"))
    files = document.get("files")
    if not isinstance(files, list):
        raise ValueError("scan JSON does not contain a files list")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in files:
        if not isinstance(row, dict) or row.get("classification") != CLASSIFICATION:
            continue
        sha256 = row.get("sha256")
        path = row.get("path")
        if not isinstance(sha256, str) or not sha256 or not isinstance(path, str) or not path:
            raise ValueError("flattened-gradient-mask scan row is missing path/sha256")
        grouped[sha256].append(row)

    groups: list[dict[str, Any]] = []
    for sha256, rows in grouped.items():
        rows = sorted(rows, key=lambda row: str(row["path"]).lower())
        groups.append(
            {
                "sha256": sha256,
                "paths": [str(row["path"]) for row in rows],
                "count": len(rows),
                "size_bytes": int(rows[0].get("size_bytes") or 0),
            }
        )
    groups.sort(key=lambda group: (group["paths"][0].lower(), group["sha256"]))
    return groups


def _case_summary(group: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    renders = manifest.get("renders") or []
    largest = max(renders, key=lambda row: int(row.get("size", 0)), default=None)
    reconstruction = manifest.get("reconstruction") or {}
    palette = reconstruction.get("dominant_palette") or []
    colors = [row.get("color") for row in palette if isinstance(row, dict) and row.get("color")]
    candidate_scan = manifest.get("candidate_scan") or {}
    return {
        "sha256": group["sha256"],
        "duplicate_count": group["count"],
        "paths": group["paths"],
        "representative": manifest.get("source"),
        "status": "ok",
        "source_size_bytes": manifest.get("source_size_bytes"),
        "candidate_size_bytes": manifest.get("candidate_size_bytes"),
        "byte_reduction_fraction": manifest.get("byte_reduction_fraction"),
        "palette_colors": colors,
        "match_mode": reconstruction.get("match_mode"),
        "gradient_count": reconstruction.get("gradient_count"),
        "candidate_classification": candidate_scan.get("classification"),
        "candidate_advisories": candidate_scan.get("advisories") or [],
        "candidate_signals": candidate_scan.get("signals") or [],
        "largest_render": largest,
        "render_summary": manifest.get("render_summary"),
        "case_manifest": str(Path(manifest.get("candidate", "")).parent / "manifest.json"),
    }


def _write_csv(path: Path, cases: list[dict[str, Any]]) -> None:
    fields = [
        "sha256",
        "status",
        "duplicate_count",
        "representative",
        "source_size_bytes",
        "candidate_size_bytes",
        "byte_reduction_fraction",
        "palette_colors",
        "largest_render_size",
        "largest_render_rgba_rmse",
        "largest_render_white_rgb_rmse",
        "candidate_classification",
        "error",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for case in cases:
            largest = case.get("largest_render") or {}
            writer.writerow(
                {
                    "sha256": case.get("sha256"),
                    "status": case.get("status"),
                    "duplicate_count": case.get("duplicate_count"),
                    "representative": case.get("representative"),
                    "source_size_bytes": case.get("source_size_bytes"),
                    "candidate_size_bytes": case.get("candidate_size_bytes"),
                    "byte_reduction_fraction": case.get("byte_reduction_fraction"),
                    "palette_colors": ";".join(case.get("palette_colors") or []),
                    "largest_render_size": largest.get("size"),
                    "largest_render_rgba_rmse": largest.get("rgba_rmse"),
                    "largest_render_white_rgb_rmse": largest.get("white_background_rgb_rmse"),
                    "candidate_classification": case.get("candidate_classification"),
                    "error": case.get("error"),
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the experimental compact gradient/mask reconstruction once per unique "
            "flattened-gradient-mask source hash from a scan JSON report."
        )
    )
    parser.add_argument("source_root", type=Path, help="root containing the scan report's relative SVG paths")
    parser.add_argument("scan_json", type=Path, help="scan JSON containing flattened-gradient-mask classifications")
    parser.add_argument("--output-dir", type=Path, default=Path("gradient-mask-batch"))
    parser.add_argument("--sizes", type=render_compare.parse_sizes, default=DEFAULT_SIZES)
    parser.add_argument("--inkscape")
    parser.add_argument("--scour", action="store_true")
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument(
        "--allow-hash-mismatch",
        action="store_true",
        help="run even when a source file no longer matches the scan JSON hash",
    )
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    scan_json = args.scan_json.resolve()
    if not source_root.is_dir():
        parser.error(f"source root does not exist: {args.source_root}")
    if not scan_json.is_file():
        parser.error(f"scan JSON does not exist: {args.scan_json}")

    try:
        groups = load_groups(scan_json)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    if not groups:
        parser.error(f"scan JSON contains no {CLASSIFICATION!r} files")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    reconstruct_script = Path(__file__).with_name("gradient_mask_reconstruct.py")
    cases: list[dict[str, Any]] = []

    for index, group in enumerate(groups, start=1):
        source: Path | None = None
        for relative_path in group["paths"]:
            candidate = _source_path(source_root, relative_path)
            if candidate.is_file():
                source = candidate
                break
        if source is None:
            cases.append(
                {
                    "sha256": group["sha256"],
                    "duplicate_count": group["count"],
                    "paths": group["paths"],
                    "status": "missing",
                    "error": "none of the duplicate paths exists below source_root",
                }
            )
            continue

        actual_hash = _sha256(source)
        if actual_hash != group["sha256"] and not args.allow_hash_mismatch:
            cases.append(
                {
                    "sha256": group["sha256"],
                    "actual_sha256": actual_hash,
                    "duplicate_count": group["count"],
                    "paths": group["paths"],
                    "representative": str(source),
                    "status": "hash-mismatch",
                    "error": "source bytes do not match scan JSON; rerun scan or use --allow-hash-mismatch",
                }
            )
            continue

        case_dir = args.output_dir / f"{index:02d}-{group['sha256'][:12]}-{source.stem}"
        command = [
            sys.executable,
            str(reconstruct_script),
            str(source),
            "--output-dir",
            str(case_dir),
            "--sizes",
            ",".join(str(value) for value in args.sizes),
        ]
        if args.inkscape:
            command.extend(["--inkscape", args.inkscape])
        if args.scour:
            command.append("--scour")
        if args.no_render:
            command.append("--no-render")

        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        manifest_path = case_dir / "manifest.json"
        if completed.returncode != 0 or not manifest_path.is_file():
            stderr = completed.stderr.strip()
            stdout = completed.stdout.strip()
            cases.append(
                {
                    "sha256": group["sha256"],
                    "duplicate_count": group["count"],
                    "paths": group["paths"],
                    "representative": str(source),
                    "status": "rejected",
                    "error": stderr or stdout or f"reconstruction exited {completed.returncode}",
                }
            )
            continue

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        case = _case_summary(group, manifest)
        case["representative"] = str(source)
        case["actual_sha256"] = actual_hash
        case["case_manifest"] = str(manifest_path)
        cases.append(case)

    ok_cases = [case for case in cases if case.get("status") == "ok"]
    payload = {
        "schema_version": 1,
        "experiment": "gradient-mask-family-batch",
        "classification": CLASSIFICATION,
        "source_root": str(source_root),
        "scan_json": str(scan_json),
        "unique_source_groups": len(groups),
        "semantic_paths": sum(group["count"] for group in groups),
        "successful_groups": len(ok_cases),
        "rejected_groups": sum(case.get("status") == "rejected" for case in cases),
        "missing_groups": sum(case.get("status") == "missing" for case in cases),
        "hash_mismatch_groups": sum(case.get("status") == "hash-mismatch" for case in cases),
        "cases": cases,
    }
    report_path = args.output_dir / "batch-report.json"
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_csv(args.output_dir / "batch-report.csv", cases)
    print(json.dumps(payload, indent=2))
    return 0 if len(ok_cases) == len(groups) else 1


if __name__ == "__main__":
    raise SystemExit(main())
