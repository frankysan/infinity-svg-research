from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import gradient_mask_model
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
        "model": reconstruction.get("model", "three-gradient"),
        "gradient_count": reconstruction.get("gradient_count"),
        "gray_shadow_mode": (reconstruction.get("gray_shadow") or {}).get("mode"),
        "candidate_classification": candidate_scan.get("classification"),
        "candidate_advisories": candidate_scan.get("advisories") or [],
        "candidate_signals": candidate_scan.get("signals") or [],
        "largest_render": largest,
        "render_summary": manifest.get("render_summary"),
        "case_manifest": str(Path(manifest.get("candidate", "")).parent / "manifest.json"),
    }


def _run_reconstruction_module(
    *,
    module: str,
    source: Path,
    output_dir: Path,
    sizes: tuple[int, ...],
    scour: bool,
    extra_args: tuple[str, ...] = (),
) -> tuple[dict[str, Any] | None, str | None]:
    command = [
        sys.executable,
        "-m",
        module,
        str(source),
        "--output-dir",
        str(output_dir),
        "--sizes",
        ",".join(str(value) for value in sizes),
        "--no-render",
        *extra_args,
    ]
    if scour:
        command.append("--scour")
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    manifest_path = output_dir / "manifest.json"
    if completed.returncode != 0 or not manifest_path.is_file():
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        return None, stderr or stdout or f"reconstruction exited {completed.returncode}"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"could not read reconstruction manifest: {exc}"
    if not isinstance(manifest, dict):
        return None, "reconstruction manifest is not a JSON object"
    return manifest, None


def _shell_run_payload(run: render_compare.ShellBatchRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "inkscape_version": run.inkscape_version,
        "renderer_processes": run.renderer_processes,
        "document_opens": run.document_opens,
        "exports": run.exports,
        "render_seconds": run.render_seconds,
        "batches": [asdict(batch) for batch in run.batches],
    }


