from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from lxml import etree

from . import scan


@dataclass
class TransformResult:
    name: str
    changed: bool
    exact_expected: bool
    stats: dict[str, Any]


def _parse_svg(path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        recover=False,
        huge_tree=True,
        remove_blank_text=False,
    )
    return etree.parse(str(path), parser)


def _style_dict(element: etree._Element) -> dict[str, str]:
    return scan.parse_style_declarations(element.get("style"))


def _set_inline_style_property(element: etree._Element, key: str, value: str) -> None:
    declarations = _style_dict(element)
    declarations[key] = value
    element.set("style", ";".join(f"{name}:{declarations[name]}" for name in sorted(declarations)))


def _rgb_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{value:02x}" for value in rgb)


def _is_simple_single_path_group(group: etree._Element, path: etree._Element) -> bool:
    if scan.local_name(group) != "g":
        return False
    meaningful = [
        child
        for child in group
        if isinstance(child.tag, str) and scan.local_name(child) not in scan.NONRENDERING_TAGS
    ]
    return meaningful == [path]


def _document_order_key(element: etree._Element) -> tuple[int, ...]:
    indexes: list[int] = []
    node = element
    while node.getparent() is not None:
        parent = node.getparent()
        indexes.append(parent.index(node))
        node = parent
    return tuple(reversed(indexes))


