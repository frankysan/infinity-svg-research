from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict
from pathlib import Path
from statistics import median
from typing import Any

from lxml import etree

from . import render_compare
from . import scan

DEFAULT_SIZES = (64, 128, 256, 512, 1024, 1600)
CSS_RULE_RE = re.compile(r"(?P<selectors>[^{}]+)\{(?P<body>[^{}]*)\}")
URL_REF_RE = re.compile(r"url\(\s*#([^)\s]+)\s*\)")
SIMPLE_CLASS_RE = re.compile(r"^\.([\w-]+)$")


def _parse_svg(path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        recover=False,
        huge_tree=True,
        remove_blank_text=False,
    )
    return etree.parse(str(path), parser)


def _class_fill(root: etree._Element) -> dict[str, str]:
    style_text = "\n".join(root.xpath(".//s:style/text()", namespaces=scan.NS))
    return {match.group(1): match.group(2) for match in scan.CLASS_FILL_RE.finditer(style_text)}


def _gradients(root: etree._Element) -> dict[str, etree._Element]:
    return {
        element.get("id"): element
        for element in root.xpath(".//s:linearGradient | .//s:radialGradient", namespaces=scan.NS)
        if element.get("id")
    }


def _step_translation(base: etree._Element, step: etree._Element) -> tuple[float, float]:
    shifts: list[tuple[float, float]] = []
    for base_geometry, geometry in zip(list(base), list(step), strict=True):
        _base_norm, base_anchor = scan.normalized_geometry(base_geometry)
        _norm, anchor = scan.normalized_geometry(geometry)
        shifts.append((anchor[0] - base_anchor[0], anchor[1] - base_anchor[1]))
    return median(x for x, _y in shifts), median(y for _x, y in shifts)


def _format_number(value: float) -> str:
    if abs(value) < 5e-12:
        value = 0.0
    return f"{value:.9g}"


def _unique_id(root: etree._Element, prefix: str) -> str:
    existing = {element.get("id") for element in root.iter() if isinstance(element.tag, str)}
    index = 1
    while f"{prefix}-{index}" in existing:
        index += 1
    return f"{prefix}-{index}"


def _simple_group_attributes(group: etree._Element) -> bool:
    return all(name == "id" for name in group.attrib)


def rewrite_blend_stacks(
    tree: etree._ElementTree,
    *,
    geometry_tolerance: float = 0.011,
    translation_tolerance: float = 0.021,
) -> dict[str, Any]:
    root = tree.getroot()
    class_fill = _class_fill(root)
    gradients = _gradients(root)
    candidates: list[tuple[etree._Element, scan.BlendStackEvidence]] = []
    for group in root.xpath(".//s:g", namespaces=scan.NS):
        evidence = scan.analyze_blend_stack(
            group,
            class_fill,
            gradients,
            geometry_tolerance,
            translation_tolerance,
        )
        if evidence is not None:
            candidates.append((group, evidence))

    rewritten = 0
    generated_uses = 0
    replaced_steps = 0
    rejected_group_attributes = 0
    stack_stats: list[dict[str, Any]] = []
    for stack, evidence in candidates:
        steps = list(stack)
        if not all(_simple_group_attributes(step) for step in steps):
            rejected_group_attributes += 1
            continue
        base = steps[0]
        base_id = base.get("id") or _unique_id(root, "blend-use-base")
        base.set("id", base_id)
        translations: list[tuple[float, float]] = []
        for step in steps[1:]:
            translations.append(_step_translation(base, step))
        for step, (dx, dy) in zip(steps[1:], translations, strict=True):
            use = etree.Element(f"{{{scan.SVG}}}use")
            use.set("href", f"#{base_id}")
            use.set(f"{{{scan.XLINK}}}href", f"#{base_id}")
            use.set("transform", f"translate({_format_number(dx)} {_format_number(dy)})")
            stack.replace(step, use)
            generated_uses += 1
            replaced_steps += 1
        rewritten += 1
        stack_stats.append(
            {
                "steps": evidence.steps,
                "glyphs_per_step": evidence.glyphs_per_step,
                "base_id": base_id,
                "uses": len(translations),
                "translations": [[dx, dy] for dx, dy in translations],
            }
        )

    return {
        "detected_stacks": len(candidates),
        "rewritten_stacks": rewritten,
        "rejected_group_attributes": rejected_group_attributes,
        "replaced_steps": replaced_steps,
        "generated_uses": generated_uses,
        "stacks": stack_stats,
    }


