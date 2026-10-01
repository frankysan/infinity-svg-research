from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lxml import etree
from scour import scour as scour_module

from . import scan
from .optimize import ExpandedSource, expand_sources, sha256
from .palette_repair import _parse_svg, _scan_for_palette_class, snap_fragmented_palette
from .render_compare import compare_rendered, find_inkscape, parse_sizes
from .transforms import write_tree


DEFAULT_SIZES = (64, 128, 256, 512, 1024, 1600)
TEMP_ID_PREFIX = "__svg_research_union_"
SAFE_PATH_STYLE_PROPERTIES = {
    "fill",
    "fill-opacity",
    "fill-rule",
    "stroke",
    "stroke-opacity",
    "stroke-width",
    "stroke-linecap",
    "stroke-linejoin",
    "stroke-miterlimit",
    "opacity",
}
UNSAFE_PATH_ATTRIBUTES = {
    "clip-path",
    "filter",
    "mask",
    "marker-start",
    "marker-mid",
    "marker-end",
    "mix-blend-mode",
    "paint-order",
    "transform",
    "vector-effect",
}


@dataclass
class UnionGroup:
    ids: list[str]
    fill: tuple[int, int, int]
    fill_rule: str
    path_count: int
    path_data_bytes: int


@dataclass
class UnionProbe:
    case_index: int
    group_index: int
    input_svg: Path
    output_svg: Path


@dataclass
class VariantJob:
    source: Path
    snapped: Path
    consolidated: Path
    output_dir: Path


@dataclass
class ShellTiming:
    processes: int
    document_opens: int
    exports: int
    seconds: float
    inkscape_version: str | None


def _rgb_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{value:02x}" for value in rgb)


def _parse_opacity(value: str | None) -> float | None:
    if value is None:
        return 1.0
    text = value.strip()
    if text.endswith("%"):
        try:
            return float(text[:-1]) / 100.0
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def _effective_property(
    element: etree._Element,
    key: str,
    class_styles: dict[str, dict[str, str]],
    default: str | None = None,
) -> str | None:
    value = default
    chain = list(element.iterancestors())[::-1] + [element]
    for node in chain:
        for class_name in (node.get("class") or "").split():
            class_value = class_styles.get(class_name, {}).get(key)
            if class_value is not None:
                value = class_value.strip()
        attribute_value = node.get(key)
        if attribute_value is not None:
            value = attribute_value.strip()
        inline_value = scan.parse_style_declarations(node.get("style")).get(key)
        if inline_value is not None:
            value = inline_value.strip()
    return value


def _path_specific_properties_safe(
    path: etree._Element,
    class_styles: dict[str, dict[str, str]],
) -> bool:
    if any(path.get(attribute) is not None for attribute in UNSAFE_PATH_ATTRIBUTES):
        return False
    for class_name in (path.get("class") or "").split():
        declarations = class_styles.get(class_name, {})
        if any(key not in SAFE_PATH_STYLE_PROPERTIES for key in declarations):
            return False
    inline = scan.parse_style_declarations(path.get("style"))
    return not any(key not in SAFE_PATH_STYLE_PROPERTIES for key in inline)


def _merge_signature(
    path: etree._Element,
    class_styles: dict[str, dict[str, str]],
) -> tuple[tuple[int, int, int], str] | None:
    if etree.QName(path.tag).localname != "path" or path.get("id") is not None:
        return None
    path_data = path.get("d") or ""
    if not path_data or not _path_specific_properties_safe(path, class_styles):
        return None

    try:
        subpaths, _segments = scan.analyze_path_subpaths(path_data)
        feature_widths, _feature_segments = scan.analyze_path_feature_widths(
            path_data, scan.IDENTITY_MATRIX, curve_samples=8
        )
    except ValueError:
        return None
    if not subpaths or any(not closed for _span, closed in subpaths):
        return None
    # Mathematically zero-area slivers disappear under Inkscape path-union. Leave them
    # to a dedicated degenerate-geometry experiment instead of conflating that cleanup
    # with same-colour consolidation.
    if len(feature_widths) != len(subpaths) or any(width <= 1e-9 for width, _ in feature_widths):
        return None

    props = scan.effective_paint_properties(path, class_styles)
    fill = scan.parse_css_rgb(props.get("fill"))
    if fill is None:
        return None
    stroke = (props.get("stroke") or "none").strip().lower()
    if stroke not in {"none", "transparent"}:
        return None
    for key in ("opacity", "fill-opacity"):
        opacity = _parse_opacity(props.get(key))
        if opacity is None or abs(opacity - 1.0) > 1e-12:
            return None

    fill_rule = (_effective_property(path, "fill-rule", class_styles, "nonzero") or "nonzero").lower()
    if fill_rule != "nonzero":
        return None
    return fill, fill_rule