def merge_duplicate_fill_stroke(tree: etree._ElementTree) -> TransformResult:
    """Merge conservative Illustrator fill+stroke duplicate pairs.

    This exact transform intentionally handles only the pattern proven by Trinitarians:
    two adjacent sibling groups, each containing one path with identical geometry and
    cumulative transform; the first is an opaque fill-only path and the second is an
    opaque stroke-only path of the same colour. The stroke path survives and receives
    the fill as an inline style, preserving SVG fill-before-stroke paint order.
    """
    root = tree.getroot()
    class_styles = scan.parse_class_styles(root)
    candidates: dict[
        tuple[str, tuple[float, ...], tuple[int, int, int]],
        dict[str, list[etree._Element]],
    ] = defaultdict(lambda: {"fill": [], "stroke": []})

    for path in root.xpath(".//s:path", namespaces=scan.NS):
        path_data = path.get("d") or ""
        if not path_data:
            continue
        matrix = scan.normalized_matrix(scan.cumulative_transform(path))
        if matrix is None:
            continue
        props = scan.effective_paint_properties(path, class_styles)
        fill_text = (props.get("fill") or "black").strip().lower()
        stroke_text = (props.get("stroke") or "none").strip().lower()
        fill = scan.parse_css_rgb(fill_text)
        stroke = scan.parse_css_rgb(stroke_text)
        opacity = (props.get("opacity") or "1").strip()
        fill_opacity = (props.get("fill-opacity") or "1").strip()
        stroke_opacity = (props.get("stroke-opacity") or "1").strip()
        if opacity not in {"1", "1.0", "1.00"}:
            continue
        if fill is not None and stroke is None and fill_opacity in {"1", "1.0", "1.00"}:
            candidates[(path_data, matrix, fill)]["fill"].append(path)
        elif fill_text == "none" and stroke is not None and stroke_opacity in {"1", "1.0", "1.00"}:
            candidates[(path_data, matrix, stroke)]["stroke"].append(path)

    # Keep the optimizer aligned with the scanner classification contract.  A few
    # isolated fill/stroke duplicates can occur incidentally and are not evidence of
    # the systematic Illustrator export pathology this transform is intended to fix.
    # v7 classifies duplicate-fill-stroke-geometry only at >=8 pairs and >=4 KiB
    # duplicated path data; do not opportunistically rewrite weaker signals.
    systematic_min_pairs = 8
    systematic_min_path_bytes = 4_000
    potential_pairs = sum(
        min(len(group["fill"]), len(group["stroke"])) for group in candidates.values()
    )
    potential_path_bytes = sum(
        len(path_data.encode("utf-8")) * min(len(group["fill"]), len(group["stroke"]))
        for (path_data, _matrix, _color), group in candidates.items()
    )
    if (
        potential_pairs < systematic_min_pairs
        or potential_path_bytes < systematic_min_path_bytes
    ):
        return TransformResult(
            name="duplicate-fill-stroke-geometry",
            changed=False,
            exact_expected=True,
            stats={
                "potential_pairs": potential_pairs,
                "potential_path_data_bytes": potential_path_bytes,
                "systematic_min_pairs": systematic_min_pairs,
                "systematic_min_path_data_bytes": systematic_min_path_bytes,
                "skipped_below_systematic_threshold": potential_pairs > 0,
                "merged_pairs": 0,
                "duplicated_path_data_bytes_removed": 0,
                "rejected_nonadjacent_pairs": 0,
                "rejected_container_pairs": 0,
            },
        )

    merged = 0
    duplicated_path_bytes = 0
    rejected_nonadjacent = 0
    rejected_container = 0

    for (path_data, _matrix, color), group in candidates.items():
        fills = sorted(group["fill"], key=_document_order_key)
        strokes = sorted(group["stroke"], key=_document_order_key)
        used_strokes: set[int] = set()
        for fill_path in fills:
            fill_parent = fill_path.getparent()
            if fill_parent is None or not _is_simple_single_path_group(fill_parent, fill_path):
                rejected_container += 1
                continue

            match_index: int | None = None
            for index, stroke_path in enumerate(strokes):
                if index in used_strokes:
                    continue
                stroke_parent = stroke_path.getparent()
                if stroke_parent is None or not _is_simple_single_path_group(stroke_parent, stroke_path):
                    continue
                common_parent = fill_parent.getparent()
                if common_parent is None or stroke_parent.getparent() is not common_parent:
                    continue
                fill_index = common_parent.index(fill_parent)
                stroke_index = common_parent.index(stroke_parent)
                if stroke_index != fill_index + 1:
                    continue
                match_index = index
                break

            if match_index is None:
                rejected_nonadjacent += 1
                continue

            stroke_path = strokes[match_index]
            stroke_parent = stroke_path.getparent()
            assert stroke_parent is not None
            common_parent = fill_parent.getparent()
            assert common_parent is not None

            _set_inline_style_property(stroke_path, "fill", _rgb_hex(color))
            common_parent.remove(fill_parent)
            used_strokes.add(match_index)
            merged += 1
            duplicated_path_bytes += len(path_data.encode("utf-8"))

    return TransformResult(
        name="duplicate-fill-stroke-geometry",
        changed=merged > 0,
        exact_expected=True,
        stats={
            "potential_pairs": potential_pairs,
            "potential_path_data_bytes": potential_path_bytes,
            "systematic_min_pairs": systematic_min_pairs,
            "systematic_min_path_data_bytes": systematic_min_path_bytes,
            "skipped_below_systematic_threshold": False,
            "merged_pairs": merged,
            "duplicated_path_data_bytes_removed": duplicated_path_bytes,
            "rejected_nonadjacent_pairs": rejected_nonadjacent,
            "rejected_container_pairs": rejected_container,
        },
    )


def _top_level_child(root: etree._Element, element: etree._Element) -> etree._Element | None:
    node = element
    while node.getparent() is not None and node.getparent() is not root:
        node = node.getparent()
    return node if node.getparent() is root else None


def _is_identity_matrix(matrix: scan.Matrix | None) -> bool:
    return matrix is not None and all(
        abs(left - right) <= 1e-12
        for left, right in zip(matrix, scan.IDENTITY_MATRIX)
    )