def prune_unused_class_rules(root: etree._Element) -> dict[str, int]:
    used_classes = {
        class_name
        for element in root.iter()
        if isinstance(element.tag, str)
        for class_name in (element.get("class") or "").split()
        if class_name
    }
    removed_rules = 0
    removed_bytes = 0
    for style in root.xpath(".//s:style", namespaces=scan.NS):
        text = style.text or ""
        parts: list[str] = []
        cursor = 0
        for match in CSS_RULE_RE.finditer(text):
            parts.append(text[cursor : match.start()])
            selectors = [selector.strip() for selector in match.group("selectors").split(",")]
            classes = [SIMPLE_CLASS_RE.fullmatch(selector) for selector in selectors]
            removable = bool(classes) and all(item is not None for item in classes) and all(
                item.group(1) not in used_classes for item in classes if item is not None
            )
            if removable:
                removed_rules += 1
                removed_bytes += len(match.group(0).encode("utf-8"))
            else:
                parts.append(match.group(0))
            cursor = match.end()
        parts.append(text[cursor:])
        style.text = "".join(parts)
    return {"removed_css_rules": removed_rules, "removed_css_bytes_estimate": removed_bytes}


def _initial_id_references(root: etree._Element) -> set[str]:
    refs: set[str] = set()
    gradient_names = {"linearGradient", "radialGradient"}
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        if scan.local_name(element) in gradient_names:
            continue
        for value in element.attrib.values():
            refs.update(URL_REF_RE.findall(value))
            if value.startswith("#"):
                refs.add(value[1:])
        if scan.local_name(element) == "style" and element.text:
            refs.update(URL_REF_RE.findall(element.text))
    return refs


def prune_unused_gradients(root: etree._Element) -> dict[str, int]:
    gradients = _gradients(root)
    keep = _initial_id_references(root)
    queue = list(keep)
    while queue:
        gradient_id = queue.pop()
        gradient = gradients.get(gradient_id)
        if gradient is None:
            continue
        href = gradient.get(f"{{{scan.XLINK}}}href") or gradient.get("href")
        if href and href.startswith("#") and href[1:] not in keep:
            keep.add(href[1:])
            queue.append(href[1:])
        for value in gradient.attrib.values():
            for ref in URL_REF_RE.findall(value):
                if ref not in keep:
                    keep.add(ref)
                    queue.append(ref)

    removed = 0
    removed_bytes = 0
    for gradient_id, gradient in list(gradients.items()):
        if gradient_id in keep:
            continue
        parent = gradient.getparent()
        if parent is None:
            continue
        removed_bytes += len(etree.tostring(gradient, encoding="utf-8"))
        parent.remove(gradient)
        removed += 1
    return {"removed_gradients": removed, "removed_gradient_bytes_estimate": removed_bytes}


def _scan_source(path: Path) -> scan.SvgReport:
    return scan.scan_file(
        path,
        path.name,
        confirm_blends=True,
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
            "Experimental replacement of confirmed translated blend-stack steps with <use> clones. "
            "Outputs always require render review."
        )
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("blend-use-reconstruction"))
    parser.add_argument("--sizes", type=render_compare.parse_sizes, default=DEFAULT_SIZES)
    parser.add_argument("--inkscape")
    parser.add_argument("--geometry-tolerance", type=float, default=0.011)
    parser.add_argument("--translation-tolerance", type=float, default=0.021)
    parser.add_argument(
        "--no-render",
        action="store_true",
        help="write the experimental candidate without invoking Inkscape",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow experimentation on a source not classified as flattened-blend-stack",
    )
    args = parser.parse_args()
    source = args.source.resolve()
    if not source.is_file():
        parser.error(f"source does not exist: {args.source}")

    report = _scan_source(source)
    if report.classification != "flattened-blend-stack" and not args.force:
        parser.error(
            f"source classification is {report.classification!r}, not 'flattened-blend-stack'; use --force for an explicit experiment"
        )

    tree = _parse_svg(source)
    rewrite = rewrite_blend_stacks(
        tree,
        geometry_tolerance=args.geometry_tolerance,
        translation_tolerance=args.translation_tolerance,
    )
    css = prune_unused_class_rules(tree.getroot())
    gradients = prune_unused_gradients(tree.getroot())

    args.output_dir.mkdir(parents=True, exist_ok=True)
    candidate = args.output_dir / f"{source.stem}.blend-use.svg"
    tree.write(str(candidate), encoding="UTF-8", xml_declaration=True, pretty_print=False)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "experiment": "blend-use-reconstruction",
        "verdict": "experimental-review-required",
        "automatic_acceptance": False,
        "source": str(source),
        "candidate": str(candidate),
        "source_classification": report.classification,
        "source_size_bytes": source.stat().st_size,
        "candidate_size_bytes": candidate.stat().st_size,
        "byte_reduction_fraction": 1.0 - candidate.stat().st_size / source.stat().st_size,
        "rewrite": rewrite,
        "css_pruning": css,
        "gradient_pruning": gradients,
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
