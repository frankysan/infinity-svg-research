from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from lxml import etree
from scour import scour as scour_module

from . import blend_use_reconstruct
from . import render_compare
from . import scan

DEFAULT_SIZES = (64, 128, 256, 512, 1024, 1600)
URL_REF_RE = re.compile(r"url\(\s*#([^)\s]+)\s*\)")

# Recovered/refitted from the raw Guijia scaffold. The compact target is three
# gradients total: one gray disc gradient plus two differently angled accent
# gradients. Accent colors are recovered from the source palette. Coordinates are expressed relative to the detected concentric
# circles so the experiment remains auditable and can be tested on compatible
# source-hash families.
GRAY_GRADIENT_RELATIVE = {
    "x1": -3.59488739985701 / 32.02,
    "y1": 28.48001510176267 / 32.02,
    "x2": 3.86016836849642 / 32.02,
    "y2": -30.58166813082862 / 32.02,
}
GRAY_DARK = "#d9dcde"
GRAY_LIGHT = "#ffffff"

ACCENT_BASE_RELATIVE = {
    "x1": -19.64 / 24.69,
    "y1": -14.73 / 24.69,
    "x2": 20.50 / 24.69,
    "y2": 15.37 / 24.69,
}
ACCENT_HIGHLIGHT_RELATIVE = {
    "x1": 2.371924390837344 / 24.69,
    "y1": -24.575802625431196 / 24.69,
    "x2": 1.56632498687974 / 24.69,
    "y2": -16.2288873429259 / 24.69,
}
ACCENT_HIGHLIGHT_START_OPACITY = 0.6154277671321837


class ReconstructionError(RuntimeError):
    pass


def _parse_svg(path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        recover=False,
        huge_tree=True,
        remove_blank_text=False,
    )
    return etree.parse(str(path), parser)


def _format_number(value: float) -> str:
    if abs(value) < 5e-12:
        value = 0.0
    return f"{value:.9g}"


def _local(element: etree._Element) -> str:
    return scan.local_name(element)


def _descendants(element: etree._Element, name: str) -> list[etree._Element]:
    return [node for node in element.iter() if isinstance(node.tag, str) and _local(node) == name]


def _url_refs_from_element(element: etree._Element, *, include_descendants: bool = True) -> set[str]:
    refs: set[str] = set()
    nodes: Iterable[etree._Element] = element.iter() if include_descendants else (element,)
    for node in nodes:
        if not isinstance(node.tag, str):
            continue
        for value in node.attrib.values():
            refs.update(URL_REF_RE.findall(value))
            if value.startswith("#"):
                refs.add(value[1:])
        if _local(node) == "style" and node.text:
            refs.update(URL_REF_RE.findall(node.text))
    return refs


def _ids_in(element: etree._Element) -> set[str]:
    return {
        node.get("id")
        for node in element.iter()
        if isinstance(node.tag, str) and node.get("id")
    }


def _direct_graphic_children(group: etree._Element) -> list[etree._Element]:
    return [child for child in group if isinstance(child.tag, str)]