def remove_off_artboard_top_level(tree: etree._ElementTree) -> TransformResult:
    """Remove top-level graphic branches provably disjoint from the SVG viewBox.

    A candidate branch is retained if an on-document reference could reuse one of its
    IDs in a different position. One conservative exception is a top-level untransformed
    `<text>` whose `<textPath>` points at an off-artboard top-level path: that text follows
    the same off-artboard geometry and is removed with its path. This handles the exact
    Illustrator duplication pattern present in Oktavia without leaving broken hrefs.
    """
    root = tree.getroot()
    viewport = scan.parse_viewbox_bounds(root)
    if viewport is None:
        return TransformResult(
            name="off-artboard-content",
            changed=False,
            exact_expected=True,
            stats={"reason": "no analyzable viewBox"},
        )

    raw_candidates: list[tuple[etree._Element, int]] = []
    analysis_errors = 0
    for child in list(root):
        name = scan.local_name(child)
        if not name or name in scan.NONRENDERING_TAGS:
            continue
        try:
            bounds, complete = scan.graphic_branch_bounds(child)
        except (ValueError, OverflowError):
            analysis_errors += 1
            continue
        if not complete or bounds is None or scan.bounds_intersect(bounds, viewport):
            continue
        raw_candidates.append((child, len(etree.tostring(child, encoding="utf-8"))))

    candidate_set = {child for child, _size in raw_candidates}
    id_owner: dict[str, etree._Element] = {}
    id_element: dict[str, etree._Element] = {}
    for child, _size in raw_candidates:
        for element in child.iter():
            if not isinstance(element.tag, str):
                continue
            element_id = element.get("id")
            if element_id:
                id_owner[element_id] = child
                id_element[element_id] = element

    protected: set[etree._Element] = set()
    dependent_text: set[etree._Element] = set()
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        top = _top_level_child(root, element)
        if top is None or top in candidate_set:
            continue
        href = element.get(f"{{{scan.XLINK}}}href") or element.get("href") or ""
        if not href.startswith("#"):
            continue
        target_id = href[1:]
        owner = id_owner.get(target_id)
        if owner is None:
            continue

        target = id_element[target_id]
        if (
            scan.local_name(element) == "textPath"
            and scan.local_name(top) == "text"
            and scan.local_name(target) == "path"
            and owner is target
            and _is_identity_matrix(scan.cumulative_transform(top))
        ):
            dependent_text.add(top)
        else:
            protected.add(owner)

    removable = [(child, size) for child, size in raw_candidates if child not in protected]

    removed_bytes = 0
    external_images = 0
    removed_tags: dict[str, int] = defaultdict(int)
    for child, serialized_bytes in removable:
        removed_bytes += serialized_bytes
        removed_tags[scan.local_name(child) or "unknown"] += 1
        external_images += len(
            [
                image
                for image in child.xpath(".//s:image | self::s:image", namespaces=scan.NS)
                if (image.get(f"{{{scan.XLINK}}}href") or image.get("href") or "")
                and not (image.get(f"{{{scan.XLINK}}}href") or image.get("href") or "").startswith("data:")
            ]
        )
        root.remove(child)

    # Remove only text nodes whose referenced path was actually removed.
    removed_ids = {
        element.get("id")
        for child, _size in removable
        for element in child.iter()
        if isinstance(element.tag, str) and element.get("id")
    }
    dependent_removed = 0
    for text in sorted(dependent_text, key=_document_order_key, reverse=True):
        refs = {
            (node.get(f"{{{scan.XLINK}}}href") or node.get("href") or "")[1:]
            for node in text.xpath(".//s:textPath", namespaces=scan.NS)
            if (node.get(f"{{{scan.XLINK}}}href") or node.get("href") or "").startswith("#")
        }
        if refs and refs <= removed_ids and text.getparent() is root:
            removed_bytes += len(etree.tostring(text, encoding="utf-8"))
            removed_tags["text"] += 1
            root.remove(text)
            dependent_removed += 1

    return TransformResult(
        name="off-artboard-content",
        changed=bool(removable or dependent_removed),
        exact_expected=True,
        stats={
            "removed_top_level_branches": len(removable),
            "removed_dependent_text_paths": dependent_removed,
            "protected_referenced_branches": len(protected),
            "removed_serialized_bytes_estimate": removed_bytes,
            "removed_external_images": external_images,
            "removed_tags": dict(sorted(removed_tags.items())),
            "analysis_errors": analysis_errors,
        },
    )


def apply_exact_transforms(source: Path) -> tuple[etree._ElementTree, list[TransformResult]]:
    tree = _parse_svg(source)
    # Fixed deterministic order: first remove invisible branches, then consolidate
    # visible duplicate paint geometry.
    results = [
        remove_off_artboard_top_level(tree),
        merge_duplicate_fill_stroke(tree),
    ]
    return tree, results


def write_tree(tree: etree._ElementTree, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tree.write(
        str(destination),
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )


def result_dict(result: TransformResult) -> dict[str, Any]:
    return asdict(result)
