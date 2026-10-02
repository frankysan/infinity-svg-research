"""Normalize page metadata without rewriting SVG geometry.

Inkscape queries return CSS-pixel bounds, not viewBox coordinates. Convert through
the original viewport mapping before removing fixed root dimensions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path

from lxml import etree

ROOT_TAG = re.compile(rb"<svg\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>", re.DOTALL)
ATTRIBUTE = re.compile(rb"\s+([\w:-]+)\s*=\s*(\"[^\"]*\"|'[^']*')", re.DOTALL)
UNITS = {
    "": 1,
    "px": 1,
    "in": 96,
    "mm": 96 / 25.4,
    "cm": 96 / 2.54,
    "pt": 96 / 72,
    "pc": 16,
    "q": 96 / 101.6,
}


def parse_svg(data: bytes) -> etree._Element:
    root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
    if etree.QName(root).localname != "svg":
        raise ValueError("document root is not svg")
    return root


def replace_root_attributes(data: bytes, attributes: dict[str, str | None]) -> bytes:
    """Preserve every byte outside the attributes being changed."""
    comments = [(m.start(), m.end()) for m in re.finditer(rb"<!--.*?-->", data, re.DOTALL)]
    match = next(
        (
            m
            for m in ROOT_TAG.finditer(data)
            if not any(start <= m.start() < end for start, end in comments)
        ),
        None,
    )
    if match is None:
        raise ValueError("expected an unprefixed SVG root tag")
    pending = dict(attributes)

    def replace(attr: re.Match[bytes]) -> bytes:
        name = attr.group(1).decode("ascii")
        if name not in pending:
            return attr.group(0)
        value = pending.pop(name)
        if value is None:
            return b""
        return b" " + attr.group(1) + b'="' + value.encode("ascii") + b'"'

    tag = ATTRIBUTE.sub(replace, match.group())
    extra = b"".join(
        b" " + k.encode("ascii") + b'="' + v.encode("ascii") + b'"'
        for k, v in pending.items()
        if v is not None
    )
    tag = tag[:-1] + extra + b">"
    return data[: match.start()] + tag + data[match.end() :]


def css_length(value: str | None) -> float:
    match = re.fullmatch(r"\s*([+\-\d.eE]+)\s*([a-zA-Z]*)\s*", value or "")
    if not match or match[2].lower() not in UNITS:
        raise ValueError(f"unsupported physical dimension: {value!r}")
    number = float(match[1]) * UNITS[match[2].lower()]
    if not math.isfinite(number) or number <= 0:
        raise ValueError("physical dimensions must be positive and finite")
    return number


def pixels_to_user_bounds(root: etree._Element, bounds: list[float]) -> list[float]:
    x, y, w, h = map(float, root.get("viewBox", "").replace(",", " ").split())
    if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
        raise ValueError("invalid viewBox")
    width, height = css_length(root.get("width")), css_length(root.get("height"))
    sx, sy = width / w, height / h
    aspect = root.get("preserveAspectRatio", "xMidYMid meet").split()
    dx = dy = 0.0
    if aspect != ["none"]:
        if len(aspect) == 1:
            aspect.append("meet")
        if len(aspect) != 2 or aspect[1] not in {"meet", "slice"}:
            raise ValueError("unsupported preserveAspectRatio")
        align = re.fullmatch(r"x(Min|Mid|Max)Y(Min|Mid|Max)", aspect[0])
        if align is None:
            raise ValueError("unsupported viewport alignment")
        scale = min(sx, sy) if aspect[1] == "meet" else max(sx, sy)
        sx = sy = scale
        factor = {"Min": 0, "Mid": 0.5, "Max": 1}
        dx = (width - w * scale) * factor[align[1]]
        dy = (height - h * scale) * factor[align[2]]
    bx, by, bw, bh = bounds
    return [(bx - dx) / sx + x, (by - dy) / sy + y, bw / sx, bh / sy]


def blockers(root: etree._Element) -> list[str]:
    reasons = set()
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        name = etree.QName(element).localname
        if name in {"text", "flowRoot", "foreignObject", "script"}:
            reasons.add("font-dependent-text" if name in {"text", "flowRoot"} else name)
        if element is not root and name == "svg":
            reasons.add("nested-viewport")
        if any("%" in v for v in element.attrib.values()) or (
            name == "style" and "%" in (element.text or "")
        ):
            reasons.add("viewport-relative-percentage")
        for key, value in element.attrib.items():
            if etree.QName(key).localname == "href" and not value.startswith(("#", "data:")):
                reasons.add("external-reference")
    if root.get("transform"):
        reasons.add("root-transform")
    if re.search(r"(?:^|;)\s*(?:width|height)\s*:", root.get("style", ""), re.IGNORECASE):
        reasons.add("css-root-size")
    identifier = root.get("id")
    if identifier:
        # Query staging adds a unique root id; don't change a referenced CSS selector.
        reference = re.compile(r"#" + re.escape(identifier) + r"(?![\w-])")
        if any(reference.search(v) for el in root.iter() for v in el.attrib.values()) or any(
            isinstance(el.tag, str)
            and etree.QName(el).localname == "style"
            and reference.search(el.text or "")
            for el in root.iter()
        ):
            reasons.add("referenced-root-id")
    return sorted(reasons)


def query_bounds(paths: list[Path], *, inkscape: str, staging: Path) -> dict[Path, list[float]]:
    commands = []
    ids = {}
    for index, path in enumerate(paths):
        identifier = f"viewport_query_{index}"
        staged = staging / f"{index}.svg"
        staged.write_bytes(replace_root_attributes(path.read_bytes(), {"id": identifier}))
        location = str(staged.resolve()).replace("\\", "/")
        if any(c in location for c in ";\r\n"):
            raise ValueError("Inkscape action paths cannot contain semicolons or newlines")
        ids[identifier] = path
        commands.append(f"file-open:{location};query-all;file-close")
    result = subprocess.run(
        [inkscape, "--shell"],
        input="\n".join([*commands, "quit", ""]),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Inkscape query failed: {result.stderr[-2000:]}")
    queried = {}
    for line in result.stdout.splitlines():
        fields = line.strip().split(",")
        if len(fields) != 5 or fields[0] not in ids:
            continue
        values = list(map(float, fields[1:]))
        if all(math.isfinite(v) for v in values) and values[2] > 0 and values[3] > 0:
            queried[ids[fields[0]]] = values
    return queried


def normalize(
    data: bytes, pixel_bounds: list[float], *, padding: float = 0.005
) -> tuple[bytes, dict]:
    root = parse_svg(data)
    reasons = blockers(root)
    if reasons:
        raise ValueError(", ".join(reasons))
    if not math.isfinite(padding) or padding < 0:
        raise ValueError("padding must be nonnegative")
    if len(pixel_bounds) != 4 or not all(math.isfinite(v) for v in pixel_bounds):
        raise ValueError("invalid drawing bounds")
    if pixel_bounds[2] <= 0 or pixel_bounds[3] <= 0:
        raise ValueError("empty drawing bounds")
    x, y, w, h = pixels_to_user_bounds(root, pixel_bounds)
    # query-all rounds to six significant digits; include an outward allowance.
    allowance = max(abs(x), abs(y), w, h) * 0.00002
    pad = max(w, h) * padding + allowance
    box = [x - pad, y - pad, w + 2 * pad, h + 2 * pad]
    attrs = {
        "viewBox": " ".join(format(v, ".12g") for v in box),
        "width": None,
        "height": None,
        "preserveAspectRatio": "xMidYMid meet",
    }
    candidate = replace_root_attributes(data, attrs)
    # Metadata-only invariant: no children, styles, transforms, or root semantic attrs changed.
    restored = parse_svg(candidate)
    for key in attrs:
        if key in root.attrib:
            restored.set(key, root.get(key))
        else:
            restored.attrib.pop(key, None)
    if etree.tostring(restored, method="c14n") != etree.tostring(root, method="c14n"):
        raise RuntimeError("normalization changed non-viewport content")
    return candidate, {
        "old_viewport": {k: root.get(k) for k in attrs},
        "new_viewport": attrs,
        "drawing_bounds_user_units": [x, y, w, h],
        "bounds_method": "inkscape-drawing-bounds-css-pixels-to-user-units",
        "padding_ratio": padding,
        "rounding_allowance_user_units": allowance,
        "sizing": "responsive-viewBox-only",
        "intrinsic_aspect_ratio": box[2] / box[3],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--inkscape", default="inkscape")
    parser.add_argument("--padding", type=float, default=0.005)
    args = parser.parse_args(argv)
    source, output = args.source_root.resolve(), args.output_dir.resolve()
    if not source.is_dir():
        parser.error("source_root must be a directory")
    if output == source or source in output.parents or output in source.parents:
        parser.error("source and output directories must be separate")
    if not math.isfinite(args.padding) or args.padding < 0:
        parser.error("padding must be nonnegative")
    if output.exists() and any(output.iterdir()):
        parser.error("output directory must be empty (use a new run directory)")
    output.mkdir(parents=True, exist_ok=True)
    rows, eligible = [], []
    for path in sorted(source.rglob("*.svg")):
        data = path.read_bytes()
        row = {
            "path": path.relative_to(source).as_posix(),
            "source_sha256": hashlib.sha256(data).hexdigest(),
            "status": "pending",
        }
        try:
            root = parse_svg(data)
            reasons = blockers(root)
            pixels_to_user_bounds(root, [0, 0, 1, 1])
            if reasons:
                row.update(status="blocked", reasons=reasons)
            else:
                eligible.append(path)
        except (ValueError, etree.XMLSyntaxError) as exc:
            row.update(status="blocked", reasons=[str(exc)])
        rows.append(row)
    by_path = {row["path"]: row for row in rows}
    with tempfile.TemporaryDirectory(prefix="viewport-query-", dir=output) as directory:
        staging = Path(directory)
        for start in range(0, len(eligible), 100):
            batch = eligible[start : start + 100]
            queried = query_bounds(batch, inkscape=args.inkscape, staging=staging)
            for path in batch:
                row = by_path[path.relative_to(source).as_posix()]
                if path not in queried:
                    row.update(status="blocked", reasons=["missing-or-empty-drawing-bounds"])
                    continue
                candidate, metadata = normalize(
                    path.read_bytes(), queried[path], padding=args.padding
                )
                destination = output / "svg" / row["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(candidate)
                row.update(
                    status="normalized-review-required",
                    **metadata,
                    candidate_sha256=hashlib.sha256(candidate).hexdigest(),
                )
            print(
                f"Queried {min(start + 100, len(eligible))}/{len(eligible)} eligible SVGs",
                flush=True,
            )
    report = {
        "format": "infinity-svg-viewport-normalization",
        "version": 2,
        "sizing": "responsive-viewBox-only",
        "geometry_unchanged": True,
        "publication_approved": False,
        "source_root": str(source),
        "inkscape": args.inkscape,
        "files": rows,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Normalized {sum(r['status'].startswith('normalized') for r in rows)}/{len(rows)} SVGs")
    return 0