def _parse_declarations(text: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    for match in re.finditer(r"([A-Za-z-]+)\s*:\s*([^;}]+)", text):
        declarations[match.group(1).strip().lower()] = match.group(2).strip()
    return declarations


def _class_style_rules(root: etree._Element) -> dict[str, dict[str, str]]:
    rules: dict[str, dict[str, str]] = {}
    for style in root.xpath(".//s:style", namespaces=scan.NS):
        text = style.text or ""
        for match in re.finditer(r"\.([A-Za-z_][\w-]*)\s*\{([^}]*)\}", text, re.S):
            class_name = match.group(1)
            declarations = _parse_declarations(match.group(2))
            if class_name not in rules:
                rules[class_name] = {}
            rules[class_name].update(declarations)
    return rules


def _resolved_property(element: etree._Element, property_name: str) -> str | None:
    property_name = property_name.lower()
    value = element.get(property_name)
    root = element.getroottree().getroot()
    rules = _class_style_rules(root)
    for class_name in (element.get("class") or "").split():
        class_value = rules.get(class_name, {}).get(property_name)
        if class_value is not None:
            value = class_value
    inline_value = _parse_declarations(element.get("style") or "").get(property_name)
    if inline_value is not None:
        value = inline_value
    return value


def _style_contains(element: etree._Element, needle: str) -> bool:
    normalized = needle.replace(" ", "").lower()
    fragments = [element.get("style") or ""]
    root = element.getroottree().getroot()
    rules = _class_style_rules(root)
    for class_name in (element.get("class") or "").split():
        declarations = rules.get(class_name)
        if declarations:
            fragments.append(";".join(f"{key}:{value}" for key, value in declarations.items()))
    return normalized in ";".join(fragments).replace(" ", "").lower()


def _geometry_count(element: etree._Element, name: str) -> int:
    return sum(1 for node in element.iter() if isinstance(node.tag, str) and _local(node) == name)


def _stripe_geometry_count(element: etree._Element) -> int:
    # Raw Corvus Belli exports use polygons for these clipped stripe fields,
    # while published/Scoured copies can contain equivalent paths.
    return sum(
        1
        for node in element.iter()
        if isinstance(node.tag, str) and _local(node) in {"path", "polygon", "rect"}
    )


def _float_attr(element: etree._Element, name: str) -> float:
    value = element.get(name)
    if value is None:
        raise ReconstructionError(f"expected {name!r} on {_local(element)}")
    try:
        return float(value)
    except ValueError as exc:
        raise ReconstructionError(f"non-numeric {name!r}={value!r}") from exc


def _circle_geometry(element: etree._Element) -> tuple[float, float, float]:
    if _local(element) != "circle":
        raise ReconstructionError(f"expected circle, got {_local(element)!r}")
    return _float_attr(element, "cx"), _float_attr(element, "cy"), _float_attr(element, "r")


def _near(a: float, b: float, tolerance: float = 0.2) -> bool:
    return abs(a - b) <= tolerance


def _own_url_ref(element: etree._Element, property_name: str) -> str | None:
    value = _resolved_property(element, property_name)
    if not value:
        return None
    refs = URL_REF_RE.findall(value)
    return refs[0] if refs else None


def _is_in_defs(element: etree._Element) -> bool:
    return any(isinstance(parent.tag, str) and _local(parent) == "defs" for parent in element.iterancestors())


def _id_lookup(root: etree._Element) -> dict[str, etree._Element]:
    return {
        node.get("id"): node
        for node in root.iter()
        if isinstance(node.tag, str) and node.get("id")
    }


def _clip_circle_geometry(root: etree._Element, group: etree._Element) -> tuple[float, float, float] | None:
    ref = _own_url_ref(group, "clip-path")
    if not ref:
        return None
    target = _id_lookup(root).get(ref)
    if target is None or _local(target) != "clipPath":
        return None
    circles = _descendants(target, "circle")
    if not circles:
        return None
    try:
        return _circle_geometry(circles[0])
    except ReconstructionError:
        return None


def _document_order(root: etree._Element) -> dict[int, int]:
    return {id(node): index for index, node in enumerate(root.iter()) if isinstance(node.tag, str)}


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ReconstructionError("cannot take median of empty sequence")
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _representative_circle_geometry(group: etree._Element) -> tuple[float, float, float] | None:
    geometries: list[tuple[float, float, float]] = []
    for circle in _descendants(group, "circle"):
        try:
            geometries.append(_circle_geometry(circle))
        except ReconstructionError:
            continue
    if not geometries:
        return None
    return (
        _median([value[0] for value in geometries]),
        _median([value[1] for value in geometries]),
        _median([value[2] for value in geometries]),
    )


def _common_group_ancestor(elements: list[etree._Element]) -> etree._Element | None:
    if not elements:
        return None
    chains: list[list[etree._Element]] = []
    for element in elements:
        chain = [
            ancestor
            for ancestor in element.iterancestors()
            if isinstance(ancestor.tag, str) and _local(ancestor) == "g"
        ]
        chain.reverse()
        chains.append(chain)
    common: etree._Element | None = None
    for candidates in zip(*chains):
        first = candidates[0]
        if all(candidate is first for candidate in candidates[1:]):
            common = first
        else:
            break
    return common


def _branch_under(ancestor: etree._Element, element: etree._Element) -> etree._Element:
    current = element
    while current.getparent() is not ancestor:
        parent = current.getparent()
        if parent is None:
            raise ReconstructionError("scaffold candidate is not under its computed common ancestor")
        current = parent
    return current


def scaffold_diagnostics(root: etree._Element) -> dict[str, Any]:
    groups = [
        node for node in root.xpath(".//s:g", namespaces=scan.NS)
        if not _is_in_defs(node)
    ]
    multiply = [
        {
            "id": node.get("id"),
            "circles": _geometry_count(node, "circle"),
            "geometry": _representative_circle_geometry(node),
        }
        for node in groups
        if _style_contains(node, "mix-blend-mode:multiply")
    ]
    masked = [
        {
            "id": node.get("id"),
            "mask": _own_url_ref(node, "mask"),
            "circles": _geometry_count(node, "circle"),
            "geometry": _representative_circle_geometry(node),
        }
        for node in groups
        if _own_url_ref(node, "mask")
    ]
    clipped = [
        {
            "id": node.get("id"),
            "clip": _own_url_ref(node, "clip-path"),
            "stripe_geometry": _stripe_geometry_count(node),
            "clip_geometry": _clip_circle_geometry(root, node),
            "style": node.get("style"),
        }
        for node in groups
        if _own_url_ref(node, "clip-path")
    ]
    return {
        "body_group_count": len(groups),
        "multiply_groups": multiply,
        "masked_groups": masked,
        "clipped_groups": clipped,
        "body_circles": sum(
            1 for node in root.xpath(".//s:circle", namespaces=scan.NS) if not _is_in_defs(node)
        ),
        "body_paths": sum(
            1 for node in root.xpath(".//s:path", namespaces=scan.NS) if not _is_in_defs(node)
        ),
        "body_polygons": sum(
            1 for node in root.xpath(".//s:polygon", namespaces=scan.NS) if not _is_in_defs(node)
        ),
        "body_rects": sum(
            1 for node in root.xpath(".//s:rect", namespaces=scan.NS) if not _is_in_defs(node)
        ),
    }


def _relationship_scaffolds(root: etree._Element) -> list[dict[str, Any]]:
    groups = [
        node for node in root.xpath(".//s:g", namespaces=scan.NS)
        if not _is_in_defs(node)
    ]
    order = _document_order(root)
    clipped = [
        node for node in groups
        if _own_url_ref(node, "clip-path") and _stripe_geometry_count(node) >= 15
    ]
    masked = [
        node for node in groups
        if _own_url_ref(node, "mask") and _geometry_count(node, "circle") >= 1
    ]
    multiply_groups = [
        node for node in groups
        if _style_contains(node, "mix-blend-mode:multiply") and _geometry_count(node, "circle") >= 20
    ]
    body_circles = [
        node for node in root.xpath(".//s:circle", namespaces=scan.NS)
        if not _is_in_defs(node)
    ]

    matches: list[dict[str, Any]] = []
    for multiply in multiply_groups:
        stack_geometry = _representative_circle_geometry(multiply)
        if stack_geometry is None:
            continue
        stack_cx, stack_cy, stack_r = stack_geometry

        ring_options: list[tuple[etree._Element, etree._Element, tuple[float, float, float]]] = []
        for group in masked:
            for circle in _descendants(group, "circle"):
                try:
                    geometry = _circle_geometry(circle)
                except ReconstructionError:
                    continue
                cx, cy, radius = geometry
                if radius > stack_r + 1.0 and _near(cx, stack_cx, 0.5) and _near(cy, stack_cy, 0.5):
                    ring_options.append((group, circle, geometry))

        outer_options: list[tuple[etree._Element, tuple[float, float, float]]] = []
        inner_stripe_options: list[tuple[etree._Element, tuple[float, float, float]]] = []
        for group in clipped:
            geometry = _clip_circle_geometry(root, group)
            if geometry is None:
                continue
            cx, cy, radius = geometry
            if not (_near(cx, stack_cx, 0.5) and _near(cy, stack_cy, 0.5)):
                continue
            if radius > stack_r + 1.0:
                outer_options.append((group, geometry))
            elif _near(radius, stack_r, 0.5):
                inner_stripe_options.append((group, geometry))

        inner_disc_options: list[tuple[etree._Element, tuple[float, float, float]]] = []
        multiply_ids = {id(node) for node in multiply.iter()}
        for circle in body_circles:
            if id(circle) in multiply_ids:
                continue
            try:
                geometry = _circle_geometry(circle)
            except ReconstructionError:
                continue
            cx, cy, radius = geometry
            if not (_near(cx, stack_cx, 0.5) and _near(cy, stack_cy, 0.5) and _near(radius, stack_r, 0.5)):
                continue
            fill_value = _resolved_property(circle, "fill") or ""
            if "url(#" not in fill_value.replace(" ", ""):
                continue
            inner_disc_options.append((circle, geometry))

        if not (ring_options and outer_options and inner_stripe_options and inner_disc_options):
            continue

        ring_options.sort(key=lambda item: (item[2][2], _stripe_geometry_count(item[0])), reverse=True)
        outer_options.sort(key=lambda item: (_stripe_geometry_count(item[0]), item[1][2]), reverse=True)
        inner_stripe_options.sort(key=lambda item: (_stripe_geometry_count(item[0]), -abs(item[1][2] - stack_r)), reverse=True)
        inner_disc_options.sort(key=lambda item: order.get(id(item[0]), 10**9))

        ring_group, ring_disc, ring_geometry = ring_options[0]
        outer_stripes, _outer_geometry = outer_options[0]
        inner_stripes, _inner_clip_geometry = inner_stripe_options[0]
        after_stack = [item for item in inner_disc_options if order.get(id(item[0]), 0) > order.get(id(multiply), 0)]
        inner_disc, inner_geometry = (after_stack or inner_disc_options)[0]

        nodes = [outer_stripes, ring_group, multiply, inner_disc, inner_stripes]
        layer = _common_group_ancestor(nodes)
        if layer is None:
            continue
        branches = [_branch_under(layer, node) for node in nodes]
        branch_indexes = [layer.index(branch) for branch in branches]
        matches.append({
            "layer": layer,
            "outer": None,
            "outer_stripes": outer_stripes,
            "masked_ring": ring_group,
            "multiply_stack": multiply,
            "inner_disc": inner_disc,
            "inner_stripes": inner_stripes,
            "ring_disc": ring_disc,
            "inner_geometry": inner_geometry,
            "ring_geometry": ring_geometry,
            "removed_nodes": nodes,
            "insert_parent": layer,
            "insert_index": min(branch_indexes),
            "match_mode": "relationship",
        })
    return matches


def _candidate_sequence(children: list[etree._Element], index: int) -> bool:
    if index + 5 >= len(children):
        return False
    outer, outer_stripes, masked_ring, multiply_stack, inner_disc, inner_stripes = children[index : index + 6]
    if _local(outer) not in {"path", "circle", "ellipse", "polygon"}:
        return False
    if _local(outer_stripes) != "g" or not _own_url_ref(outer_stripes, "clip-path"):
        return False
    if _stripe_geometry_count(outer_stripes) < 20:
        return False
    if _local(masked_ring) != "g" or not _own_url_ref(masked_ring, "mask"):
        return False
    if _geometry_count(masked_ring, "circle") < 1:
        return False
    if _local(multiply_stack) != "g" or not _style_contains(multiply_stack, "mix-blend-mode:multiply"):
        return False
    if _geometry_count(multiply_stack, "circle") < 20:
        return False
    if _local(inner_disc) != "circle":
        return False
    if _local(inner_stripes) != "g" or not _own_url_ref(inner_stripes, "clip-path"):
        return False
    if _stripe_geometry_count(inner_stripes) < 20:
        return False
    return True


def find_gradient_mask_scaffold(root: etree._Element) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for group in root.xpath(".//s:g", namespaces=scan.NS):
        children = _direct_graphic_children(group)
        for index in range(max(0, len(children) - 5)):
            if not _candidate_sequence(children, index):
                continue
            outer, outer_stripes, masked_ring, multiply_stack, inner_disc, inner_stripes = children[index : index + 6]
            ring_circles = _descendants(masked_ring, "circle")
            if not ring_circles:
                continue
            ring_disc = ring_circles[0]
            try:
                inner_cx, inner_cy, inner_r = _circle_geometry(inner_disc)
                ring_cx, ring_cy, ring_r = _circle_geometry(ring_disc)
            except ReconstructionError:
                continue
            if ring_r <= inner_r or not (_near(inner_cx, ring_cx) and _near(inner_cy, ring_cy)):
                continue
            matches.append(
                {
                    "layer": group,
                    "children": children,
                    "index": index,
                    "outer": outer,
                    "outer_stripes": outer_stripes,
                    "masked_ring": masked_ring,
                    "multiply_stack": multiply_stack,
                    "inner_disc": inner_disc,
                    "inner_stripes": inner_stripes,
                    "ring_disc": ring_disc,
                    "inner_geometry": (inner_cx, inner_cy, inner_r),
                    "ring_geometry": (ring_cx, ring_cy, ring_r),
                    "removed_nodes": [outer_stripes, masked_ring, multiply_stack, inner_disc, inner_stripes],
                    "insert_parent": group,
                    "insert_index": group.index(outer_stripes),
                    "match_mode": "sequence",
                }
            )
    if not matches:
        matches = _relationship_scaffolds(root)
    # Deduplicate equivalent matches that identify the same five source nodes.
    unique: dict[tuple[int, ...], dict[str, Any]] = {}
    for match in matches:
        key = tuple(sorted(id(node) for node in match["removed_nodes"]))
        unique[key] = match
    matches = list(unique.values())
    if not matches:
        diagnostics = scaffold_diagnostics(root)
        raise ReconstructionError(
            "no compatible Guijia-style gradient/mask scaffold found; diagnostics="
            + json.dumps(diagnostics, separators=(",", ":"))
        )
    if len(matches) != 1:
        raise ReconstructionError(f"expected one compatible scaffold, found {len(matches)}")
    return matches[0]

def _dominant_gradient_palette(root: etree._Element) -> tuple[tuple[str | None, str | None, str | None, str | None], ...]:
    gradients = {
        gradient.get("id"): gradient
        for gradient in root.xpath(".//s:linearGradient", namespaces=scan.NS)
        if gradient.get("id")
    }
    palettes = [scan.resolve_gradient_stops(gradients, gradient_id) for gradient_id in gradients]
    counts = Counter(palette for palette in palettes if palette)
    if not counts:
        raise ReconstructionError("no non-empty linear-gradient palette could be resolved")
    palette, _count = counts.most_common(1)[0]
    if len(palette) != 2:
        raise ReconstructionError(f"expected dominant two-stop palette, found {len(palette)} stops")
    if any(stop[1] is None for stop in palette):
        raise ReconstructionError("dominant palette does not expose explicit stop-color values")
    return palette


def _ensure_defs(root: etree._Element) -> etree._Element:
    defs = root.find(f"{{{scan.SVG}}}defs")
    if defs is None:
        defs = etree.Element(f"{{{scan.SVG}}}defs")
        root.insert(0, defs)
    return defs


def _unique_id(root: etree._Element, prefix: str) -> str:
    existing = {node.get("id") for node in root.iter() if isinstance(node.tag, str) and node.get("id")}
    if prefix not in existing:
        return prefix
    index = 2
    while f"{prefix}-{index}" in existing:
        index += 1
    return f"{prefix}-{index}"


def _make_linear_gradient(
    root: etree._Element,
    *,
    prefix: str,
    center_x: float,
    center_y: float,
    radius: float,
    coordinates: dict[str, float],
    stops: list[tuple[str, str, str | None]],
) -> tuple[str, etree._Element]:
    gradient_id = _unique_id(root, prefix)
    gradient = etree.Element(f"{{{scan.SVG}}}linearGradient")
    gradient.set("id", gradient_id)
    gradient.set("gradientUnits", "userSpaceOnUse")
    for key in ("x1", "y1", "x2", "y2"):
        axis = "x" if key.startswith("x") else "y"
        center = center_x if axis == "x" else center_y
        gradient.set(key, _format_number(center + coordinates[key] * radius))
    for offset, color, opacity in stops:
        stop = etree.SubElement(gradient, f"{{{scan.SVG}}}stop")
        stop.set("offset", offset)
        stop.set("stop-color", color)
        if opacity is not None:
            stop.set("stop-opacity", opacity)
    return gradient_id, gradient


def _palette_colors(
    palette: tuple[tuple[str | None, str | None, str | None, str | None], ...],
) -> tuple[str, str]:
    if len(palette) != 2 or palette[0][1] is None or palette[1][1] is None:
        raise ReconstructionError("expected a resolved two-stop accent palette")
    return palette[0][1], palette[1][1]


def _used_classes_outside_defs(root: etree._Element) -> set[str]:
    classes: set[str] = set()
    defs = root.find(f"{{{scan.SVG}}}defs")
    for child in root:
        if child is defs:
            continue
        for node in child.iter():
            if not isinstance(node.tag, str):
                continue
            classes.update((node.get("class") or "").split())
    return classes


def prune_unused_class_rules_outside_defs(root: etree._Element) -> dict[str, int]:
    used = _used_classes_outside_defs(root)
    removed_rules = 0
    removed_bytes = 0
    rule_re = re.compile(r"\.([A-Za-z_][\w-]*)\s*\{[^}]*\}", re.S)
    for style in root.xpath(".//s:style", namespaces=scan.NS):
        text = style.text or ""
        pieces: list[str] = []
        last = 0
        for match in rule_re.finditer(text):
            pieces.append(text[last:match.start()])
            if match.group(1) in used:
                pieces.append(match.group(0))
            else:
                removed_rules += 1
                removed_bytes += len(match.group(0).encode("utf-8"))
            last = match.end()
        pieces.append(text[last:])
        style.text = "".join(pieces)
    return {
        "removed_css_rules": removed_rules,
        "removed_css_bytes_estimate": removed_bytes,
    }


def _referenced_ids_outside_defs(root: etree._Element) -> set[str]:
    refs: set[str] = set()
    defs = root.find(f"{{{scan.SVG}}}defs")
    for child in root:
        if child is defs:
            continue
        refs.update(_url_refs_from_element(child))
    # After unused class rules have been pruned, any remaining CSS url(#id)
    # references are live even when the corresponding property is class-based.
    for style in root.xpath(".//s:style", namespaces=scan.NS):
        if style.text:
            refs.update(URL_REF_RE.findall(style.text))
    return refs


def _id_element_map(root: etree._Element) -> dict[str, etree._Element]:
    return {
        node.get("id"): node
        for node in root.xpath(".//s:defs//*[@id]", namespaces=scan.NS)
        if node.get("id")
    }


def prune_unreferenced_defs(root: etree._Element) -> dict[str, int]:
    defs = root.find(f"{{{scan.SVG}}}defs")
    if defs is None:
        return {"removed_defs_elements": 0, "removed_defs_bytes_estimate": 0}

    by_id = _id_element_map(root)
    keep = _referenced_ids_outside_defs(root)
    queue = list(keep)
    while queue:
        current = queue.pop()
        element = by_id.get(current)
        if element is None:
            continue
        for ref in _url_refs_from_element(element):
            if ref not in keep:
                keep.add(ref)
                queue.append(ref)

    removed = 0
    removed_bytes = 0
    # Guijia-family exporter objects are top-level children of <defs>. Keep styles
    # and anonymous containers; remove only id-bearing top-level definitions proven
    # unreachable from the rebuilt body.
    for child in list(defs):
        if not isinstance(child.tag, str):
            continue
        child_id = child.get("id")
        if child_id is None or child_id in keep:
            continue
        removed += 1
        removed_bytes += len(etree.tostring(child, encoding="utf-8"))
        defs.remove(child)
    return {"removed_defs_elements": removed, "removed_defs_bytes_estimate": removed_bytes}


def _refs_outside_removed(root: etree._Element, removed_nodes: list[etree._Element]) -> set[str]:
    excluded = {id(node) for root_node in removed_nodes for node in root_node.iter()}
    refs: set[str] = set()
    for child in root:
        if isinstance(child.tag, str) and _local(child) == "defs":
            continue
        for node in child.iter():
            if id(node) in excluded or not isinstance(node.tag, str):
                continue
            for value in node.attrib.values():
                refs.update(URL_REF_RE.findall(value))
                if value.startswith("#"):
                    refs.add(value[1:])
            if _local(node) == "style" and node.text:
                refs.update(URL_REF_RE.findall(node.text))
    return refs


def _remove_nodes(nodes: list[etree._Element]) -> int:
    unique: list[etree._Element] = []
    seen: set[int] = set()
    for node in nodes:
        if id(node) not in seen:
            unique.append(node)
            seen.add(id(node))
    # Remove deepest nodes first so nested wrappers cannot invalidate children.
    unique.sort(key=lambda node: sum(1 for _ in node.iterancestors()), reverse=True)
    removed = 0
    for node in unique:
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)
            removed += 1
    return removed