def _update_render_manifest(
    manifest_path: Path,
    render_dir: Path,
    sizes: tuple[int, ...],
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metrics, compare_seconds = render_compare.compare_pair_outputs(render_dir, sizes)
    manifest["render_summary"] = gradient_mask_model._metric_summary(metrics)
    manifest["renders"] = [asdict(metric) for metric in metrics]
    manifest["batch_render"] = {
        "mode": "inkscape-shell-batch",
        "compare_seconds": compare_seconds,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def _write_csv(path: Path, cases: list[dict[str, Any]]) -> None:
    fields = [
        "sha256",
        "status",
        "duplicate_count",
        "representative",
        "source_size_bytes",
        "candidate_size_bytes",
        "byte_reduction_fraction",
        "model",
        "gray_shadow_mode",
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
                    "model": case.get("model"),
                    "gray_shadow_mode": case.get("gray_shadow_mode"),
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
    parser.add_argument(
        "source_root",
        type=Path,
        help="root containing the scan report's relative SVG paths",
    )
    parser.add_argument(
        "scan_json",
        type=Path,
        help="scan JSON containing flattened-gradient-mask classifications",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("gradient-mask-batch"))
    parser.add_argument("--sizes", type=render_compare.parse_sizes, default=DEFAULT_SIZES)
    parser.add_argument("--inkscape")
    parser.add_argument("--scour", action="store_true")
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument(
        "--model",
        choices=("three-gradient", "decomposed"),
        default="three-gradient",
        help="reconstruction model; default preserves the v8.9.4 three-gradient baseline",
    )
    parser.add_argument(
        "--fit-gray-shadow",
        action="store_true",
        help="with --model decomposed, fit strong gray-mask crescents from source renders",
    )
    parser.add_argument(
        "--fit-size",
        type=int,
        default=gradient_mask_model.DEFAULT_FIT_SIZE,
        help="render size used for decomposed gray-shadow fitting",
    )
    parser.add_argument(
        "--shell-restart-every",
        type=int,
        default=0,
        help="restart the shared Inkscape shell after N cases; 0 keeps one shell per phase",
    )
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
    if scan_json.suffix.lower() == ".csv":
        parser.error(f"scan report must be scanner JSON, not CSV: {scan_json}")

    try:
        groups = load_groups(scan_json)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    if not groups:
        parser.error(f"scan JSON contains no {CLASSIFICATION!r} files")
    if args.fit_gray_shadow and args.model != "decomposed":
        parser.error("--fit-gray-shadow requires --model decomposed")
    if args.fit_gray_shadow and args.no_render:
        parser.error("--fit-gray-shadow requires rendering; remove --no-render")
    if args.fit_size <= 0:
        parser.error("--fit-size must be positive")
    if args.shell_restart_every < 0:
        parser.error("--shell-restart-every must be >= 0")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    reconstruct_module = (
        "infinity_svg_research.gradient_mask_model"
        if args.model == "decomposed"
        else "infinity_svg_research.gradient_mask_reconstruct"
    )

    case_results: dict[int, dict[str, Any]] = {}
    ready_cases: list[dict[str, Any]] = []
    fit_cases: list[dict[str, Any]] = []

    for index, group in enumerate(groups, start=1):
        source: Path | None = None
        for relative_path in group["paths"]:
            candidate = _source_path(source_root, relative_path)
            if candidate.is_file():
                source = candidate
                break
        if source is None:
            case_results[index] = {
                "sha256": group["sha256"],
                "duplicate_count": group["count"],
                "paths": group["paths"],
                "status": "missing",
                "error": "none of the duplicate paths exists below source_root",
            }
            continue

        actual_hash = _sha256(source)
        if actual_hash != group["sha256"] and not args.allow_hash_mismatch:
            case_results[index] = {
                "sha256": group["sha256"],
                "actual_sha256": actual_hash,
                "duplicate_count": group["count"],
                "paths": group["paths"],
                "representative": str(source),
                "status": "hash-mismatch",
                "error": (
                    "source bytes do not match scan JSON; rerun scan or use "
                    "--allow-hash-mismatch"
                ),
            }
            continue

        case_dir = args.output_dir / f"{index:02d}-{group['sha256'][:12]}-{source.stem}"
        common = {
            "index": index,
            "group": group,
            "source": source,
            "actual_hash": actual_hash,
            "case_dir": case_dir,
        }

        if args.fit_gray_shadow:
            prep_dir = case_dir / "gray-shadow-fit" / "prep"
            prep_manifest, error = _run_reconstruction_module(
                module=reconstruct_module,
                source=source,
                output_dir=prep_dir,
                sizes=args.sizes,
                scour=False,
                extra_args=("--gray-shadow", "none"),
            )
            if error or prep_manifest is None:
                case_results[index] = {
                    "sha256": group["sha256"],
                    "duplicate_count": group["count"],
                    "paths": group["paths"],
                    "representative": str(source),
                    "status": "rejected",
                    "error": error or "gray-shadow fit preparation failed",
                }
                continue
            fit_cases.append({**common, "prep_manifest": prep_manifest, "prep_dir": prep_dir})
            continue

        manifest, error = _run_reconstruction_module(
            module=reconstruct_module,
            source=source,
            output_dir=case_dir,
            sizes=args.sizes,
            scour=args.scour,
        )
        if error or manifest is None:
            case_results[index] = {
                "sha256": group["sha256"],
                "duplicate_count": group["count"],
                "paths": group["paths"],
                "representative": str(source),
                "status": "rejected",
                "error": error or "reconstruction failed",
            }
            continue
        ready_cases.append({**common, "manifest": manifest})

    renderer: str | None = None
    fit_render_run: render_compare.ShellBatchRun | None = None
    validation_render_run: render_compare.ShellBatchRun | None = None

    if fit_cases:
        try:
            renderer = render_compare.find_inkscape(args.inkscape)
            fit_jobs = [
                render_compare.ShellRenderJob(
                    original=case["source"],
                    candidate=Path(case["prep_manifest"]["candidate"]),
                    output_dir=case["case_dir"] / "gray-shadow-fit" / "renders",
                )
                for case in fit_cases
            ]
            fit_render_run = render_compare.render_svg_pairs_shell_batch(
                fit_jobs,
                (args.fit_size,),
                inkscape=renderer,
                restart_every=args.shell_restart_every,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            parser.error(f"gray-shadow fit render failed: {exc}")

        for case in fit_cases:
            fit_dir = case["case_dir"] / "gray-shadow-fit"
            render_dir = fit_dir / "renders"
            prep_manifest = case["prep_manifest"]
            gray = prep_manifest.get("reconstruction", {}).get("gray_geometry") or {}
            try:
                source_tree = gradient_mask_model.legacy._parse_svg(case["source"])
                fit_report = gradient_mask_model.fit_gray_shadow_from_renders(
                    render_dir / f"original-{args.fit_size}.png",
                    render_dir / f"candidate-{args.fit_size}.png",
                    view_box=gradient_mask_model._view_box(source_tree.getroot()),
                    gray_geometry=(float(gray["cx"]), float(gray["cy"]), float(gray["r"])),
                )
            except (KeyError, TypeError, ValueError, gradient_mask_model.ModelError) as exc:
                case_results[case["index"]] = {
                    "sha256": case["group"]["sha256"],
                    "duplicate_count": case["group"]["count"],
                    "paths": case["group"]["paths"],
                    "representative": str(case["source"]),
                    "status": "rejected",
                    "error": f"gray-shadow fit failed: {exc}",
                }
                continue

            fit_report_path = fit_dir / "fit-report.json"
            fit_report_path.write_text(json.dumps(fit_report, indent=2) + "\n", encoding="utf-8")
            manifest, error = _run_reconstruction_module(
                module=reconstruct_module,
                source=case["source"],
                output_dir=case["case_dir"],
                sizes=args.sizes,
                scour=args.scour,
                extra_args=("--gray-shadow-fit-json", str(fit_report_path)),
            )
            if error or manifest is None:
                case_results[case["index"]] = {
                    "sha256": case["group"]["sha256"],
                    "duplicate_count": case["group"]["count"],
                    "paths": case["group"]["paths"],
                    "representative": str(case["source"]),
                    "status": "rejected",
                    "error": error or "fitted reconstruction failed",
                }
                continue
            ready_cases.append({**case, "manifest": manifest})

    if ready_cases and not args.no_render:
        if renderer is None:
            try:
                renderer = render_compare.find_inkscape(args.inkscape)
            except RuntimeError as exc:
                parser.error(str(exc))
        try:
            validation_jobs = [
                render_compare.ShellRenderJob(
                    original=case["source"],
                    candidate=Path(case["manifest"]["candidate"]),
                    output_dir=case["case_dir"] / "render-compare",
                )
                for case in ready_cases
            ]
            validation_render_run = render_compare.render_svg_pairs_shell_batch(
                validation_jobs,
                args.sizes,
                inkscape=renderer,
                restart_every=args.shell_restart_every,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            parser.error(f"validation render failed: {exc}")

        for case in ready_cases:
            manifest_path = case["case_dir"] / "manifest.json"
            case["manifest"] = _update_render_manifest(
                manifest_path,
                case["case_dir"] / "render-compare",
                args.sizes,
            )

    for case in ready_cases:
        index = case["index"]
        if index in case_results:
            continue
        manifest_path = case["case_dir"] / "manifest.json"
        manifest = case["manifest"]
        summary = _case_summary(case["group"], manifest)
        summary["representative"] = str(case["source"])
        summary["actual_sha256"] = case["actual_hash"]
        summary["case_manifest"] = str(manifest_path)
        case_results[index] = summary

    cases = [case_results[index] for index in range(1, len(groups) + 1)]
    ok_cases = [case for case in cases if case.get("status") == "ok"]
    renderer_processes = (
        (fit_render_run.renderer_processes if fit_render_run is not None else 0)
        + (validation_render_run.renderer_processes if validation_render_run is not None else 0)
    )
    payload = {
        "schema_version": 2,
        "experiment": "gradient-mask-family-batch",
        "classification": CLASSIFICATION,
        "model": args.model,
        "fit_gray_shadow": args.fit_gray_shadow,
        "source_root": str(source_root),
        "scan_json": str(scan_json),
        "unique_source_groups": len(groups),
        "semantic_paths": sum(group["count"] for group in groups),
        "successful_groups": len(ok_cases),
        "rejected_groups": sum(case.get("status") == "rejected" for case in cases),
        "missing_groups": sum(case.get("status") == "missing" for case in cases),
        "hash_mismatch_groups": sum(case.get("status") == "hash-mismatch" for case in cases),
        "renderer": {
            "mode": "inkscape-shell-batch" if renderer_processes else "not-used",
            "total_processes": renderer_processes,
            "fit_phase": _shell_run_payload(fit_render_run),
            "validation_phase": _shell_run_payload(validation_render_run),
        },
        "cases": cases,
    }
    report_path = args.output_dir / "batch-report.json"
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_csv(args.output_dir / "batch-report.csv", cases)
    print(json.dumps(payload, indent=2))
    return 0 if len(ok_cases) == len(groups) else 1


if __name__ == "__main__":
    raise SystemExit(main())