def _bounds_connected_components(paths: list[etree._Element]) -> list[list[etree._Element]]:
    bounds: list[scan.Bounds | None] = []
    for path in paths:
        try:
            bounds.append(scan.parse_path_bounds(path.get("d") or ""))
        except ValueError:
            bounds.append(None)

    components: list[list[etree._Element]] = []
    visited: set[int] = set()
    for start in range(len(paths)):
        if start in visited or bounds[start] is None:
            continue
        stack = [start]
        visited.add(start)
        indexes: list[int] = []
        while stack:
            current = stack.pop()
            indexes.append(current)
            current_bounds = bounds[current]
            assert current_bounds is not None
            for other in range(len(paths)):
                if other in visited or bounds[other] is None:
                    continue
                if scan.bounds_intersect(current_bounds, bounds[other]):
                    visited.add(other)
                    stack.append(other)
        if len(indexes) >= 2:
            components.append([paths[index] for index in sorted(indexes)])
    return components


def plan_union_groups(tree: etree._ElementTree) -> tuple[list[UnionGroup], dict[str, Any]]:
    root = tree.getroot()
    class_styles = scan.parse_class_styles(root)
    groups: list[UnionGroup] = []
    temp_index = 0
    eligible_paths = 0
    contiguous_runs = 0

    for parent in root.iter():
        children = [child for child in parent if isinstance(child.tag, str)]
        index = 0
        while index < len(children):
            child = children[index]
            signature = _merge_signature(child, class_styles)
            if signature is None:
                index += 1
                continue

            run = [child]
            eligible_paths += 1
            cursor = index + 1
            while cursor < len(children):
                next_child = children[cursor]
                next_signature = _merge_signature(next_child, class_styles)
                if next_signature != signature:
                    break
                run.append(next_child)
                eligible_paths += 1
                cursor += 1

            if len(run) >= 2:
                contiguous_runs += 1
                for component in _bounds_connected_components(run):
                    ids: list[str] = []
                    path_bytes = 0
                    for path in component:
                        temp_id = f"{TEMP_ID_PREFIX}{temp_index:06d}"
                        temp_index += 1
                        path.set("id", temp_id)
                        ids.append(temp_id)
                        path_bytes += len((path.get("d") or "").encode("utf-8"))
                    groups.append(
                        UnionGroup(
                            ids=ids,
                            fill=signature[0],
                            fill_rule=signature[1],
                            path_count=len(component),
                            path_data_bytes=path_bytes,
                        )
                    )
            index = max(cursor, index + 1)

    return groups, {
        "eligible_paths": eligible_paths,
        "contiguous_runs": contiguous_runs,
        "planned_union_groups": len(groups),
        "planned_union_paths": sum(group.path_count for group in groups),
        "planned_path_reduction": sum(group.path_count - 1 for group in groups),
        "planned_path_data_bytes": sum(group.path_data_bytes for group in groups),
    }


def _strip_temp_ids(root: etree._Element) -> int:
    count = 0
    for element in root.xpath(".//*[@id]"):
        ident = element.get("id")
        if ident and ident.startswith(TEMP_ID_PREFIX):
            del element.attrib["id"]
            count += 1
    return count


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


def _serialize_tree(tree: etree._ElementTree, *, xml_declaration: bool) -> bytes:
    return etree.tostring(
        tree, encoding="UTF-8", xml_declaration=xml_declaration, pretty_print=False
    )