def reconstruct_tree(tree: etree._ElementTree) -> dict[str, Any]:
    root = tree.getroot()
    scaffold = find_gradient_mask_scaffold(root)
    palette = _dominant_gradient_palette(root)
    accent_light, accent_dark = _palette_colors(palette)

    removed_nodes: list[etree._Element] = scaffold["removed_nodes"]
    removed_ids = set().union(*(_ids_in(child) for child in removed_nodes))
    remaining_refs = _refs_outside_removed(root, removed_nodes)
    dangling = sorted(removed_ids & remaining_refs)
    if dangling:
        raise ReconstructionError(
            "remaining artwork references ids defined inside the scaffold slated for removal: "
            + ", ".join(dangling)
        )

    inner_cx, inner_cy, inner_r = scaffold["inner_geometry"]
    gray_cx, gray_cy, gray_r = scaffold["ring_geometry"]
    defs = _ensure_defs(root)

    gray_id, gray_gradient = _make_linear_gradient(
        root,
        prefix="svg-research-gray",
        center_x=gray_cx,
        center_y=gray_cy,
        radius=gray_r,
        coordinates=GRAY_GRADIENT_RELATIVE,
        stops=[("0", GRAY_DARK, None), ("1", GRAY_LIGHT, None)],
    )
    accent_base_id, accent_base = _make_linear_gradient(
        root,
        prefix="svg-research-accent-base",
        center_x=inner_cx,
        center_y=inner_cy,
        radius=inner_r,
        coordinates=ACCENT_BASE_RELATIVE,
        stops=[("0", accent_light, None), ("1", accent_dark, None)],
    )
    accent_highlight_id, accent_highlight = _make_linear_gradient(
        root,
        prefix="svg-research-accent-highlight",
        center_x=inner_cx,
        center_y=inner_cy,
        radius=inner_r,
        coordinates=ACCENT_HIGHLIGHT_RELATIVE,
        stops=[
            ("0", accent_light, _format_number(ACCENT_HIGHLIGHT_START_OPACITY)),
            ("1", accent_light, "0"),
        ],
    )
    defs.extend((gray_gradient, accent_base, accent_highlight))

    gray = etree.Element(f"{{{scan.SVG}}}circle")
    gray.set("cx", _format_number(gray_cx))
    gray.set("cy", _format_number(gray_cy))
    gray.set("r", _format_number(gray_r))
    gray.set("fill", f"url(#{gray_id})")
    gray.set("data-svg-research", "reconstructed-gray-disc")

    accent_group = etree.Element(f"{{{scan.SVG}}}g")
    accent_group.set("data-svg-research", "reconstructed-accent-disc")
    accent_base_circle = etree.SubElement(accent_group, f"{{{scan.SVG}}}circle")
    accent_base_circle.set("cx", _format_number(inner_cx))
    accent_base_circle.set("cy", _format_number(inner_cy))
    accent_base_circle.set("r", _format_number(inner_r))
    accent_base_circle.set("fill", f"url(#{accent_base_id})")
    accent_highlight_circle = etree.SubElement(accent_group, f"{{{scan.SVG}}}circle")
    accent_highlight_circle.set("cx", _format_number(inner_cx))
    accent_highlight_circle.set("cy", _format_number(inner_cy))
    accent_highlight_circle.set("r", _format_number(inner_r))
    accent_highlight_circle.set("fill", f"url(#{accent_highlight_id})")

    insert_parent: etree._Element = scaffold["insert_parent"]
    insert_at: int = scaffold["insert_index"]
    insert_parent.insert(insert_at, gray)
    insert_parent.insert(insert_at + 1, accent_group)
    removed_count = _remove_nodes(removed_nodes)

    css_stats = prune_unused_class_rules_outside_defs(root)
    defs_stats = prune_unreferenced_defs(root)

    palette_summary = [
        {"offset": offset, "color": color, "opacity": opacity, "style": style}
        for offset, color, opacity, style in palette
    ]
    return {
        "match_mode": scaffold.get("match_mode", "unknown"),
        "pattern_index": scaffold.get("index"),
        "outer_stripe_paths_removed": _geometry_count(scaffold["outer_stripes"], "path"),
        "inner_stripe_paths_removed": _geometry_count(scaffold["inner_stripes"], "path"),
        "outer_stripe_geometry_removed": _stripe_geometry_count(scaffold["outer_stripes"]),
        "inner_stripe_geometry_removed": _stripe_geometry_count(scaffold["inner_stripes"]),
        "multiply_circles_removed": _geometry_count(scaffold["multiply_stack"], "circle"),
        "mask_group_circles_removed": _geometry_count(scaffold["masked_ring"], "circle"),
        "removed_scaffold_nodes": removed_count,
        "inner_geometry": {"cx": inner_cx, "cy": inner_cy, "r": inner_r},
        "gray_geometry": {"cx": gray_cx, "cy": gray_cy, "r": gray_r},
        "gradient_count": 3,
        "gray_gradient": {
            "id": gray_id,
            "colors": [GRAY_DARK, GRAY_LIGHT],
            "coordinates": {key: gray_gradient.get(key) for key in ("x1", "y1", "x2", "y2")},
        },
        "accent_base_gradient": {
            "id": accent_base_id,
            "colors": [accent_light, accent_dark],
            "coordinates": {key: accent_base.get(key) for key in ("x1", "y1", "x2", "y2")},
        },
        "accent_highlight_gradient": {
            "id": accent_highlight_id,
            "color": accent_light,
            "start_opacity": ACCENT_HIGHLIGHT_START_OPACITY,
            "coordinates": {key: accent_highlight.get(key) for key in ("x1", "y1", "x2", "y2")},
        },
        "dominant_palette": palette_summary,
        "css_pruning": css_stats,
        "defs_pruning": defs_stats,
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


def _scan_summary(path: Path) -> dict[str, Any]:
    report = _scan_source(path)
    return {
        "classification": report.classification,
        "severity": report.severity,
        "size_bytes": report.size_bytes,
        "linear_gradients": report.linear_gradients,
        "masks": report.masks,
        "filters": report.filters,
        "clip_paths": report.clip_paths,
        "embedded_images": report.embedded_images,
        "circles": report.circles,
        "paths": report.paths,
        "advisories": list(report.advisories),
        "signals": list(report.signals),
    }


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


def _scour_svg(source: Path, destination: Path) -> dict[str, Any]:
    optimized = scour_module.scourString(source.read_text(encoding="utf-8"), scour_module.sanitizeOptions())
    destination.write_text(optimized, encoding="utf-8")
    return {"bytes_before": source.stat().st_size, "bytes_after": destination.stat().st_size}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Experimental Guijia-family reconstruction: replace the flattened gradient/mask "
            "scaffold with one gray gradient and two differently angled accent gradients. "
            "Outputs always require render review."
        )
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("gradient-mask-reconstruction"))
    parser.add_argument("--sizes", type=render_compare.parse_sizes, default=DEFAULT_SIZES)
    parser.add_argument("--inkscape")
    parser.add_argument("--scour", action="store_true", help="run standard Scour after structural reconstruction")
    parser.add_argument("--no-render", action="store_true", help="write the candidate without invoking Inkscape")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="print structural matcher diagnostics before reconstruction",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow experimentation on a source not classified as flattened-gradient-mask",
    )
    args = parser.parse_args()

    source = args.source.resolve()
    if not source.is_file():
        parser.error(f"source does not exist: {args.source}")
    report = _scan_source(source)
    if report.classification != "flattened-gradient-mask" and not args.force:
        parser.error(
            f"source classification is {report.classification!r}, not 'flattened-gradient-mask'; "
            "use --force for an explicit experiment"
        )

    tree = _parse_svg(source)
    if args.diagnose:
        print(json.dumps({"scaffold_diagnostics": scaffold_diagnostics(tree.getroot())}, indent=2))
    try:
        reconstruction = reconstruct_tree(tree)
    except ReconstructionError as exc:
        parser.error(str(exc))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    reconstructed = args.output_dir / f"{source.stem}.gradient-mask-reconstructed.svg"
    tree.write(str(reconstructed), encoding="UTF-8", xml_declaration=True, pretty_print=False)
    candidate = reconstructed
    stages: dict[str, Any] = {"reconstructed": {"path": str(reconstructed), "bytes": reconstructed.stat().st_size}}
    if args.scour:
        scoured = args.output_dir / f"{source.stem}.gradient-mask-reconstructed.scour.svg"
        stages["scoured"] = _scour_svg(reconstructed, scoured)
        stages["scoured"]["path"] = str(scoured)
        candidate = scoured

    payload: dict[str, Any] = {
        "schema_version": 1,
        "experiment": "gradient-mask-reconstruction",
        "verdict": "experimental-review-required",
        "automatic_acceptance": False,
        "source": str(source),
        "candidate": str(candidate),
        "source_classification": report.classification,
        "source_size_bytes": source.stat().st_size,
        "candidate_size_bytes": candidate.stat().st_size,
        "byte_reduction_fraction": 1.0 - candidate.stat().st_size / source.stat().st_size,
        "historical_basis": {
            "gray_gradient": "refit-from-raw-guijia-render",
            "accent_base_gradient": "recovered-from-prior-two-gradient-experiment",
            "accent_highlight_gradient": "refit-to-reproduce-prior-two-gradient-result",
            "guijia_accent_background_fit_rgb_rmse_1024": 3.3886,
            "canonical_mode": "three-gradient-total",
        },
        "reconstruction": reconstruction,
        "stages": stages,
        "candidate_scan": _scan_summary(candidate),
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
