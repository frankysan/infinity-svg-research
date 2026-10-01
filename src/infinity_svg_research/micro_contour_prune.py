from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from lxml import etree
from scour import scour as scour_module

from . import render_compare
from . import scan

DEFAULT_SIZES = (64, 128, 256, 512, 1024, 1200)


def _parse_svg(path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        recover=False,
        huge_tree=True,
        remove_blank_text=False,
    )
    return etree.parse(str(path), parser)


def _subpath_slices(path_data: str) -> list[str]:
    """Split path data at explicit moveto commands without rewriting coordinates."""
    starts = [
        match.start()
        for match in scan.PATH_TOKEN_RE.finditer(path_data)
        if match.group(0) in {"M", "m"}
    ]
    if not starts:
        return []
    return [
        path_data[start : (starts[index + 1] if index + 1 < len(starts) else len(path_data))].strip()
        for index, start in enumerate(starts)
    ]


def _format_number(value: float) -> str:
    if abs(value) < 5e-15:
        value = 0.0
    return format(value, ".15g")


def _absolutize_piece(
    piece: str, current_before: tuple[float, float]
) -> tuple[str, tuple[float, float], tuple[float, float]]:
    """Return an explicit absolute-command form for one moveto-delimited piece.

    Every repeated parameter set is emitted with an explicit command. This avoids the
    SVG moveto special case where extra pairs after ``m`` are relative lineto segments,
    and makes each retained subpath independent of any predecessor that may be pruned.
    """
    tokens = scan.PATH_TOKEN_RE.findall(piece)
    if not tokens or tokens[0] not in {"M", "m"}:
        raise ValueError("subpath piece does not start with moveto")

    out: list[str] = []
    i = 0
    command: str | None = None
    x, y = current_before
    start_x = start_y = 0.0
    have_moveto = False

    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            command = token
            i += 1
            if command.upper() == "Z":
                if not have_moveto:
                    raise ValueError("closepath occurs before moveto")
                out.append("Z")
                x, y = start_x, start_y
                command = None
                continue
        if command is None:
            raise ValueError("path data contains numbers without a command")

        upper = command.upper()
        count = scan.PATH_PARAMS.get(upper)
        if count is None or count == 0:
            raise ValueError(f"unsupported path command: {command}")
        if i + count > len(tokens) or any(value.isalpha() for value in tokens[i : i + count]):
            raise ValueError(f"incomplete path command: {command}")
        values = [float(value) for value in tokens[i : i + count]]
        i += count
        relative = command.islower()
        base_x, base_y = x, y

        if upper == "M":
            nx = values[0] + (base_x if relative else 0.0)
            ny = values[1] + (base_y if relative else 0.0)
            if not have_moveto:
                out.append(f"M{_format_number(nx)} {_format_number(ny)}")
                start_x, start_y = nx, ny
                have_moveto = True
            else:
                out.append(f"L{_format_number(nx)} {_format_number(ny)}")
            x, y = nx, ny
            # Additional parameter pairs after moveto are implicit lineto segments.
            command = "l" if relative else "L"
            continue

        if not have_moveto:
            raise ValueError("path drawing command occurs before moveto")

        if upper == "L":
            nx = values[0] + (base_x if relative else 0.0)
            ny = values[1] + (base_y if relative else 0.0)
            out.append(f"L{_format_number(nx)} {_format_number(ny)}")
            x, y = nx, ny
        elif upper == "H":
            nx = values[0] + (base_x if relative else 0.0)
            out.append(f"H{_format_number(nx)}")
            x = nx
        elif upper == "V":
            ny = values[0] + (base_y if relative else 0.0)
            out.append(f"V{_format_number(ny)}")
            y = ny
        elif upper == "C":
            x1 = values[0] + (base_x if relative else 0.0)
            y1 = values[1] + (base_y if relative else 0.0)
            x2 = values[2] + (base_x if relative else 0.0)
            y2 = values[3] + (base_y if relative else 0.0)
            nx = values[4] + (base_x if relative else 0.0)
            ny = values[5] + (base_y if relative else 0.0)
            out.append(
                "C"
                f"{_format_number(x1)} {_format_number(y1)} "
                f"{_format_number(x2)} {_format_number(y2)} "
                f"{_format_number(nx)} {_format_number(ny)}"
            )
            x, y = nx, ny
        elif upper in {"S", "Q"}:
            x1 = values[0] + (base_x if relative else 0.0)
            y1 = values[1] + (base_y if relative else 0.0)
            nx = values[2] + (base_x if relative else 0.0)
            ny = values[3] + (base_y if relative else 0.0)
            out.append(
                f"{upper}{_format_number(x1)} {_format_number(y1)} "
                f"{_format_number(nx)} {_format_number(ny)}"
            )
            x, y = nx, ny
        elif upper == "T":
            nx = values[0] + (base_x if relative else 0.0)
            ny = values[1] + (base_y if relative else 0.0)
            out.append(f"T{_format_number(nx)} {_format_number(ny)}")
            x, y = nx, ny
        elif upper == "A":
            nx = values[5] + (base_x if relative else 0.0)
            ny = values[6] + (base_y if relative else 0.0)
            out.append(
                "A"
                f"{_format_number(values[0])} {_format_number(values[1])} "
                f"{_format_number(values[2])} {_format_number(values[3])} "
                f"{_format_number(values[4])} {_format_number(nx)} {_format_number(ny)}"
            )
            x, y = nx, ny
        else:
            raise ValueError(f"unsupported path command: {command}")

    if not have_moveto:
        raise ValueError("subpath piece is missing moveto coordinates")
    return " ".join(out), (start_x, start_y), (x, y)

