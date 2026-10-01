from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .render_compare import (
    RendererMode,
    ShellRenderJob,
    compare_pair_outputs,
    parse_sizes,
    render_svg_pairs_shell_batch,
    validate_svg_pair,
)
from .transforms import apply_exact_transforms, result_dict, write_tree



@dataclass(frozen=True)
class ExpandedSource:
    path: Path
    output_key: Path
    input_path: Path
    input_kind: str


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _iter_svg_files(directory: Path, *, excluded_root: Path | None) -> list[Path]:
    files: list[Path] = []
    for path in directory.rglob("*"):
        if not path.is_file() or path.suffix.lower() != ".svg":
            continue
        resolved = path.resolve()
        if excluded_root is not None and _is_relative_to(resolved, excluded_root):
            continue
        files.append(resolved)
    return sorted(files, key=lambda item: item.relative_to(directory).as_posix().casefold())


def expand_sources(inputs: list[Path], *, output_root: Path) -> list[ExpandedSource]:
    """Expand positional file/directory inputs into deterministic SVG cases.

    Directory inputs are searched recursively. Their relative directory structure is
    preserved below the output root, e.g. ``units/foo.svg`` becomes
    ``<output>/units/foo/foo.candidate.svg``. Duplicate source paths are processed once.
    If distinct inputs would map to the same output directory, a short deterministic
    path hash is appended to avoid collisions.
    """
    expanded: list[ExpandedSource] = []
    seen_sources: set[Path] = set()

    for raw_input in inputs:
        input_path = raw_input.resolve()
        if not input_path.exists():
            raise FileNotFoundError(input_path)

        if input_path.is_file():
            if input_path.suffix.lower() != ".svg":
                raise ValueError(f"Input file is not an SVG: {input_path}")
            candidates = [(input_path, Path(input_path.stem), "file")]
        elif input_path.is_dir():
            candidates = [
                (source, source.relative_to(input_path).with_suffix(""), "directory")
                for source in _iter_svg_files(input_path, excluded_root=output_root)
            ]
        else:
            raise ValueError(f"Input is neither a regular file nor directory: {input_path}")

        for source, output_key, input_kind in candidates:
            source = source.resolve()
            if source in seen_sources:
                continue
            seen_sources.add(source)
            expanded.append(
                ExpandedSource(
                    path=source,
                    output_key=output_key,
                    input_path=input_path,
                    input_kind=input_kind,
                )
            )

    if not expanded:
        raise ValueError("No SVG files found in the supplied inputs")

    # Protect against output collisions when several roots/files contain identical
    # relative names. Keep the ordinary path untouched unless a collision exists.
    by_key: dict[str, list[int]] = {}
    for index, item in enumerate(expanded):
        key = item.output_key.as_posix().casefold()
        by_key.setdefault(key, []).append(index)

    for indexes in by_key.values():
        if len(indexes) <= 1:
            continue
        for index in indexes:
            item = expanded[index]
            suffix = hashlib.sha256(str(item.path).encode("utf-8")).hexdigest()[:8]
            leaf = item.output_key.name + "__" + suffix
            expanded[index] = ExpandedSource(
                path=item.path,
                output_key=item.output_key.parent / leaf,
                input_path=item.input_path,
                input_kind=item.input_kind,
            )

    return expanded


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inkscape_version(executable: str) -> tuple[str | None, float]:
    started = time.perf_counter()
    result = subprocess.run(
        [executable, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    elapsed = time.perf_counter() - started
    version = result.stdout.strip() or result.stderr.strip() or None
    return version, elapsed


def prepare_case(
    source: Path,
    output_root: Path,
    *,
    output_key: Path | None = None,
    discovered_from: Path | None = None,
    input_kind: str | None = None,
) -> tuple[dict[str, object], Path | None, Path | None]:
    case_started = time.perf_counter()
    source = source.resolve()
    if not source.exists():
        raise FileNotFoundError(source)

    case_dir = output_root / (output_key or Path(source.stem))
    candidate = case_dir / f"{source.stem}.candidate.svg"
    render_dir = case_dir / "renders"

    transform_started = time.perf_counter()
    tree, transform_results = apply_exact_transforms(source)
    transform_seconds = time.perf_counter() - transform_started
    changed = any(result.changed for result in transform_results)

    record: dict[str, object] = {
        "source": {
            "path": str(source),
            "sha256": sha256(source),
            "bytes": source.stat().st_size,
            "discovered_from": str(discovered_from) if discovered_from is not None else None,
            "input_kind": input_kind,
            "output_key": (output_key or Path(source.stem)).as_posix(),
        },
        "transforms": [result_dict(result) for result in transform_results],
        "changed": changed,
    }

    if not changed:
        record["candidate"] = None
        record["validation"] = None
        record["timing_seconds"] = {
            "transform": transform_seconds,
            "compare": 0.0,
            "case_local_total": time.perf_counter() - case_started,
        }
        record["verdict"] = "no-change"
        return record, None, None

    write_tree(tree, candidate)
    record["candidate"] = {
        "path": str(candidate),
        "sha256": sha256(candidate),
        "bytes": candidate.stat().st_size,
        "byte_delta": candidate.stat().st_size - source.stat().st_size,
        "byte_reduction_fraction": 1.0 - candidate.stat().st_size / source.stat().st_size,
    }
    record["timing_seconds"] = {
        "transform": transform_seconds,
        "compare": None,
        "case_local_total": None,
    }
    return record, candidate, render_dir


def _finish_shell_case(
    record: dict[str, object],
    render_dir: Path,
    sizes: tuple[int, ...],
    *,
    batch_index: int,
) -> None:
    compare_started = time.perf_counter()
    metrics, compare_seconds = compare_pair_outputs(render_dir, sizes)
    case_local_total = time.perf_counter() - compare_started
    exact = all(metric.exact for metric in metrics)
    record["validation"] = {
        "sizes": list(sizes),
        "exact": exact,
        "renderer": {
            "mode": "inkscape-shell",
            "shared_process": True,
            "batch_index": batch_index,
            "document_opens": 2,
            "exports": 2 * len(sizes),
        },
        "timing_seconds": {
            "render": None,
            "render_scope": "run-batch",
            "compare": compare_seconds,
            "case_local_total": case_local_total,
        },
        "renders": [asdict(metric) for metric in metrics],
    }
    timing = record["timing_seconds"]
    timing["compare"] = compare_seconds  # type: ignore[index]
    timing["case_local_total"] = timing["transform"] + compare_seconds  # type: ignore[index,operator]
    record["verdict"] = "exact-render-identical" if exact else "reject-render-changed"


def _finish_one_shot_case(
    record: dict[str, object],
    candidate: Path,
    render_dir: Path,
    sizes: tuple[int, ...],
    *,
    inkscape: str,
) -> tuple[int, int]:
    source = Path(str(record["source"]["path"]))  # type: ignore[index]
    run = validate_svg_pair(
        source,
        candidate,
        render_dir,
        sizes=sizes,
        inkscape=inkscape,
        renderer_mode="inkscape-one-shot",
    )
    exact = all(metric.exact for metric in run.metrics)
    record["validation"] = {
        "sizes": list(sizes),
        "exact": exact,
        "renderer": {
            "mode": run.renderer_mode,
            "shared_process": False,
            "processes": run.renderer_processes,
            "document_opens": run.document_opens,
            "exports": run.exports,
        },
        "timing_seconds": {
            "render": run.render_seconds,
            "compare": run.compare_seconds,
            "total": run.total_seconds,
        },
        "renders": [asdict(metric) for metric in run.metrics],
    }
    timing = record["timing_seconds"]
    timing["compare"] = run.compare_seconds  # type: ignore[index]
    timing["case_local_total"] = timing["transform"] + run.total_seconds  # type: ignore[index,operator]
    record["verdict"] = "exact-render-identical" if exact else "reject-render-changed"
    return run.renderer_processes, run.exports


def _batch_index_for_case(case_index: int, restart_every: int, changed_count: int) -> int:
    if restart_every <= 0:
        return 0
    return case_index // restart_every


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate exact SVG optimization candidates and validate them by rendering."
    )
    parser.add_argument(
        "sources",
        nargs="+",
        type=Path,
        help="SVG files and/or directories. Directories are searched recursively for *.svg.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("svg-research-run"))
    parser.add_argument("--sizes", type=parse_sizes, default=(64, 128, 256, 1024))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--inkscape")
    parser.add_argument(
        "--renderer",
        choices=("inkscape-shell", "inkscape-one-shot"),
        default="inkscape-shell",
        help="Use one shared Inkscape shell for the run (default) or one process per export.",
    )
    parser.add_argument(
        "--shell-restart-every",
        type=int,
        default=0,
        metavar="N",
        help="Restart the shared shell after N changed cases; 0 keeps one shell for the whole run.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print no-change cases as well as changed/rejected cases.",
    )
    parser.add_argument(
        "--probe-version",
        action="store_true",
        help="For one-shot mode, run a separate `inkscape --version` probe. Shell mode gets the version from the shared shell without another process.",
    )
    args = parser.parse_args()

    if args.shell_restart_every < 0:
        parser.error("--shell-restart-every must be >= 0")

    executable = args.inkscape or shutil.which("inkscape")
    if executable is None:
        raise RuntimeError("Inkscape was not found on PATH")

    output_root = args.output_dir.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = args.manifest.resolve() if args.manifest else output_root / "manifest.json"

    run_started = time.perf_counter()
    expanded_sources = expand_sources(args.sources, output_root=output_root)
    print(f"discovered {len(expanded_sources)} SVG file(s)")

    records: list[dict[str, object]] = []
    changed_jobs: list[tuple[int, Path, Path, Path]] = []
    for item in expanded_sources:
        record, candidate, render_dir = prepare_case(
            item.path,
            output_root,
            output_key=item.output_key,
            discovered_from=item.input_path,
            input_kind=item.input_kind,
        )
        record_index = len(records)
        records.append(record)
        if candidate is not None and render_dir is not None:
            source_path = Path(str(record["source"]["path"]))  # type: ignore[index]
            changed_jobs.append((record_index, source_path, candidate, render_dir))

    version: str | None = None
    version_source = "not-probed"
    version_probe_processes = 0
    version_probe_seconds = 0.0
    total_render_processes = 0
    total_exports = 0
    run_render_seconds = 0.0
    renderer_batches: list[dict[str, object]] = []

    if args.renderer == "inkscape-shell" and changed_jobs:
        shell_run = render_svg_pairs_shell_batch(
            [
                ShellRenderJob(original=source, candidate=candidate, output_dir=render_dir)
                for _, source, candidate, render_dir in changed_jobs
            ],
            args.sizes,
            inkscape=executable,
            restart_every=args.shell_restart_every,
        )
        version = shell_run.inkscape_version
        version_source = "shared-shell-action" if version else "shared-shell-unavailable"
        total_render_processes = shell_run.renderer_processes
        total_exports = shell_run.exports
        run_render_seconds = shell_run.render_seconds
        renderer_batches = [asdict(batch) for batch in shell_run.batches]

        for changed_index, (record_index, _, _, render_dir) in enumerate(changed_jobs):
            _finish_shell_case(
                records[record_index],
                render_dir,
                args.sizes,
                batch_index=_batch_index_for_case(
                    changed_index, args.shell_restart_every, len(changed_jobs)
                ),
            )
    elif args.renderer == "inkscape-one-shot":
        if args.probe_version:
            version, version_probe_seconds = inkscape_version(executable)
            version_source = "separate-version-process"
            version_probe_processes = 1
        for record_index, _, candidate, render_dir in changed_jobs:
            processes, exports = _finish_one_shot_case(
                records[record_index],
                candidate,
                render_dir,
                args.sizes,
                inkscape=executable,
            )
            total_render_processes += processes
            total_exports += exports
            validation = records[record_index]["validation"]
            run_render_seconds += validation["timing_seconds"]["render"]  # type: ignore[index,operator]
    elif args.renderer == "inkscape-shell" and args.probe_version:
        # No changed cases means there was no shared shell from which to query the version.
        version, version_probe_seconds = inkscape_version(executable)
        version_source = "separate-version-process"
        version_probe_processes = 1

    failed = False
    rejected_cases = 0
    for record in records:
        verdict = record["verdict"]
        source_path = Path(str(record["source"]["path"]))  # type: ignore[index]
        output_key = str(record["source"].get("output_key") or source_path.name)  # type: ignore[index]
        candidate = record.get("candidate")
        if candidate:
            reduction = candidate["byte_reduction_fraction"]  # type: ignore[index]
            print(f"{output_key}: {verdict}; size reduction={reduction:.1%}")
        elif args.verbose:
            print(f"{output_key}: {verdict}")
        if verdict == "reject-render-changed":
            failed = True
            rejected_cases += 1

    print(
        f"summary: {len(records)} case(s); {len(changed_jobs)} changed; "
        f"{rejected_cases} rejected; {len(records) - len(changed_jobs)} unchanged"
    )

    payload = {
        "schema_version": 4,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "inkscape": version,
            "inkscape_version_source": version_source,
            "inkscape_executable": str(executable),
            "renderer_mode": args.renderer,
        },
        "validation_policy": {
            "kind": "exact",
            "rule": "all rendered RGBA pixels must be identical at every configured size",
            "sizes": list(args.sizes),
        },
        "run": {
            "input_arguments": [str(path.resolve()) for path in args.sources],
            "cases": len(records),
            "changed_cases": len(changed_jobs),
            "renderer": {
                "mode": args.renderer,
                "processes": total_render_processes,
                "shell_restart_every": args.shell_restart_every if args.renderer == "inkscape-shell" else None,
                "shell_restarts": max(0, total_render_processes - 1) if args.renderer == "inkscape-shell" else None,
                "document_opens": 2 * len(changed_jobs) if args.renderer == "inkscape-shell" else total_exports,
                "exports": total_exports,
                "render_seconds": run_render_seconds,
                "batches": renderer_batches,
            },
            "version_probe_processes": version_probe_processes,
            "version_probe_seconds": version_probe_seconds,
            "total_seconds": time.perf_counter() - run_started,
        },
        "cases": records,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"manifest: {manifest_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
