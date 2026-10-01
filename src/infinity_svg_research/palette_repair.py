from __future__ import annotations

import argparse
import json
import math
import platform
import re
import sys
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lxml import etree

from . import scan
from .optimize import ExpandedSource, expand_sources, sha256
from .render_compare import (
    ShellRenderJob,
    compare_pair_outputs,
    find_inkscape,
    parse_sizes,
    render_svg_pairs_shell_batch,
)


DEFAULT_SIZES = (64, 128, 256, 512, 1024, 1600)


def _parse_svg(path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        recover=False,
        huge_tree=True,
        remove_blank_text=False,
    )
    return etree.parse(str(path), parser)


def _has_xml_declaration(path: Path) -> bool:
    return path.read_bytes().lstrip().startswith(b"<?xml")


def _write_like_source(tree: etree._ElementTree, source_format: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tree.write(
        str(destination),
        encoding="UTF-8",
        xml_declaration=_has_xml_declaration(source_format),
        pretty_print=False,
    )


PAINT_DECL_RE = re.compile(r"(?P<prefix>\b(?P<property>fill|stroke)\s*:\s*)(?P<value>[^;}]*)", re.I)


def _rgb_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{value:02x}" for value in rgb)


def _replace_paint_declarations(
    text: str | None, mapping: dict[tuple[int, int, int], tuple[int, int, int]]
) -> tuple[str | None, int]:
    if not text:
        return text, 0
    changed = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal changed
        value = match.group("value").strip()
        color = scan.parse_css_rgb(value)
        target = mapping.get(color) if color is not None else None
        if target is None:
            return match.group(0)
        changed += 1
        return match.group("prefix") + _rgb_hex(target)

    return PAINT_DECL_RE.sub(replace, text), changed

def _scan_for_palette_class(source: Path) -> scan.SvgReport:
    return scan.scan_file(
        source,
        str(source),
        confirm_blends=False,
        geometry_tolerance=0.011,
        translation_tolerance=0.021,
        deep_raster=False,
        micro_contour_span_ratio=0.0002,
        small_contour_span_ratio=0.0005,
        subpixel_detail=True,
        subpixel_min_path_data_bytes=20_000,
        subpixel_curve_samples=6,
    )


def _palette_path_records(
    root: etree._Element,
) -> tuple[
    list[tuple[etree._Element, tuple[int, int, int], int]],
    Counter[tuple[int, int, int]],
    Counter[tuple[int, int, int]],
]:
    class_styles = scan.parse_class_styles(root)
    records: list[tuple[etree._Element, tuple[int, int, int], int]] = []
    path_counts: Counter[tuple[int, int, int]] = Counter()
    path_bytes: Counter[tuple[int, int, int]] = Counter()
    for path in root.xpath(".//s:path", namespaces=scan.NS):
        props = scan.effective_paint_properties(path, class_styles)
        fill = scan.parse_css_rgb(props.get("fill"))
        path_data = path.get("d") or ""
        if fill is None or not path_data:
            continue
        encoded_bytes = len(path_data.encode("utf-8"))
        records.append((path, fill, encoded_bytes))
        path_counts[fill] += 1
        path_bytes[fill] += encoded_bytes
    return records, path_counts, path_bytes


def _farthest_endpoints(
    colors: list[tuple[int, int, int]],
) -> tuple[tuple[int, int, int], tuple[int, int, int], float]:
    distance_sq, start, end = max(
        (
            (sum((left[i] - right[i]) ** 2 for i in range(3)), left, right)
            for index, left in enumerate(colors)
            for right in colors[index + 1 :]
        ),
        key=lambda item: item[0],
    )
    return start, end, math.sqrt(distance_sq)


def _distinct_effective_path_fills(root: etree._Element) -> int:
    class_styles = scan.parse_class_styles(root)
    colors: set[tuple[int, int, int]] = set()
    for path in root.xpath(".//s:path", namespaces=scan.NS):
        props = scan.effective_paint_properties(path, class_styles)
        fill = scan.parse_css_rgb(props.get("fill"))
        if fill is not None and (path.get("d") or ""):
            colors.add(fill)
    return len(colors)


def snap_fragmented_palette(
    tree: etree._ElementTree,
    *,
    axis_distance: float = 8.0,
    endpoint_guard: float = 0.02,
) -> dict[str, Any]:
    root = tree.getroot()
    records, path_counts, path_bytes = _palette_path_records(root)
    colors = list(path_counts)
    if len(colors) < 2:
        return {
            "changed": False,
            "reason": "fewer-than-two-flat-fill-colors",
            "changed_paths": 0,
        }

    start, end, endpoint_distance = _farthest_endpoints(colors)
    mapping: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    axis_colors = 0
    axis_paths = 0
    axis_path_bytes = 0
    intermediate_paths = 0
    intermediate_path_bytes = 0
    off_axis_paths = 0
    for color in colors:
        distance, t = scan.point_segment_distance_and_t(color, start, end)
        if distance > axis_distance:
            off_axis_paths += path_counts[color]
            continue
        axis_colors += 1
        axis_paths += path_counts[color]
        axis_path_bytes += path_bytes[color]
        if endpoint_guard < t < 1.0 - endpoint_guard:
            target = start if t < 0.5 else end
            if target != color:
                mapping[color] = target
                intermediate_paths += path_counts[color]
                intermediate_path_bytes += path_bytes[color]

    # Change declarations rather than individual path nodes. Illustrator frequently
    # stores the traced palette in shared CSS classes, and those classes can also paint
    # polygons/other geometry. Rewriting the declaration keeps every user of the same
    # traced shade coherent while leaving geometry untouched.
    changed_style_declarations = 0
    for style_element in root.xpath(".//s:style", namespaces=scan.NS):
        replaced, count = _replace_paint_declarations(style_element.text, mapping)
        if count:
            style_element.text = replaced
            changed_style_declarations += count

    changed_fill_attribute_declarations = 0
    changed_stroke_attribute_declarations = 0
    changed_inline_declarations = 0
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        fill_attr = element.get("fill")
        fill_color = scan.parse_css_rgb(fill_attr)
        target = mapping.get(fill_color) if fill_color is not None else None
        if target is not None:
            element.set("fill", _rgb_hex(target))
            changed_fill_attribute_declarations += 1

        stroke_attr = element.get("stroke")
        stroke_color = scan.parse_css_rgb(stroke_attr)
        target = mapping.get(stroke_color) if stroke_color is not None else None
        if target is not None:
            element.set("stroke", _rgb_hex(target))
            changed_stroke_attribute_declarations += 1

        style_text = element.get("style")
        replaced, count = _replace_paint_declarations(style_text, mapping)
        if count:
            assert replaced is not None
            element.set("style", replaced)
            changed_inline_declarations += count

    after_records, after_counts, _after_bytes = _palette_path_records(root)
    before_fills = [color for _path, color, _size in records]
    after_fills = [color for _path, color, _size in after_records]
    changed_paths = sum(1 for before, after in zip(before_fills, after_fills) if before != after)

    return {
        "changed": (
            changed_style_declarations
            + changed_fill_attribute_declarations
            + changed_stroke_attribute_declarations
            + changed_inline_declarations
            > 0
        ),
        "axis_distance_threshold": axis_distance,
        "endpoint_guard": endpoint_guard,
        "endpoint_start": list(start),
        "endpoint_end": list(end),
        "endpoint_distance": endpoint_distance,
        "flat_fill_paths": len(records),
        "distinct_flat_fill_colors_before": len(colors),
        "distinct_flat_fill_colors_after": len(after_counts),
        "axis_colors": axis_colors,
        "axis_paths": axis_paths,
        "axis_path_data_bytes": axis_path_bytes,
        "off_axis_paths": off_axis_paths,
        "mapped_source_colors": len(mapping),
        "changed_paths": changed_paths,
        "changed_source_colors": len(mapping),
        "changed_path_data_bytes": intermediate_path_bytes,
        "intermediate_paths": intermediate_paths,
        "changed_style_declarations": changed_style_declarations,
        "changed_fill_attribute_declarations": changed_fill_attribute_declarations,
        "changed_stroke_attribute_declarations": changed_stroke_attribute_declarations,
        "changed_inline_declarations": changed_inline_declarations,
        "changed_declarations_total": (
            changed_style_declarations
            + changed_fill_attribute_declarations
            + changed_stroke_attribute_declarations
            + changed_inline_declarations
        ),
        "source_color_path_counts": {
            _rgb_hex(color): count for color, count in sorted(path_counts.items())
        },
        "source_color_path_data_bytes": {
            _rgb_hex(color): size for color, size in sorted(path_bytes.items())
        },
    }

def _case_dir(output_root: Path, expanded: ExpandedSource) -> Path:
    return output_root / expanded.output_key


def prepare_case(
    expanded: ExpandedSource,
    output_root: Path,
    *,
    include_advisory: bool,
    axis_distance: float,
    endpoint_guard: float,
) -> tuple[dict[str, Any], Path | None, Path | None]:
    started = time.perf_counter()
    source = expanded.path
    report = _scan_for_palette_class(source)
    selected_by = None
    if report.classification == "palette-fragmented-trace":
        selected_by = "classification"
    elif include_advisory and "palette-fragmentation" in report.advisories:
        selected_by = "advisory"

    record: dict[str, Any] = {
        "source": {
            "path": str(source),
            "sha256": sha256(source),
            "bytes": source.stat().st_size,
            "discovered_from": str(expanded.input_path),
            "input_kind": expanded.input_kind,
            "output_key": expanded.output_key.as_posix(),
        },
        "detection": {
            "selected": selected_by is not None,
            "selected_by": selected_by,
            "classification": report.classification,
            "severity": report.severity,
            "advisories": list(report.advisories),
            "flat_fill_paths": report.flat_fill_paths,
            "distinct_flat_fill_colors": report.distinct_flat_fill_colors,
            "palette_endpoint_distance": report.palette_endpoint_distance,
            "palette_linearity_fraction": report.palette_linearity_fraction,
            "palette_intermediate_colors": report.palette_intermediate_colors,
            "palette_intermediate_paths": report.palette_intermediate_paths,
            "palette_intermediate_path_data_bytes": report.palette_intermediate_path_data_bytes,
            "subpixel_path_data_fraction_256": report.subpixel_path_data_fraction_256,
            "signals": list(report.signals),
        },
    }

    if selected_by is None:
        record.update(
            {
                "transform": None,
                "candidate": None,
                "comparison": None,
                "verdict": "not-selected",
                "timing_seconds": {"total": time.perf_counter() - started},
            }
        )
        return record, None, None

    tree = _parse_svg(source)
    transform_started = time.perf_counter()
    transform = snap_fragmented_palette(
        tree,
        axis_distance=axis_distance,
        endpoint_guard=endpoint_guard,
    )
    transform_seconds = time.perf_counter() - transform_started
    record["transform"] = {
        "name": "palette-paint-endpoint-snap",
        "approximate": True,
        "stats": transform,
    }

    if not transform["changed"]:
        record.update(
            {
                "candidate": None,
                "comparison": None,
                "verdict": "selected-no-change",
                "timing_seconds": {
                    "transform": transform_seconds,
                    "total": time.perf_counter() - started,
                },
            }
        )
        return record, None, None

    case_dir = _case_dir(output_root, expanded)
    candidate = case_dir / f"{source.stem}.palette-snapped.svg"
    render_dir = case_dir / "renders"
    _write_like_source(tree, source, candidate)
    record["candidate"] = {
        "path": str(candidate),
        "sha256": sha256(candidate),
        "bytes": candidate.stat().st_size,
        "byte_delta": candidate.stat().st_size - source.stat().st_size,
        "byte_reduction_fraction": 1.0 - candidate.stat().st_size / source.stat().st_size,
    }
    record["comparison"] = None
    record["verdict"] = "experimental-review-required"
    record["timing_seconds"] = {
        "transform": transform_seconds,
        "compare": None,
        "case_local_total": None,
    }
    return record, candidate, render_dir


def _finish_case(record: dict[str, Any], render_dir: Path, sizes: tuple[int, ...]) -> None:
    metrics, compare_seconds = compare_pair_outputs(render_dir, sizes)
    changed = [metric for metric in metrics if not metric.exact]
    record["comparison"] = {
        "sizes": list(sizes),
        "exact": not changed,
        "automatic_acceptance": False,
        "renders": [asdict(metric) for metric in metrics],
        "summary": {
            "changed_sizes": [metric.size for metric in changed],
            "max_changed_pixel_fraction": max(
                (metric.changed_pixel_fraction for metric in metrics), default=0.0
            ),
            "max_channel_diff": max((metric.max_channel_diff for metric in metrics), default=0),
            "max_rgba_rmse": max((metric.rgba_rmse for metric in metrics), default=0.0),
            "max_premultiplied_rgba_rmse": max(
                (metric.premultiplied_rgba_rmse for metric in metrics), default=0.0
            ),
            "max_white_background_rgb_rmse": max(
                (metric.white_background_rgb_rmse for metric in metrics), default=0.0
            ),
        },
    }
    timing = record["timing_seconds"]
    timing["compare"] = compare_seconds
    timing["case_local_total"] = timing["transform"] + compare_seconds


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Experimental palette repair for SVGs classified as palette-fragmented-trace. "
            "This is approximate and never auto-accepted."
        )
    )
    parser.add_argument("sources", nargs="+", type=Path, help="SVG files and/or directories")
    parser.add_argument("--output-dir", type=Path, default=Path("palette-run"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--inkscape", type=str)
    parser.add_argument(
        "--sizes",
        type=parse_sizes,
        default=DEFAULT_SIZES,
        help="comma-separated render widths (default: 64,128,256,512,1024,1600)",
    )
    parser.add_argument(
        "--include-advisory",
        action="store_true",
        help="also experiment on weaker palette-fragmentation advisories",
    )
    parser.add_argument(
        "--axis-distance",
        type=float,
        default=8.0,
        help="maximum RGB distance from inferred endpoint axis (default: 8)",
    )
    parser.add_argument(
        "--endpoint-guard",
        type=float,
        default=0.02,
        help="do not alter colors within this normalized distance of either endpoint (default: 0.02)",
    )
    args = parser.parse_args()
    if args.axis_distance < 0:
        parser.error("--axis-distance must be >= 0")
    if not 0 <= args.endpoint_guard < 0.5:
        parser.error("--endpoint-guard must be in [0, 0.5)")

    run_started = time.perf_counter()
    output_root = args.output_dir.resolve()
    manifest_path = (args.manifest or output_root / "manifest.json").resolve()
    sources = expand_sources(args.sources, output_root=output_root)
    executable = find_inkscape(args.inkscape)

    records: list[dict[str, Any]] = []
    jobs: list[tuple[int, Path, Path, Path]] = []
    for expanded in sources:
        record, candidate, render_dir = prepare_case(
            expanded,
            output_root,
            include_advisory=args.include_advisory,
            axis_distance=args.axis_distance,
            endpoint_guard=args.endpoint_guard,
        )
        records.append(record)
        if candidate is not None and render_dir is not None:
            jobs.append((len(records) - 1, expanded.path, candidate, render_dir))

    shell_run = render_svg_pairs_shell_batch(
        [
            ShellRenderJob(original=source, candidate=candidate, output_dir=render_dir)
            for _, source, candidate, render_dir in jobs
        ],
        args.sizes,
        inkscape=executable,
        restart_every=0,
    )
    for record_index, _source, _candidate, render_dir in jobs:
        _finish_case(records[record_index], render_dir, args.sizes)

    selected = [record for record in records if record["detection"]["selected"]]
    print(
        f"summary: {len(records)} case(s); {len(selected)} selected; "
        f"{len(jobs)} candidate(s); all candidates require review"
    )
    for record in selected:
        source = record["source"]
        transform = record["transform"]
        comparison = record["comparison"]
        if transform is None:
            print(f"{source['output_key']}: selected but no transform")
            continue
        stats = transform["stats"]
        if comparison is None:
            print(f"{source['output_key']}: selected but unchanged")
            continue
        summary = comparison["summary"]
        print(
            f"{source['output_key']}: snapped {stats['changed_paths']} path(s) / "
            f"{stats['changed_source_colors']} color(s); max-rmse={summary['max_rgba_rmse']:.4f}; "
            f"max-changed={summary['max_changed_pixel_fraction']:.3%}"
        )

    payload = {
        "schema_version": 1,
        "experiment": "palette-fragmented-trace-endpoint-snap",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "inkscape": shell_run.inkscape_version,
            "inkscape_executable": executable,
            "renderer_mode": "inkscape-shell",
        },
        "selection_policy": {
            "default": "classification == palette-fragmented-trace",
            "include_advisory": args.include_advisory,
            "advisory_name": "palette-fragmentation",
        },
        "transform_policy": {
            "kind": "approximate-experimental",
            "name": "palette-paint-endpoint-snap",
            "axis_distance": args.axis_distance,
            "endpoint_guard": args.endpoint_guard,
            "automatic_acceptance": False,
            "rule": (
                "infer the farthest flat-fill RGB endpoints; mapped intermediate colors are snapped "
                "to their nearest endpoint wherever they occur in fill/stroke paint declarations"
            ),
        },
        "comparison_policy": {
            "kind": "source-to-candidate-render-delta",
            "sizes": list(args.sizes),
            "rule": "record error metrics only; no approximate candidate is auto-accepted",
        },
        "run": {
            "input_arguments": [str(path.resolve()) for path in args.sources],
            "cases": len(records),
            "selected_cases": len(selected),
            "candidate_cases": len(jobs),
            "renderer": {
                "processes": shell_run.renderer_processes,
                "document_opens": shell_run.document_opens,
                "exports": shell_run.exports,
                "render_seconds": shell_run.render_seconds,
                "batches": [asdict(batch) for batch in shell_run.batches],
            },
            "total_seconds": time.perf_counter() - run_started,
        },
        "cases": records,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