def prune_path_data(path_data: str, *, max_span: float) -> tuple[str, dict[str, Any]]:
    pieces = _subpath_slices(path_data)
    if not pieces:
        return path_data, {
            "subpaths": 0,
            "closed_subpaths": 0,
            "removed_subpaths": 0,
            "removed_path_data_bytes": 0,
            "rebased_relative_movetos": 0,
        }

    try:
        stats, _segments = scan.analyze_path_subpaths(path_data)
        if len(stats) != len(pieces):
            raise ValueError("subpath analysis count does not match explicit moveto pieces")

        absolute_pieces: list[str] = []
        current = (0.0, 0.0)
        for piece in pieces:
            absolute_piece, _absolute_start, current = _absolutize_piece(piece, current)
            absolute_pieces.append(absolute_piece)
    except ValueError:
        return path_data, {
            "subpaths": len(pieces),
            "closed_subpaths": 0,
            "removed_subpaths": 0,
            "removed_path_data_bytes": 0,
            "rebased_relative_movetos": 0,
            "analysis_error": True,
        }

    keep: list[str] = []
    removed = 0
    removed_bytes = 0
    closed_count = 0
    rebased = 0
    for piece, absolute_piece, (span, closed) in zip(
        pieces, absolute_pieces, stats, strict=True
    ):
        if closed:
            closed_count += 1
        if closed and span <= max_span:
            removed += 1
            removed_bytes += len(piece.encode("utf-8"))
            continue

        keep.append(absolute_piece)
        if piece.lstrip().startswith("m"):
            rebased += 1

    if not removed:
        return path_data, {
            "subpaths": len(pieces),
            "closed_subpaths": closed_count,
            "removed_subpaths": 0,
            "removed_path_data_bytes": 0,
            "rebased_relative_movetos": 0,
        }
    return " ".join(keep), {
        "subpaths": len(pieces),
        "closed_subpaths": closed_count,
        "removed_subpaths": removed,
        "removed_path_data_bytes": removed_bytes,
        "rebased_relative_movetos": rebased,
    }