def _shell_path(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    if ";" in value or "\n" in value or "\r" in value:
        raise RuntimeError(f"Inkscape shell paths cannot contain ';' or newlines: {path}")
    return value


def _parse_shell_version(output: str) -> str | None:
    for line in output.splitlines():
        candidate = line.strip().lstrip("> ").strip()
        if re.match(r"^Inkscape\s+\d", candidate):
            return candidate
    return None


def _build_probe_svg(group: UnionGroup, tree: etree._ElementTree, destination: Path) -> None:
    root = tree.getroot()
    svg = etree.Element(
        "{http://www.w3.org/2000/svg}svg",
        nsmap={None: "http://www.w3.org/2000/svg"},
        viewBox="0 0 1 1",
    )
    for index, ident in enumerate(group.ids):
        matches = root.xpath(f'.//*[@id="{ident}"]')
        if len(matches) != 1:
            raise RuntimeError(f"Could not resolve planned union path id {ident}")
        etree.SubElement(
            svg,
            "{http://www.w3.org/2000/svg}path",
            id=f"p{index}",
            d=matches[0].get("d") or "",
            fill="#000",
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(etree.tostring(svg, encoding="UTF-8", xml_declaration=True))


def _probe_actions(probe: UnionProbe, path_count: int) -> str:
    ids = ",".join(f"p{index}" for index in range(path_count))
    return "; ".join(
        [
            f"file-open:{_shell_path(probe.input_svg)}",
            "select-clear",
            f"select-by-id:{ids}",
            "path-union",
            "object-set-attribute:fill,#000000",
            "object-set-attribute:stroke,none",
            "export-plain-svg",
            f"export-filename:{_shell_path(probe.output_svg)}",
            "export-do",
            "file-close",
        ]
    )


def run_union_probes(
    probes: list[tuple[UnionProbe, int]],
    *,
    inkscape: str,
) -> ShellTiming:
    if not probes:
        return ShellTiming(0, 0, 0, 0.0, None)
    lines = ["inkscape-version"]
    expected: list[Path] = []
    for probe, path_count in probes:
        if probe.output_svg.exists():
            probe.output_svg.unlink()
        expected.append(probe.output_svg)
        lines.append(_probe_actions(probe, path_count))
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
    seconds = time.perf_counter() - started
    combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if result.returncode != 0:
        raise RuntimeError(f"Inkscape union-probe shell failed (exit {result.returncode}): {combined.strip()}")
    missing = [str(path) for path in expected if not path.exists()]
    if missing:
        raise RuntimeError("Inkscape union-probe shell did not create: " + ", ".join(missing))
    return ShellTiming(1, len(probes), len(probes), seconds, _parse_shell_version(combined))


def _extract_compact_union_path(probe_output: Path) -> str:
    text = probe_output.read_text(encoding="utf-8")
    scoured = scour_module.scourString(text, scour_module.sanitizeOptions())
    root = etree.fromstring(scoured.encode("utf-8"))
    paths = root.xpath(".//s:path", namespaces=scan.NS)
    if len(paths) != 1:
        raise RuntimeError(f"Union probe {probe_output} produced {len(paths)} paths instead of one")
    path_data = paths[0].get("d") or ""
    if not path_data:
        raise RuntimeError(f"Union probe {probe_output} produced an empty path")
    return path_data


def _apply_group_union(
    tree: etree._ElementTree,
    group: UnionGroup,
    union_path_data: str,
) -> None:
    root = tree.getroot()
    elements: list[etree._Element] = []
    for ident in group.ids:
        matches = root.xpath(f'.//*[@id="{ident}"]')
        if len(matches) != 1:
            raise RuntimeError(f"Could not apply union group; missing {ident}")
        elements.append(matches[0])
    first = elements[0]
    first.set("d", union_path_data)
    for element in elements[1:]:
        parent = element.getparent()
        if parent is None:
            raise RuntimeError("Union group path unexpectedly has no parent")
        parent.remove(element)


def _individual_serialized_savings(
    snapped: Path,
    group_index: int,
    union_path_data: str,
) -> int:
    tree = _parse_svg(snapped)
    groups, _stats = plan_union_groups(tree)
    if group_index >= len(groups):
        raise RuntimeError("Union planning was not deterministic")
    _apply_group_union(tree, groups[group_index], union_path_data)
    _strip_temp_ids(tree.getroot())
    return snapped.stat().st_size - len(
        _serialize_tree(tree, xml_declaration=_has_xml_declaration(snapped))
    )


def _assemble_candidate(
    snapped: Path,
    accepted: list[tuple[int, str]],
    destination: Path,
) -> dict[str, int]:
    tree = _parse_svg(snapped)
    groups, _stats = plan_union_groups(tree)
    paths_before = len(tree.getroot().xpath(".//s:path", namespaces=scan.NS))
    for group_index, union_path_data in accepted:
        _apply_group_union(tree, groups[group_index], union_path_data)
    stripped = _strip_temp_ids(tree.getroot())
    _write_like_source(tree, snapped, destination)
    paths_after = len(tree.getroot().xpath(".//s:path", namespaces=scan.NS))
    return {
        "paths_before": paths_before,
        "paths_after": paths_after,
        "actual_path_reduction": paths_before - paths_after,
        "stripped_temporary_ids": stripped,
    }


def _variant_export_actions(svg: Path, prefix: str, output_dir: Path, sizes: tuple[int, ...]) -> str:
    actions = [
        f"file-open:{_shell_path(svg)}",
        "export-area-page",
        "export-background-opacity:0",
    ]
    for size in sizes:
        output = output_dir / f"{prefix}-{size}.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            output.unlink()
        actions.extend(
            [
                f"export-width:{size}",
                f"export-filename:{_shell_path(output)}",
                "export-do",
            ]
        )
    actions.append("file-close")
    return "; ".join(actions)


def render_variants_shell(
    jobs: list[VariantJob],
    sizes: tuple[int, ...],
    *,
    inkscape: str,
) -> ShellTiming:
    if not jobs:
        return ShellTiming(0, 0, 0, 0.0, None)
    lines = ["inkscape-version"]
    expected: list[Path] = []
    for job in jobs:
        for prefix, svg in (
            ("source", job.source),
            ("snapped", job.snapped),
            ("consolidated", job.consolidated),
        ):
            lines.append(_variant_export_actions(svg, prefix, job.output_dir, sizes))
            expected.extend(job.output_dir / f"{prefix}-{size}.png" for size in sizes)
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
    seconds = time.perf_counter() - started
    combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if result.returncode != 0:
        raise RuntimeError(f"Inkscape render shell failed (exit {result.returncode}): {combined.strip()}")
    missing = [str(path) for path in expected if not path.exists()]
    if missing:
        raise RuntimeError("Inkscape render shell did not create: " + ", ".join(missing))
    return ShellTiming(
        1,
        3 * len(jobs),
        3 * len(jobs) * len(sizes),
        seconds,
        _parse_shell_version(combined),
    )


def _compare_variants(
    render_dir: Path,
    sizes: tuple[int, ...],
    left: str,
    right: str,
    diff_prefix: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    metrics = [
        compare_rendered(
            render_dir / f"{left}-{size}.png",
            render_dir / f"{right}-{size}.png",
            size=size,
            diff_png=render_dir / f"{diff_prefix}-{size}.png",
        )
        for size in sizes
    ]
    changed = [metric for metric in metrics if not metric.exact]
    return {
        "left": left,
        "right": right,
        "exact": not changed,
        "renders": [asdict(metric) for metric in metrics],
        "summary": {
            "changed_sizes": [metric.size for metric in changed],
            "max_changed_pixel_fraction": max((m.changed_pixel_fraction for m in metrics), default=0.0),
            "max_channel_diff": max((m.max_channel_diff for m in metrics), default=0),
            "max_rgba_rmse": max((m.rgba_rmse for m in metrics), default=0.0),
            "max_premultiplied_rgba_rmse": max(
                (m.premultiplied_rgba_rmse for m in metrics), default=0.0
            ),
            "max_white_background_rgb_rmse": max(
                (m.white_background_rgb_rmse for m in metrics), default=0.0
            ),
            "max_alpha_rmse": max((m.alpha_rmse for m in metrics), default=0.0),
        },
        "compare_seconds": time.perf_counter() - started,
    }


def _case_dir(output_root: Path, expanded: ExpandedSource) -> Path:
    return output_root / expanded.output_key


def prepare_cases(
    sources: list[ExpandedSource],
    output_root: Path,
    *,
    include_advisory: bool,
    axis_distance: float,
    endpoint_guard: float,
) -> tuple[list[dict[str, Any]], list[list[UnionGroup]], list[Path | None]]:
    records: list[dict[str, Any]] = []
    groups_by_case: list[list[UnionGroup]] = []
    snapped_by_case: list[Path | None] = []

    for expanded in sources:
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
                    "palette_snap": None,
                    "consolidation": None,
                    "artifacts": None,
                    "comparisons": None,
                    "verdict": "not-selected",
                    "timing_seconds": {"total": time.perf_counter() - started},
                }
            )
            records.append(record)
            groups_by_case.append([])
            snapped_by_case.append(None)
            continue

        tree = _parse_svg(source)
        snap_started = time.perf_counter()
        snap_stats = snap_fragmented_palette(
            tree,
            axis_distance=axis_distance,
            endpoint_guard=endpoint_guard,
        )
        snap_seconds = time.perf_counter() - snap_started
        record["palette_snap"] = {
            "name": "palette-paint-endpoint-snap",
            "approximate": True,
            "stats": snap_stats,
        }
        if not snap_stats["changed"]:
            record.update(
                {
                    "consolidation": None,
                    "artifacts": None,
                    "comparisons": None,
                    "verdict": "selected-no-palette-change",
                    "timing_seconds": {
                        "palette_snap": snap_seconds,
                        "total": time.perf_counter() - started,
                    },
                }
            )
            records.append(record)
            groups_by_case.append([])
            snapped_by_case.append(None)
            continue

        case_dir = _case_dir(output_root, expanded)
        snapped = case_dir / f"{source.stem}.palette-snapped.svg"
        _write_like_source(tree, source, snapped)
        planned_tree = _parse_svg(snapped)
        groups, plan_stats = plan_union_groups(planned_tree)
        record["consolidation"] = {
            "name": "byte-beneficial-same-colour-connected-path-union",
            "approximate": True,
            "planning": plan_stats,
            "group_results": None,
            "accepted_groups": None,
            "execution": None,
        }
        record["artifacts"] = {
            "snapped": {
                "path": str(snapped),
                "sha256": sha256(snapped),
                "bytes": snapped.stat().st_size,
                "byte_delta_vs_source": snapped.stat().st_size - source.stat().st_size,
            },
            "consolidated": None,
        }
        record["comparisons"] = None
        record["verdict"] = "experimental-review-required"
        record["timing_seconds"] = {
            "palette_snap": snap_seconds,
            "prepare": time.perf_counter() - started - snap_seconds,
            "compare": None,
            "case_local_total": None,
        }
        records.append(record)
        groups_by_case.append(groups)
        snapped_by_case.append(snapped)

    return records, groups_by_case, snapped_by_case


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Experimental palette repair followed by byte-beneficial same-colour connected-path "
            "boolean-union probes. Approximate and never auto-accepted."
        )
    )
    parser.add_argument("sources", nargs="+", type=Path, help="SVG files and/or directories")
    parser.add_argument("--output-dir", type=Path, default=Path("palette-consolidation-run"))
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
    parser.add_argument("--axis-distance", type=float, default=8.0)
    parser.add_argument("--endpoint-guard", type=float, default=0.02)
    parser.add_argument(
        "--min-byte-savings",
        type=int,
        default=1,
        help="minimum independently measured serialized-byte saving for a union group (default: 1)",
    )
    parser.add_argument(
        "--keep-probes",
        action="store_true",
        help="keep minimal per-group Inkscape union-probe SVGs",
    )
    args = parser.parse_args()
    if args.axis_distance < 0:
        parser.error("--axis-distance must be >= 0")
    if not 0 <= args.endpoint_guard < 0.5:
        parser.error("--endpoint-guard must be in [0, 0.5)")
    if args.min_byte_savings < 1:
        parser.error("--min-byte-savings must be >= 1")

    run_started = time.perf_counter()
    output_root = args.output_dir.resolve()
    manifest_path = (args.manifest or output_root / "manifest.json").resolve()
    expanded_sources = expand_sources(args.sources, output_root=output_root)
    executable = find_inkscape(args.inkscape)

    records, groups_by_case, snapped_by_case = prepare_cases(
        expanded_sources,
        output_root,
        include_advisory=args.include_advisory,
        axis_distance=args.axis_distance,
        endpoint_guard=args.endpoint_guard,
    )

    probes: list[tuple[UnionProbe, int]] = []
    for case_index, groups in enumerate(groups_by_case):
        snapped = snapped_by_case[case_index]
        if snapped is None or not groups:
            continue
        planned_tree = _parse_svg(snapped)
        replay_groups, _stats = plan_union_groups(planned_tree)
        if len(replay_groups) != len(groups):
            raise RuntimeError("Union planning was not deterministic")
        probe_dir = snapped.parent / ".union-probes"
        for group_index, group in enumerate(replay_groups):
            input_svg = probe_dir / f"group-{group_index:04d}.input.svg"
            output_svg = probe_dir / f"group-{group_index:04d}.union.svg"
            _build_probe_svg(group, planned_tree, input_svg)
            probes.append(
                (
                    UnionProbe(
                        case_index=case_index,
                        group_index=group_index,
                        input_svg=input_svg,
                        output_svg=output_svg,
                    ),
                    group.path_count,
                )
            )

    probe_shell = run_union_probes(probes, inkscape=executable)

    probe_map: dict[tuple[int, int], UnionProbe] = {
        (probe.case_index, probe.group_index): probe for probe, _count in probes
    }
    variant_jobs: list[VariantJob] = []
    selected_case_indexes: list[int] = []
    for case_index, record in enumerate(records):
        if not record["detection"]["selected"]:
            continue
        snapped = snapped_by_case[case_index]
        if snapped is None:
            continue
        selected_case_indexes.append(case_index)
        groups = groups_by_case[case_index]
        group_results: list[dict[str, Any]] = []
        accepted: list[tuple[int, str]] = []
        for group_index, group in enumerate(groups):
            probe = probe_map[(case_index, group_index)]
            union_path_data = _extract_compact_union_path(probe.output_svg)
            savings = _individual_serialized_savings(snapped, group_index, union_path_data)
            accepted_here = savings >= args.min_byte_savings
            if accepted_here:
                accepted.append((group_index, union_path_data))
            group_results.append(
                {
                    "index": group_index,
                    "path_count": group.path_count,
                    "path_data_bytes_before": group.path_data_bytes,
                    "path_data_bytes_after_union": len(union_path_data.encode("utf-8")),
                    "path_data_byte_delta": len(union_path_data.encode("utf-8")) - group.path_data_bytes,
                    "serialized_byte_savings_if_applied_alone": savings,
                    "accepted_by_size_filter": accepted_here,
                    "fill": _rgb_hex(group.fill),
                    "fill_rule": group.fill_rule,
                }
            )

        source = Path(record["source"]["path"])
        case_dir = snapped.parent
        candidate = case_dir / f"{source.stem}.palette-consolidated.svg"
        if accepted:
            execution = _assemble_candidate(snapped, accepted, candidate)
            record["artifacts"]["consolidated"] = {
                "path": str(candidate),
                "sha256": sha256(candidate),
                "bytes": candidate.stat().st_size,
                "byte_delta_vs_source": candidate.stat().st_size - source.stat().st_size,
                "byte_reduction_fraction_vs_source": 1.0 - candidate.stat().st_size / source.stat().st_size,
                "byte_delta_vs_snapped": candidate.stat().st_size - snapped.stat().st_size,
                "byte_reduction_fraction_vs_snapped": 1.0 - candidate.stat().st_size / snapped.stat().st_size,
            }
            record["consolidation"]["execution"] = execution
            record["verdict"] = "experimental-review-required"
            consolidated_for_render = candidate
        else:
            record["consolidation"]["execution"] = {
                "paths_before": len(_parse_svg(snapped).getroot().xpath(".//s:path", namespaces=scan.NS)),
                "paths_after": len(_parse_svg(snapped).getroot().xpath(".//s:path", namespaces=scan.NS)),
                "actual_path_reduction": 0,
                "stripped_temporary_ids": 0,
            }
            record["verdict"] = "selected-no-byte-beneficial-unions"
            consolidated_for_render = snapped

        record["consolidation"]["group_results"] = group_results
        record["consolidation"]["accepted_groups"] = [index for index, _data in accepted]
        record["consolidation"]["accepted_group_count"] = len(accepted)
        record["consolidation"]["accepted_individual_serialized_savings"] = sum(
            item["serialized_byte_savings_if_applied_alone"]
            for item in group_results
            if item["accepted_by_size_filter"]
        )
        variant_jobs.append(
            VariantJob(
                source=source,
                snapped=snapped,
                consolidated=consolidated_for_render,
                output_dir=case_dir / "renders",
            )
        )

    render_shell = render_variants_shell(variant_jobs, args.sizes, inkscape=executable)
    for case_index, job in zip(selected_case_indexes, variant_jobs):
        record = records[case_index]
        source_to_snapped = _compare_variants(
            job.output_dir, args.sizes, "source", "snapped", "diff-source-snapped"
        )
        snapped_to_consolidated = _compare_variants(
            job.output_dir,
            args.sizes,
            "snapped",
            "consolidated",
            "diff-snapped-consolidated",
        )
        source_to_consolidated = _compare_variants(
            job.output_dir,
            args.sizes,
            "source",
            "consolidated",
            "diff-source-consolidated",
        )
        record["comparisons"] = {
            "source_to_snapped": source_to_snapped,
            "snapped_to_consolidated": snapped_to_consolidated,
            "source_to_consolidated": source_to_consolidated,
        }
        compare_seconds = sum(
            item["compare_seconds"]
            for item in (source_to_snapped, snapped_to_consolidated, source_to_consolidated)
        )
        record["timing_seconds"]["compare"] = compare_seconds
        record["timing_seconds"]["case_local_total"] = (
            record["timing_seconds"]["palette_snap"]
            + record["timing_seconds"]["prepare"]
            + compare_seconds
        )

    if not args.keep_probes:
        for record in records:
            artifacts = record.get("artifacts")
            if not artifacts:
                continue
            snapped_info = artifacts.get("snapped")
            if not snapped_info:
                continue
            probe_dir = Path(snapped_info["path"]).parent / ".union-probes"
            if probe_dir.exists():
                shutil.rmtree(probe_dir)

    selected = [record for record in records if record["detection"]["selected"]]
    candidates = [record for record in selected if record["artifacts"] and record["artifacts"]["consolidated"]]
    print(
        f"summary: {len(records)} case(s); {len(selected)} selected; "
        f"{len(candidates)} byte-beneficial consolidated candidate(s); all require review"
    )
    for record in selected:
        key = record["source"]["output_key"]
        consolidation = record.get("consolidation")
        if not consolidation:
            print(f"{key}: no consolidation stage")
            continue
        accepted_count = consolidation.get("accepted_group_count", 0)
        geometry = record.get("comparisons", {}).get("snapped_to_consolidated", {}).get("summary", {})
        if record["artifacts"] and record["artifacts"]["consolidated"]:
            candidate = record["artifacts"]["consolidated"]
            print(
                f"{key}: accepted-groups={accepted_count}; "
                f"bytes={record['artifacts']['snapped']['bytes']}->{candidate['bytes']} vs snapped; "
                f"geometry-rmse={geometry.get('max_rgba_rmse', 0.0):.4f}"
            )
        else:
            print(f"{key}: accepted-groups=0; no byte-beneficial geometry union")

    payload = {
        "schema_version": 1,
        "experiment": "palette-fragmented-trace-byte-beneficial-connected-union",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "inkscape": render_shell.inkscape_version or probe_shell.inkscape_version,
            "inkscape_executable": executable,
            "renderer_mode": "inkscape-shell",
            "scour": "0.38+",
        },
        "selection_policy": {
            "default": "classification == palette-fragmented-trace",
            "include_advisory": args.include_advisory,
            "advisory_name": "palette-fragmentation",
        },
        "transform_policy": {
            "kind": "approximate-experimental",
            "automatic_acceptance": False,
            "stages": [
                {
                    "name": "palette-paint-endpoint-snap",
                    "axis_distance": args.axis_distance,
                    "endpoint_guard": args.endpoint_guard,
                },
                {
                    "name": "byte-beneficial-same-colour-connected-path-union",
                    "min_byte_savings": args.min_byte_savings,
                    "rule": (
                        "plan only consecutive sibling closed paths with identical effective flat fill, "
                        "no stroke, full opacity, nonzero fill-rule, no path-local effects/transform, "
                        "and bounding-box-connected geometry; obtain each boolean-union path from a minimal "
                        "Inkscape probe, splice only the compact union path back into the snapped SVG, and "
                        "keep a group only when independent full-SVG serialization becomes smaller"
                    ),
                },
            ],
        },
        "comparison_policy": {
            "sizes": list(args.sizes),
            "pairs": ["source_to_snapped", "snapped_to_consolidated", "source_to_consolidated"],
            "rule": (
                "separate palette-normalization error from geometry-consolidation error; "
                "no approximate candidate is auto-accepted"
            ),
        },
        "run": {
            "input_arguments": [str(path.resolve()) for path in args.sources],
            "cases": len(records),
            "selected_cases": len(selected),
            "union_probe_groups": len(probes),
            "consolidated_candidate_cases": len(candidates),
            "probe_shell": asdict(probe_shell),
            "render_shell": asdict(render_shell),
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