def prune_tree(
    tree: etree._ElementTree, *, max_span: float, mark_changed_paths: bool = False
) -> dict[str, Any]:
    root = tree.getroot()
    paths_seen = 0
    paths_changed = 0
    paths_removed = 0
    rebased_relative = 0
    analysis_errors = 0
    total_subpaths = 0
    closed_subpaths = 0
    removed_subpaths = 0
    removed_path_data_bytes = 0
    changed_path_ids: list[str] = []
    temporary_ids: list[str] = []

    for path in list(root.xpath(".//s:path", namespaces=scan.NS)):
        path_data = path.get("d") or ""
        if not path_data:
            continue
        paths_seen += 1
        candidate, stats = prune_path_data(path_data, max_span=max_span)
        total_subpaths += int(stats["subpaths"])
        closed_subpaths += int(stats["closed_subpaths"])
        removed_subpaths += int(stats["removed_subpaths"])
        removed_path_data_bytes += int(stats["removed_path_data_bytes"])
        rebased_relative += int(stats.get("rebased_relative_movetos", 0))
        analysis_errors += int(bool(stats.get("analysis_error")))
        if candidate == path_data:
            continue
        paths_changed += 1
        if candidate:
            path.set("d", candidate)
            if mark_changed_paths:
                path_id = path.get("id")
                if not path_id:
                    path_id = f"svg-research-prune-{paths_changed}"
                    path.set("id", path_id)
                    temporary_ids.append(path_id)
                changed_path_ids.append(path_id)
        else:
            parent = path.getparent()
            if parent is not None:
                parent.remove(path)
                paths_removed += 1

    return {
        "max_span": max_span,
        "paths_seen": paths_seen,
        "paths_changed": paths_changed,
        "paths_removed": paths_removed,
        "relative_movetos_rebased": rebased_relative,
        "path_analysis_errors": analysis_errors,
        "subpaths_seen": total_subpaths,
        "closed_subpaths_seen": closed_subpaths,
        "removed_subpaths": removed_subpaths,
        "removed_path_data_bytes_estimate": removed_path_data_bytes,
        "changed_path_ids": changed_path_ids,
        "temporary_ids": temporary_ids,
    }


def _remove_temporary_ids(path: Path, ids: list[str]) -> None:
    if not ids:
        return
    tree = _parse_svg(path)
    root = tree.getroot()
    id_set = set(ids)
    for element in root.xpath(".//*[@id]"):
        if element.get("id") in id_set:
            del element.attrib["id"]
    tree.write(str(path), encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _simplify_once(
    source: Path,
    destination: Path,
    *,
    path_ids: list[str],
    temporary_ids: list[str],
    inkscape: str | None,
) -> dict[str, Any]:
    if not path_ids:
        raise RuntimeError("no changed paths are available for simplification")
    executable = render_compare.find_inkscape(inkscape)
    command = [
        executable,
        str(source),
        "--select=" + ",".join(path_ids),
        "--actions=path-simplify",
        "--export-filename=" + str(destination),
        "--export-type=svg",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0 or not destination.is_file():
        detail = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        raise RuntimeError(
            f"Inkscape path-simplify failed with exit {result.returncode}: {detail}"
        )
    _remove_temporary_ids(destination, temporary_ids)
    return {
        "passes": 1,
        "paths_selected": len(path_ids),
        "bytes": destination.stat().st_size,
    }


def _scour_svg(source: Path, destination: Path) -> dict[str, Any]:
    text = source.read_text(encoding="utf-8")
    optimized = scour_module.scourString(text, scour_module.sanitizeOptions())
    destination.write_text(optimized, encoding="utf-8")
    return {
        "bytes_before": source.stat().st_size,
        "bytes_after": destination.stat().st_size,
    }


def _scan_source(path: Path) -> scan.SvgReport:
    return scan.scan_file(
        path,
        path.name,
        confirm_blends=False,
        geometry_tolerance=0.011,
        translation_tolerance=0.021,
        deep_raster=False,
        micro_contour_span_ratio=0.0002,
        small_contour_span_ratio=0.0005,
        subpixel_detail=False,
        subpixel_min_path_data_bytes=20_000,
        subpixel_curve_samples=6,
    )


def _metric_summary(metrics: list[render_compare.RenderMetrics]) -> dict[str, Any]:
    return {
        "sizes": [metric.size for metric in metrics],
        "max_changed_pixel_fraction": max(
            (metric.changed_pixel_fraction for metric in metrics), default=0.0
        ),
        "max_channel_diff": max((metric.max_channel_diff for metric in metrics), default=0),
        "max_rgba_rmse": max((metric.rgba_rmse for metric in metrics), default=0.0),
        "max_white_background_rgb_rmse": max(
            (metric.white_background_rgb_rmse for metric in metrics), default=0.0
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Experimental pruning of tiny closed compound-path contours from "
            "micro-contour-explosion SVGs. Outputs always require review."
        )
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("micro-contour-prune"))
    parser.add_argument(
        "--max-span",
        type=float,
        default=0.1,
        help="remove closed subpaths whose conservative max span is <= this SVG-unit value (default: 0.1)",
    )
    parser.add_argument("--sizes", type=render_compare.parse_sizes, default=DEFAULT_SIZES)
    parser.add_argument("--inkscape")
    parser.add_argument(
        "--simplify-once",
        action="store_true",
        help=(
            "after pruning, apply exactly one Inkscape path-simplify pass to only "
            "the paths changed by pruning"
        ),
    )
    parser.add_argument(
        "--scour",
        action="store_true",
        help="run standard Scour on the final experimental candidate",
    )
    parser.add_argument(
        "--no-render",
        action="store_true",
        help="skip render comparison; --simplify-once still requires Inkscape",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow experimentation on sources not classified as micro-contour-explosion",
    )
    args = parser.parse_args()
    if args.max_span < 0:
        parser.error("--max-span must be non-negative")
    source = args.source.resolve()
    if not source.is_file():
        parser.error(f"source does not exist: {args.source}")

    report = _scan_source(source)
    if report.classification != "micro-contour-explosion" and not args.force:
        parser.error(
            f"source classification is {report.classification!r}, not 'micro-contour-explosion'; use --force for an explicit experiment"
        )

    tree = _parse_svg(source)
    stats = prune_tree(
        tree,
        max_span=args.max_span,
        mark_changed_paths=args.simplify_once,
    )
    changed_path_ids = list(stats.pop("changed_path_ids"))
    temporary_ids = list(stats.pop("temporary_ids"))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    pruned = args.output_dir / f"{source.stem}.prune-{args.max_span:g}.svg"
    tree.write(str(pruned), encoding="UTF-8", xml_declaration=True, pretty_print=False)
    candidate = pruned
    stages: dict[str, Any] = {
        "pruned": {"path": str(pruned), "bytes": pruned.stat().st_size}
    }

    if args.simplify_once:
        simplified = args.output_dir / f"{source.stem}.prune-{args.max_span:g}.simplify-1.svg"
        stages["simplified"] = _simplify_once(
            pruned,
            simplified,
            path_ids=changed_path_ids,
            temporary_ids=temporary_ids,
            inkscape=args.inkscape,
        )
        stages["simplified"]["path"] = str(simplified)
        candidate = simplified

    if args.scour:
        scoured = candidate.with_name(candidate.stem + ".scour.svg")
        stages["scoured"] = _scour_svg(candidate, scoured)
        stages["scoured"]["path"] = str(scoured)
        candidate = scoured

    payload: dict[str, Any] = {
        "schema_version": 2,
        "experiment": "micro-contour-prune",
        "verdict": "experimental-review-required",
        "automatic_acceptance": False,
        "source": str(source),
        "candidate": str(candidate),
        "source_classification": report.classification,
        "source_size_bytes": source.stat().st_size,
        "candidate_size_bytes": candidate.stat().st_size,
        "byte_reduction_fraction": 1.0 - candidate.stat().st_size / source.stat().st_size,
        "transform": stats,
        "simplify_once": args.simplify_once,
        "scour": args.scour,
        "stages": stages,
    }

    if not args.no_render:
        validation = render_compare.validate_svg_pair(
            source,
            candidate,
            args.output_dir / "render-compare",
            sizes=args.sizes,
            inkscape=args.inkscape,
        )
        payload["render_summary"] = _metric_summary(validation.metrics)
        payload["renders"] = [asdict(metric) for metric in validation.metrics]
    manifest = args.output_dir / "manifest.json"
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
