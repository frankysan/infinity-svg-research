#!/usr/bin/env python3
"""Batch detector for suspicious Illustrator-generated SVG structures.

Detection only: this tool never modifies SVG files.

It currently looks for several experimentally useful classes:

1. Flattened Illustrator blend stacks
   - many geometry elements and gradients
   - gradients collapse to very few underlying stop palettes
   - optionally, preserved source groups can be confirmed as translated blend stacks

2. Flattened gradient/mask scaffolds
   - repeated gradients sharing one/few palettes
   - many circles/paths
   - masks + filters + embedded raster images carrying a large payload

3. Embedded-raster-heavy SVGs
   - substantial base64/inline raster payload without the known gradient/mask scaffold

4. Micro-contour explosions
   - compound paths containing thousands of tiny closed subpaths
   - characteristic of distressed/traced outlines such as the Wolfgang specimen

5. Off-artboard content
   - large top-level graphic branches whose conservative bounds cannot intersect the viewBox
   - characteristic of abandoned Illustrator pasteboard copies/debris such as Oktavia

6. Subpixel-detail advisories
   - estimates closed-contour feature width from polygonized area/perimeter
   - reports detail that falls below one rendered pixel at 64/128/256 px
   - advisory only; does not imply that the detail is incorrect

7. Palette-fragmented flat-colour traces
   - many near-identical flat fill colours arranged along a small number of colour ramps
   - characteristic of raster antialiasing that has been vector-traced, such as Shaolin

8. Duplicate fill/stroke geometry
   - exact duplicate paths where one copy supplies a fill and another the same-colour stroke
   - safely mergeable in principle, as demonstrated by Trinitarians

9. Oversized path-data SVGs
   - unusually large path command payloads without raster/gradient structures explaining the size

External image references are reported as advisories because they make otherwise self-contained
SVG assets depend on sidecar files and may indicate dead export baggage. Relative/local
references are resolved against the SVG location so present dependencies can be distinguished
from missing sidecars.

Milder flat-palette fragmentation that does not meet the full traced-antialias classification
is reported as a low-severity advisory for manual review.

Embedded PNGs are also inspected (without Pillow) when possible. The scanner records
whether they are effectively single-colour alpha artwork (tolerating visually negligible
RGB noise in translucent antialiasing pixels) and whether their alpha masks are close
to simple discs/rings. This is diagnostic only; it never rewrites image content.

The report intentionally exposes the raw signals as well as the classification so
thresholds can be tuned against a larger corpus before any optimizer is built
into a production pipeline.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import math
import re
import struct
import sys
import zlib
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname
from statistics import median
from typing import Any

try:
    from lxml import etree
except ImportError as exc:  # pragma: no cover - CLI dependency error
    raise SystemExit("svg_issue_scan.py requires lxml: python -m pip install lxml") from exc

SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
NS = {"s": SVG}
NUM = r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
TOKEN_RE = re.compile(rf"[A-Za-z]|{NUM}")
PATH_COMMAND_RE = re.compile(r"[MmZzLlHhVvCcSsQqTtAa]")
PATH_TOKEN_RE = re.compile(rf"[MmZzLlHhVvCcSsQqTtAa]|{NUM}")
PATH_PARAMS = {
    "M": 2,
    "L": 2,
    "H": 1,
    "V": 1,
    "C": 6,
    "S": 4,
    "Q": 4,
    "T": 2,
    "A": 7,
    "Z": 0,
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CLASS_FILL_RE = re.compile(r"\.([\w-]+)\s*\{[^}]*?fill\s*:\s*url\(#([^)]+)\)", re.S)


@dataclass
class BlendStackEvidence:
    steps: int
    glyphs_per_step: int


@dataclass
class SvgReport:
    path: str
    size_bytes: int
    sha256: str = ""
    exact_duplicate_group_size: int = 1
    parse_error: str | None = None

    paths: int = 0
    polygons: int = 0
    circles: int = 0
    groups: int = 0
    uses: int = 0
    linear_gradients: int = 0
    radial_gradients: int = 0
    masks: int = 0
    filters: int = 0
    clip_paths: int = 0
    images: int = 0
    embedded_images: int = 0
    embedded_image_bytes_estimate: int = 0
    embedded_pngs: int = 0
    embedded_pngs_analyzed: int = 0
    embedded_monochrome_alpha_images: int = 0
    embedded_disc_like_images: int = 0
    embedded_ring_like_images: int = 0
    embedded_raster_analysis_errors: int = 0
    external_images: int = 0
    external_images_existing: int = 0
    external_images_missing: int = 0
    external_images_remote: int = 0
    external_image_references: list[str] = field(default_factory=list)
    external_image_missing_references: list[str] = field(default_factory=list)

    off_artboard_top_level_elements: int = 0
    off_artboard_bytes_estimate: int = 0
    off_artboard_external_images: int = 0
    off_artboard_analysis_errors: int = 0

    path_data_bytes: int = 0
    largest_path_data_bytes: int = 0
    path_command_count: int = 0
    path_segment_count: int = 0
    polygon_points_bytes: int = 0
    path_subpaths: int = 0
    closed_path_subpaths: int = 0
    degenerate_subpaths: int = 0
    micro_subpaths: int = 0
    small_subpaths: int = 0
    paths_with_100_subpaths: int = 0
    max_subpaths_in_path: int = 0
    repeated_subpath_count_groups: int = 0
    repeated_subpath_count_members: int = 0
    path_analysis_errors: int = 0
    viewbox_max_dimension: float = 0.0
    micro_subpath_span: float = 0.0
    small_subpath_span: float = 0.0

    subpixel_detail_paths_analyzed: int = 0
    subpixel_detail_analysis_errors: int = 0
    subpixel_closed_subpaths_64: int = 0
    subpixel_closed_subpaths_128: int = 0
    subpixel_closed_subpaths_256: int = 0
    subpixel_path_data_bytes_estimate_64: int = 0
    subpixel_path_data_bytes_estimate_128: int = 0
    subpixel_path_data_bytes_estimate_256: int = 0

    flat_fill_paths: int = 0
    distinct_flat_fill_colors: int = 0
    palette_endpoint_distance: float = 0.0
    palette_linearity_fraction: float = 0.0
    palette_intermediate_colors: int = 0
    palette_intermediate_paths: int = 0
    palette_intermediate_path_data_bytes: int = 0

    duplicate_fill_stroke_pairs: int = 0
    duplicate_fill_stroke_path_data_bytes: int = 0

    gradient_palettes: int = 0
    largest_palette_family: int = 0
    top3_palette_family: int = 0
    palette_repetition_ratio: float = 0.0

    confirmed_blend_stacks: list[BlendStackEvidence] = field(default_factory=list)
    classification: str | None = None
    severity: str | None = None
    advisories: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)

    @property
    def geometry_elements(self) -> int:
        return self.paths + self.polygons

    @property
    def vector_data_bytes(self) -> int:
        return self.path_data_bytes + self.polygon_points_bytes

    @property
    def vector_data_fraction(self) -> float:
        return self.vector_data_bytes / self.size_bytes if self.size_bytes else 0.0

    @property
    def micro_subpath_fraction(self) -> float:
        return self.micro_subpaths / self.closed_path_subpaths if self.closed_path_subpaths else 0.0

    @property
    def small_subpath_fraction(self) -> float:
        return self.small_subpaths / self.closed_path_subpaths if self.closed_path_subpaths else 0.0

    @property
    def embedded_monochrome_fraction(self) -> float:
        return (
            self.embedded_monochrome_alpha_images / self.embedded_pngs_analyzed
            if self.embedded_pngs_analyzed
            else 0.0
        )

    @property
    def off_artboard_fraction(self) -> float:
        return self.off_artboard_bytes_estimate / self.size_bytes if self.size_bytes else 0.0

    def _subpixel_fraction(self, count: int) -> float:
        return count / self.closed_path_subpaths if self.closed_path_subpaths else 0.0

    def _subpixel_bytes_fraction(self, value: int) -> float:
        return value / self.path_data_bytes if self.path_data_bytes else 0.0

    @property
    def subpixel_closed_subpath_fraction_64(self) -> float:
        return self._subpixel_fraction(self.subpixel_closed_subpaths_64)

    @property
    def subpixel_closed_subpath_fraction_128(self) -> float:
        return self._subpixel_fraction(self.subpixel_closed_subpaths_128)

    @property
    def subpixel_closed_subpath_fraction_256(self) -> float:
        return self._subpixel_fraction(self.subpixel_closed_subpaths_256)

    @property
    def subpixel_path_data_fraction_64(self) -> float:
        return self._subpixel_bytes_fraction(self.subpixel_path_data_bytes_estimate_64)

    @property
    def subpixel_path_data_fraction_128(self) -> float:
        return self._subpixel_bytes_fraction(self.subpixel_path_data_bytes_estimate_128)

    @property
    def subpixel_path_data_fraction_256(self) -> float:
        return self._subpixel_bytes_fraction(self.subpixel_path_data_bytes_estimate_256)

    @property
    def flagged(self) -> bool:
        return (
            self.classification is not None
            or self.parse_error is not None
            or bool(self.advisories)
        )


@dataclass
class ScanSummary:
    root: str
    svg_files: int
    flagged_files: int
    parse_errors: int
    exact_duplicate_groups: int
    classifications: dict[str, int]
    advisories: dict[str, int]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_duplicate_groups(reports: list[SvgReport]) -> list[dict[str, Any]]:
    by_hash: dict[str, list[SvgReport]] = {}
    for report in reports:
        if not report.sha256:
            continue
        by_hash.setdefault(report.sha256, []).append(report)

    groups: list[dict[str, Any]] = []
    for digest, members in by_hash.items():
        if len(members) < 2:
            continue
        for member in members:
            member.exact_duplicate_group_size = len(members)
        groups.append(
            {
                "sha256": digest,
                "size_bytes": members[0].size_bytes,
                "count": len(members),
                "paths": sorted(member.path for member in members),
            }
        )

    groups.sort(key=lambda group: (-group["size_bytes"] * group["count"], group["paths"][0]))
    return groups


def local_name(element: etree._Element) -> str:
    """Return an element local name, ignoring comments/PIs and other non-elements."""
    tag = element.tag
    if not isinstance(tag, str):
        return ""
    return etree.QName(tag).localname


def resolve_gradient_stops(
    gradients: dict[str, etree._Element], gradient_id: str
) -> tuple[tuple[str | None, str | None, str | None, str | None], ...]:
    """Resolve a gradient's effective stop list through href inheritance."""
    seen: set[str] = set()
    current = gradient_id
    while current not in seen and current in gradients:
        seen.add(current)
        gradient = gradients[current]
        stops = [child for child in gradient if local_name(child) == "stop"]
        if stops:
            return tuple(
                (
                    stop.get("offset"),
                    stop.get("stop-color"),
                    stop.get("stop-opacity"),
                    stop.get("style"),
                )
                for stop in stops
            )
        href = gradient.get(f"{{{XLINK}}}href") or gradient.get("href")
        if not href or not href.startswith("#"):
            break
        current = href[1:]
    return ()


def resolve_gradient_attr(
    gradients: dict[str, etree._Element], gradient_id: str, attr: str
) -> str | None:
    seen: set[str] = set()
    current = gradient_id
    while current not in seen and current in gradients:
        seen.add(current)
        gradient = gradients[current]
        value = gradient.get(attr)
        if value is not None:
            return value
        href = gradient.get(f"{{{XLINK}}}href") or gradient.get("href")
        if not href or not href.startswith("#"):
            break
        current = href[1:]
    return None


def gradient_translation(transform: str | None) -> tuple[float, float] | None:
    if transform is None:
        return (0.0, 0.0)
    match = re.fullmatch(rf"\s*translate\(({NUM})(?:[ ,]+)({NUM})\)\s*", transform)
    if match:
        return float(match.group(1)), float(match.group(2))
    match = re.fullmatch(
        rf"\s*matrix\(1(?:\.0+)?,[ ,]*0,[ ,]*0,[ ,]*1(?:\.0+)?,[ ,]*({NUM}),[ ,]*({NUM})\)\s*",
        transform,
    )
    if match:
        return float(match.group(1)), float(match.group(2))
    return None


def normalized_geometry(element: etree._Element) -> tuple[list[str | float], tuple[float, float]]:
    """Normalize observed Illustrator path/polygon geometry to its first anchor."""
    name = local_name(element)
    if name == "polygon":
        values = [float(v) for v in re.findall(NUM, element.get("points") or "")]
        if len(values) < 2 or len(values) % 2:
            raise ValueError("unsupported polygon")
        x0, y0 = values[:2]
        normalized = [v - (x0 if i % 2 == 0 else y0) for i, v in enumerate(values)]
        return normalized, (x0, y0)

    if name != "path":
        raise ValueError(f"unsupported geometry: {name}")

    tokens = TOKEN_RE.findall(element.get("d") or "")
    commands = [token for token in tokens if token.isalpha()]
    # The Ruby Monday source uses absolute M followed by relative commands.
    # Reject less constrained geometry rather than guessing how to normalize it.
    if any(command.isupper() and command not in {"M", "Z"} for command in commands):
        raise ValueError("path contains unsupported absolute commands")

    raw: list[str | float] = []
    absolute_indices: list[tuple[int, int, float]] = []
    command: str | None = None
    number_in_command = 0
    for token in tokens:
        if token.isalpha():
            command = token
            number_in_command = 0
            raw.append(token)
            continue
        value = float(token)
        raw.append(value)
        if command == "M":
            absolute_indices.append((len(raw) - 1, number_in_command % 2, value))
        number_in_command += 1

    if len(absolute_indices) < 2:
        raise ValueError("path has no absolute move pair")
    x0 = absolute_indices[0][2]
    y0 = absolute_indices[1][2]
    for index, axis, value in absolute_indices:
        raw[index] = value - (x0 if axis == 0 else y0)
    return raw, (x0, y0)


def close_sequences(a: list[str | float], b: list[str | float], tolerance: float) -> bool:
    if len(a) != len(b):
        return False
    for left, right in zip(a, b, strict=True):
        if isinstance(left, str) or isinstance(right, str):
            if left != right:
                return False
        elif abs(left - right) > tolerance:
            return False
    return True


def analyze_blend_stack(
    stack: etree._Element,
    class_fill: dict[str, str],
    gradients: dict[str, etree._Element],
    geometry_tolerance: float,
    translation_tolerance: float,
) -> BlendStackEvidence | None:
    """Confirm the preserved Ruby-Monday-style grouped blend signature."""
    steps = list(stack)
    if len(steps) < 20 or not all(local_name(step) == "g" for step in steps):
        return None
    widths = {len(step) for step in steps}
    if len(widths) != 1:
        return None
    width = next(iter(widths))
    if not 2 <= width <= 12:
        return None

    base = list(steps[0])
    tags = [local_name(element) for element in base]
    if any(tag not in {"path", "polygon"} for tag in tags):
        return None
    if any([local_name(element) for element in step] != tags for step in steps[1:]):
        return None

    try:
        base_norm = [normalized_geometry(element) for element in base]
    except ValueError:
        return None

    base_paints: list[tuple[tuple[Any, ...], tuple[float, float]]] = []
    for element in base:
        gradient_id = class_fill.get(element.get("class") or "")
        if not gradient_id or gradient_id not in gradients:
            return None
        signature: tuple[Any, ...] = (
            resolve_gradient_stops(gradients, gradient_id),
            tuple(
                resolve_gradient_attr(gradients, gradient_id, attr)
                for attr in ("x1", "y1", "x2", "y2", "gradientUnits")
            ),
        )
        translation = gradient_translation(
            resolve_gradient_attr(gradients, gradient_id, "gradientTransform")
        )
        if translation is None:
            return None
        base_paints.append((signature, translation))

    for step in steps:
        shifts: list[tuple[float, float]] = []
        for index, element in enumerate(step):
            try:
                normalized, anchor = normalized_geometry(element)
            except ValueError:
                return None
            base_geometry, base_anchor = base_norm[index]
            if not close_sequences(base_geometry, normalized, geometry_tolerance):
                return None
            dx = anchor[0] - base_anchor[0]
            dy = anchor[1] - base_anchor[1]
            shifts.append((dx, dy))

            gradient_id = class_fill.get(element.get("class") or "")
            if not gradient_id or gradient_id not in gradients:
                return None
            signature = (
                resolve_gradient_stops(gradients, gradient_id),
                tuple(
                    resolve_gradient_attr(gradients, gradient_id, attr)
                    for attr in ("x1", "y1", "x2", "y2", "gradientUnits")
                ),
            )
            if signature != base_paints[index][0]:
                return None
            current_translation = gradient_translation(
                resolve_gradient_attr(gradients, gradient_id, "gradientTransform")
            )
            if current_translation is None:
                return None
            paint_dx = current_translation[0] - base_paints[index][1][0]
            paint_dy = current_translation[1] - base_paints[index][1][1]
            if abs(paint_dx - dx) > translation_tolerance:
                return None
            if abs(paint_dy - dy) > translation_tolerance:
                return None

        dx = median(shift[0] for shift in shifts)
        dy = median(shift[1] for shift in shifts)
        if any(
            abs(x - dx) > translation_tolerance or abs(y - dy) > translation_tolerance
            for x, y in shifts
        ):
            return None

    return BlendStackEvidence(steps=len(steps), glyphs_per_step=width)


def estimate_data_url_bytes(href: str) -> int:
    if not href.startswith("data:") or "," not in href:
        return 0
    header, payload = href.split(",", 1)
    if ";base64" in header.lower():
        # Ignore whitespace; padding makes this an upper-bound-ish estimate by <=2 bytes.
        length = len(re.sub(r"\s+", "", payload))
        return (length * 3) // 4
    # Percent-encoded data is uncommon in these assets; byte length is enough as a signal.
    return len(payload.encode("utf-8"))




def decode_data_url(href: str) -> tuple[str, bytes] | None:
    """Decode an inline data URL when it uses base64 or literal payload data."""
    if not href.startswith("data:") or "," not in href:
        return None
    header, payload = href.split(",", 1)
    media_type = header[5:].split(";", 1)[0].lower() or "text/plain"
    try:
        if ";base64" in header.lower():
            data = base64.b64decode(re.sub(r"\s+", "", payload), validate=False)
        else:
            # Percent-decoding is intentionally omitted here. SVG-embedded raster
            # images in the corpus are base64; unsupported literal payloads simply
            # skip deep analysis while retaining the size signal.
            return None
    except (ValueError, base64.binascii.Error):
        return None
    return media_type, data


def paeth_predictor(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def decode_png_rgba(data: bytes) -> tuple[int, int, bytes] | None:
    """Decode common 8-bit, non-interlaced PNGs using only the standard library.

    The scanner needs only enough PNG support to inspect embedded logo/mask images;
    unsupported PNG variants are reported as unanalyzed rather than treated as errors.
    """
    if not data.startswith(PNG_SIGNATURE):
        return None

    offset = len(PNG_SIGNATURE)
    width = height = bit_depth = color_type = interlace = None
    palette: bytes | None = None
    transparency: bytes | None = None
    idat = bytearray()

    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_start = offset + 8
        chunk_end = chunk_start + length
        if chunk_end + 4 > len(data):
            return None
        chunk = data[chunk_start:chunk_end]
        offset = chunk_end + 4

        if chunk_type == b"IHDR":
            if len(chunk) != 13:
                return None
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
            if compression != 0 or filtering != 0:
                return None
        elif chunk_type == b"PLTE":
            palette = chunk
        elif chunk_type == b"tRNS":
            transparency = chunk
        elif chunk_type == b"IDAT":
            idat.extend(chunk)
        elif chunk_type == b"IEND":
            break

    if (
        width is None
        or height is None
        or bit_depth != 8
        or interlace != 0
        or width <= 0
        or height <= 0
        or width > 8192
        or height > 8192
    ):
        return None

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        return None
    stride = width * channels
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error:
        return None
    if len(raw) != height * (stride + 1):
        return None

    rows: list[bytearray] = []
    position = 0
    previous = bytearray(stride)
    bpp = channels
    for _ in range(height):
        filter_type = raw[position]
        position += 1
        scanline = bytearray(raw[position : position + stride])
        position += stride
        reconstructed = bytearray(stride)
        for i, value in enumerate(scanline):
            left = reconstructed[i - bpp] if i >= bpp else 0
            up = previous[i]
            upper_left = previous[i - bpp] if i >= bpp else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = up
            elif filter_type == 3:
                predictor = (left + up) // 2
            elif filter_type == 4:
                predictor = paeth_predictor(left, up, upper_left)
            else:
                return None
            reconstructed[i] = (value + predictor) & 0xFF
        rows.append(reconstructed)
        previous = reconstructed

    rgba = bytearray(width * height * 4)
    out = 0
    transparent_gray: int | None = None
    transparent_rgb: tuple[int, int, int] | None = None
    if transparency and color_type == 0 and len(transparency) >= 2:
        transparent_gray = struct.unpack(">H", transparency[:2])[0] & 0xFF
    elif transparency and color_type == 2 and len(transparency) >= 6:
        tr, tg, tb = struct.unpack(">HHH", transparency[:6])
        transparent_rgb = (tr & 0xFF, tg & 0xFF, tb & 0xFF)

    for row in rows:
        if color_type == 6:
            for i in range(0, len(row), 4):
                rgba[out : out + 4] = row[i : i + 4]
                out += 4
        elif color_type == 4:
            for i in range(0, len(row), 2):
                gray, alpha = row[i], row[i + 1]
                rgba[out : out + 4] = bytes((gray, gray, gray, alpha))
                out += 4
        elif color_type == 2:
            for i in range(0, len(row), 3):
                rgb = (row[i], row[i + 1], row[i + 2])
                alpha = 0 if transparent_rgb == rgb else 255
                rgba[out : out + 4] = bytes((*rgb, alpha))
                out += 4
        elif color_type == 0:
            for gray in row:
                alpha = 0 if transparent_gray == gray else 255
                rgba[out : out + 4] = bytes((gray, gray, gray, alpha))
                out += 4
        elif color_type == 3:
            if palette is None or len(palette) % 3:
                return None
            for index in row:
                base = index * 3
                if base + 2 >= len(palette):
                    return None
                alpha = transparency[index] if transparency and index < len(transparency) else 255
                rgba[out : out + 4] = bytes(
                    (palette[base], palette[base + 1], palette[base + 2], alpha)
                )
                out += 4

    return width, height, bytes(rgba)


def analyze_alpha_primitive(width: int, height: int, rgba: bytes) -> str | None:
    """Return 'disc'/'ring' when an alpha mask closely matches a circular primitive."""
    threshold = 128
    active: list[tuple[int, int]] = []
    for y in range(height):
        row = y * width * 4
        for x in range(width):
            if rgba[row + x * 4 + 3] >= threshold:
                active.append((x, y))
    if not active:
        return None

    min_x = min(x for x, _ in active)
    max_x = max(x for x, _ in active)
    min_y = min(y for _, y in active)
    max_y = max(y for _, y in active)
    cx = (min_x + max_x) / 2.0
    cy = (min_y + max_y) / 2.0
    max_radius = int(math.ceil(math.hypot(max(width, height), max(width, height)))) + 2
    radial_total = [0] * max_radius
    radial_active = [0] * max_radius

    for y in range(height):
        row = y * width * 4
        for x in range(width):
            radius = int(math.floor(math.hypot(x - cx, y - cy) + 0.5))
            if radius >= max_radius:
                continue
            radial_total[radius] += 1
            if rgba[row + x * 4 + 3] >= threshold:
                radial_active[radius] += 1

    good = [
        radius
        for radius, total in enumerate(radial_total)
        if total and radial_active[radius] / total >= 0.5
    ]
    if not good:
        return None

    runs: list[tuple[int, int]] = []
    start = previous = good[0]
    for radius in good[1:]:
        if radius == previous + 1:
            previous = radius
        else:
            runs.append((start, previous))
            start = previous = radius
    runs.append((start, previous))
    inner_bin, outer_bin = max(runs, key=lambda pair: pair[1] - pair[0])
    inner = max(0.0, inner_bin - 0.5)
    outer = outer_bin + 0.5

    intersection = 0
    union = 0
    for y in range(height):
        row = y * width * 4
        for x in range(width):
            radius = math.hypot(x - cx, y - cy)
            ideal = inner <= radius <= outer
            actual = rgba[row + x * 4 + 3] >= threshold
            if ideal and actual:
                intersection += 1
            if ideal or actual:
                union += 1
    if not union:
        return None
    iou = intersection / union
    if iou < 0.92:
        return None
    return "disc" if inner_bin <= 2 else "ring"


def analyze_embedded_png(data: bytes) -> tuple[bool, str | None] | None:
    """Return (effectively-single-colour-alpha, primitive-kind) for supported PNGs.

    Illustrator/PNG antialiasing can leave RGB values in translucent edge pixels that
    differ slightly from the fully opaque artwork colour. Compare premultiplied colour
    contribution instead of requiring byte-identical RGB for every alpha>0 pixel.
    This keeps the test strict in opaque regions while tolerating visually negligible
    fringe noise such as the Taowu specimen.
    """
    decoded = decode_png_rgba(data)
    if decoded is None:
        return None
    width, height, rgba = decoded

    alpha_values: set[int] = set()
    high_alpha_colors: Counter[tuple[int, int, int]] = Counter()
    visible_pixels: list[tuple[int, int, int, int]] = []
    has_transparency = False
    for i in range(0, len(rgba), 4):
        red, green, blue, alpha = rgba[i : i + 4]
        alpha_values.add(alpha)
        if alpha < 255:
            has_transparency = True
        if alpha == 0:
            continue
        visible_pixels.append((red, green, blue, alpha))
        if alpha >= 240:
            high_alpha_colors[(red, green, blue)] += 1

    if not visible_pixels or not has_transparency or len(alpha_values) <= 1:
        return False, None

    if high_alpha_colors:
        base_color, _ = high_alpha_colors.most_common(1)[0]
    else:
        # Rare masks with no nearly-opaque pixels: use the most opaque pixel colour
        # rather than guessing from nearly invisible fringe pixels.
        red, green, blue, _ = max(visible_pixels, key=lambda pixel: pixel[3])
        base_color = (red, green, blue)

    # Premultiplied channel error is the visible contribution of an RGB deviation.
    # 2/255 is deliberately tight: Taowu's antialias fringe peaks below this while
    # actual gradients/multicolour artwork fail decisively in opaque regions.
    max_premultiplied_error = 0.0
    for red, green, blue, alpha in visible_pixels:
        channel_error = max(
            abs(red - base_color[0]),
            abs(green - base_color[1]),
            abs(blue - base_color[2]),
        )
        max_premultiplied_error = max(
            max_premultiplied_error, channel_error * alpha / 255.0
        )
        if max_premultiplied_error > 2.0:
            return False, None

    monochrome_alpha = True
    primitive = analyze_alpha_primitive(width, height, rgba)
    return monochrome_alpha, primitive


def parse_viewbox_bounds(root: etree._Element) -> tuple[float, float, float, float] | None:
    viewbox = root.get("viewBox")
    if not viewbox:
        return None
    values = [float(value) for value in re.findall(NUM, viewbox)]
    if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
        return None
    x, y, width, height = values
    return x, y, x + width, y + height


def parse_viewbox_max_dimension(root: etree._Element) -> float:
    viewbox = root.get("viewBox")
    if viewbox:
        values = [float(value) for value in re.findall(NUM, viewbox)]
        if len(values) == 4 and values[2] > 0 and values[3] > 0:
            return max(values[2], values[3])
    dimensions: list[float] = []
    for attr in ("width", "height"):
        value = root.get(attr)
        if value:
            match = re.match(NUM, value.strip())
            if match:
                dimensions.append(float(match.group(0)))
    return max(dimensions, default=0.0)


def _include_point(bounds: list[float], x: float, y: float) -> None:
    bounds[0] = min(bounds[0], x)
    bounds[1] = min(bounds[1], y)
    bounds[2] = max(bounds[2], x)
    bounds[3] = max(bounds[3], y)


def analyze_path_subpaths(path_data: str) -> tuple[list[tuple[float, bool]], int]:
    """Return approximate (span, closed) stats for every subpath plus segment count.

    Bounds include endpoints and Bézier control points. Arc bounds are deliberately
    conservative (endpoint/current point expanded by the radii), which avoids
    falsely classifying a non-tiny arc as a micro-contour.
    """
    tokens = PATH_TOKEN_RE.findall(path_data)
    if not tokens:
        return [], 0

    stats: list[tuple[float, bool]] = []
    i = 0
    command: str | None = None
    x = y = 0.0
    start_x = start_y = 0.0
    bounds: list[float] | None = None
    closed = False
    segment_count = 0

    def finish() -> None:
        nonlocal bounds, closed
        if bounds is None:
            return
        span = max(bounds[2] - bounds[0], bounds[3] - bounds[1])
        stats.append((span, closed))
        bounds = None
        closed = False

    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            command = token
            i += 1
            if command.upper() == "Z":
                if bounds is not None:
                    _include_point(bounds, start_x, start_y)
                    closed = True
                    x, y = start_x, start_y
                    segment_count += 1
                command = None
                continue
        if command is None:
            raise ValueError("path data contains numbers without a command")

        upper = command.upper()
        count = PATH_PARAMS.get(upper)
        if count is None or count == 0:
            raise ValueError(f"unsupported path command: {command}")
        if i + count > len(tokens) or any(value.isalpha() for value in tokens[i : i + count]):
            raise ValueError(f"incomplete path command: {command}")
        values = [float(value) for value in tokens[i : i + count]]
        i += count
        relative = command.islower()

        if upper == "M":
            nx = values[0] + (x if relative else 0.0)
            ny = values[1] + (y if relative else 0.0)
            finish()
            x, y = nx, ny
            start_x, start_y = x, y
            bounds = [x, y, x, y]
            segment_count += 1
            command = "l" if relative else "L"
            continue

        if bounds is None:
            raise ValueError("path drawing command occurs before moveto")

        if upper == "L":
            nx = values[0] + (x if relative else 0.0)
            ny = values[1] + (y if relative else 0.0)
            _include_point(bounds, nx, ny)
            x, y = nx, ny
        elif upper == "H":
            nx = values[0] + (x if relative else 0.0)
            _include_point(bounds, nx, y)
            x = nx
        elif upper == "V":
            ny = values[0] + (y if relative else 0.0)
            _include_point(bounds, x, ny)
            y = ny
        elif upper == "C":
            points = [(values[0], values[1]), (values[2], values[3]), (values[4], values[5])]
            absolute: list[tuple[float, float]] = []
            for px, py in points:
                absolute.append((px + (x if relative else 0.0), py + (y if relative else 0.0)))
            for px, py in absolute:
                _include_point(bounds, px, py)
            x, y = absolute[-1]
        elif upper in {"S", "Q"}:
            points = [(values[0], values[1]), (values[2], values[3])]
            absolute = [
                (px + (x if relative else 0.0), py + (y if relative else 0.0))
                for px, py in points
            ]
            for px, py in absolute:
                _include_point(bounds, px, py)
            x, y = absolute[-1]
        elif upper == "T":
            nx = values[0] + (x if relative else 0.0)
            ny = values[1] + (y if relative else 0.0)
            _include_point(bounds, nx, ny)
            x, y = nx, ny
        elif upper == "A":
            rx, ry = abs(values[0]), abs(values[1])
            nx = values[5] + (x if relative else 0.0)
            ny = values[6] + (y if relative else 0.0)
            radius = max(rx, ry)
            for px, py in ((x, y), (nx, ny)):
                _include_point(bounds, px - radius, py - radius)
                _include_point(bounds, px + radius, py + radius)
            x, y = nx, ny
        segment_count += 1

    finish()
    return stats, segment_count

Matrix = tuple[float, float, float, float, float, float]
Bounds = tuple[float, float, float, float]
IDENTITY_MATRIX: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
TRANSFORM_RE = re.compile(r"([A-Za-z]+)\s*\(([^)]*)\)")
NONRENDERING_TAGS = {
    "defs",
    "style",
    "title",
    "desc",
    "metadata",
    "linearGradient",
    "radialGradient",
    "filter",
    "mask",
    "clipPath",
    "pattern",
    "symbol",
}


def multiply_matrix(left: Matrix, right: Matrix) -> Matrix:
    """Return left * right for SVG's 2D affine column-vector matrices."""
    a1, b1, c1, d1, e1, f1 = left
    a2, b2, c2, d2, e2, f2 = right
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def parse_transform(transform: str | None) -> Matrix | None:
    if not transform or not transform.strip():
        return IDENTITY_MATRIX
    matrix = IDENTITY_MATRIX
    position = 0
    for match in TRANSFORM_RE.finditer(transform):
        if transform[position : match.start()].strip(" ,\t\r\n"):
            return None
        position = match.end()
        name = match.group(1)
        values = [float(value) for value in re.findall(NUM, match.group(2))]
        op: Matrix
        if name == "matrix" and len(values) == 6:
            op = tuple(values)  # type: ignore[assignment]
        elif name == "translate" and len(values) in {1, 2}:
            tx = values[0]
            ty = values[1] if len(values) == 2 else 0.0
            op = (1.0, 0.0, 0.0, 1.0, tx, ty)
        elif name == "scale" and len(values) in {1, 2}:
            sx = values[0]
            sy = values[1] if len(values) == 2 else sx
            op = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif name == "rotate" and len(values) in {1, 3}:
            angle = math.radians(values[0])
            cosine = math.cos(angle)
            sine = math.sin(angle)
            rotation: Matrix = (cosine, sine, -sine, cosine, 0.0, 0.0)
            if len(values) == 3:
                cx, cy = values[1], values[2]
                op = multiply_matrix(
                    multiply_matrix((1.0, 0.0, 0.0, 1.0, cx, cy), rotation),
                    (1.0, 0.0, 0.0, 1.0, -cx, -cy),
                )
            else:
                op = rotation
        elif name == "skewX" and len(values) == 1:
            op = (1.0, 0.0, math.tan(math.radians(values[0])), 1.0, 0.0, 0.0)
        elif name == "skewY" and len(values) == 1:
            op = (1.0, math.tan(math.radians(values[0])), 0.0, 1.0, 0.0, 0.0)
        else:
            return None
        matrix = multiply_matrix(matrix, op)
    if transform[position:].strip(" ,\t\r\n"):
        return None
    return matrix


def transform_bounds(bounds: Bounds, matrix: Matrix) -> Bounds:
    min_x, min_y, max_x, max_y = bounds
    a, b, c, d, e, f = matrix
    points = (
        (a * min_x + c * min_y + e, b * min_x + d * min_y + f),
        (a * min_x + c * max_y + e, b * min_x + d * max_y + f),
        (a * max_x + c * min_y + e, b * max_x + d * min_y + f),
        (a * max_x + c * max_y + e, b * max_x + d * max_y + f),
    )
    return (
        min(x for x, _ in points),
        min(y for _, y in points),
        max(x for x, _ in points),
        max(y for _, y in points),
    )


def transform_point(point: tuple[float, float], matrix: Matrix) -> tuple[float, float]:
    x, y = point
    a, b, c, d, e, f = matrix
    return a * x + c * y + e, b * x + d * y + f


def cumulative_transform(element: etree._Element) -> Matrix | None:
    """Return the element-to-root transform, or None for unsupported transforms."""
    chain: list[etree._Element] = []
    current: etree._Element | None = element
    while current is not None:
        chain.append(current)
        current = current.getparent()
    matrix = IDENTITY_MATRIX
    for node in reversed(chain):
        local = parse_transform(node.get("transform"))
        if local is None:
            return None
        matrix = multiply_matrix(matrix, local)
    return matrix


def _cubic_point(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    u = 1.0 - t
    return (
        u * u * u * p0[0]
        + 3.0 * u * u * t * p1[0]
        + 3.0 * u * t * t * p2[0]
        + t * t * t * p3[0],
        u * u * u * p0[1]
        + 3.0 * u * u * t * p1[1]
        + 3.0 * u * t * t * p2[1]
        + t * t * t * p3[1],
    )


def _quadratic_point(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    u = 1.0 - t
    return (
        u * u * p0[0] + 2.0 * u * t * p1[0] + t * t * p2[0],
        u * u * p0[1] + 2.0 * u * t * p1[1] + t * t * p2[1],
    )


def _arc_points(
    start: tuple[float, float],
    rx: float,
    ry: float,
    rotation_degrees: float,
    large_arc: bool,
    sweep: bool,
    end: tuple[float, float],
    minimum_samples: int,
) -> list[tuple[float, float]]:
    """Sample an SVG endpoint-parameterized elliptical arc, excluding start."""
    x1, y1 = start
    x2, y2 = end
    rx = abs(rx)
    ry = abs(ry)
    if rx == 0.0 or ry == 0.0 or (x1 == x2 and y1 == y2):
        return [end]

    phi = math.radians(rotation_degrees % 360.0)
    cos_phi = math.cos(phi)
    sin_phi = math.sin(phi)
    dx = (x1 - x2) / 2.0
    dy = (y1 - y2) / 2.0
    x1p = cos_phi * dx + sin_phi * dy
    y1p = -sin_phi * dx + cos_phi * dy

    radius_scale = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if radius_scale > 1.0:
        scale = math.sqrt(radius_scale)
        rx *= scale
        ry *= scale

    numerator = max(
        0.0,
        rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p,
    )
    denominator = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coefficient = 0.0 if denominator == 0.0 else math.sqrt(numerator / denominator)
    if large_arc == sweep:
        coefficient = -coefficient
    cxp = coefficient * (rx * y1p / ry)
    cyp = coefficient * (-ry * x1p / rx)
    cx = cos_phi * cxp - sin_phi * cyp + (x1 + x2) / 2.0
    cy = sin_phi * cxp + cos_phi * cyp + (y1 + y2) / 2.0

    def angle(u: tuple[float, float], v: tuple[float, float]) -> float:
        dot = u[0] * v[0] + u[1] * v[1]
        det = u[0] * v[1] - u[1] * v[0]
        return math.atan2(det, dot)

    ux = (x1p - cxp) / rx
    uy = (y1p - cyp) / ry
    vx = (-x1p - cxp) / rx
    vy = (-y1p - cyp) / ry
    theta1 = angle((1.0, 0.0), (ux, uy))
    delta = angle((ux, uy), (vx, vy))
    if not sweep and delta > 0.0:
        delta -= 2.0 * math.pi
    elif sweep and delta < 0.0:
        delta += 2.0 * math.pi

    samples = max(minimum_samples, int(math.ceil(abs(delta) / (math.pi / 12.0))))
    points: list[tuple[float, float]] = []
    for step in range(1, samples + 1):
        theta = theta1 + delta * (step / samples)
        cos_theta = math.cos(theta)
        sin_theta = math.sin(theta)
        points.append(
            (
                cx + cos_phi * rx * cos_theta - sin_phi * ry * sin_theta,
                cy + sin_phi * rx * cos_theta + cos_phi * ry * sin_theta,
            )
        )
    return points


def _polygon_feature_width(points: list[tuple[float, float]]) -> float | None:
    if len(points) < 3:
        return None
    area2 = 0.0
    perimeter = 0.0
    for index, current in enumerate(points):
        following = points[(index + 1) % len(points)]
        area2 += current[0] * following[1] - following[0] * current[1]
        perimeter += math.hypot(following[0] - current[0], following[1] - current[1])
    if perimeter <= 1e-12:
        return None
    # 2A/P approximates the thickness of a long narrow closed feature, while
    # remaining scale-aware and cheap enough for a corpus scan.
    return abs(area2) / perimeter


def analyze_path_feature_widths(
    path_data: str,
    matrix: Matrix,
    *,
    curve_samples: int,
) -> tuple[list[tuple[float, int]], int]:
    """Return (approx feature width, segment count) for closed subpaths.

    Curves are polygonized in transformed/root user coordinates. The result is
    advisory: self-intersections and compound fill semantics can make 2A/P only an
    approximation of visible feature width.
    """
    tokens = PATH_TOKEN_RE.findall(path_data)
    if not tokens:
        return [], 0

    widths: list[tuple[float, int]] = []
    i = 0
    command: str | None = None
    x = y = 0.0
    start_x = start_y = 0.0
    points: list[tuple[float, float]] = []
    closed = False
    subpath_segments = 0
    total_segments = 0
    previous_upper: str | None = None
    last_cubic_control: tuple[float, float] | None = None
    last_quadratic_control: tuple[float, float] | None = None

    def add_point(point: tuple[float, float]) -> None:
        points.append(transform_point(point, matrix))

    def finish() -> None:
        nonlocal points, closed, subpath_segments
        if closed and len(points) >= 3:
            width = _polygon_feature_width(points)
            if width is not None:
                widths.append((width, max(subpath_segments, 1)))
        points = []
        closed = False
        subpath_segments = 0

    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            command = token
            i += 1
            if command.upper() == "Z":
                if points:
                    closed = True
                    x, y = start_x, start_y
                    subpath_segments += 1
                    total_segments += 1
                previous_upper = "Z"
                last_cubic_control = None
                last_quadratic_control = None
                command = None
                continue
        if command is None:
            raise ValueError("path data contains numbers without a command")

        upper = command.upper()
        count = PATH_PARAMS.get(upper)
        if count is None or count == 0:
            raise ValueError(f"unsupported path command: {command}")
        if i + count > len(tokens) or any(value.isalpha() for value in tokens[i : i + count]):
            raise ValueError(f"incomplete path command: {command}")
        values = [float(value) for value in tokens[i : i + count]]
        i += count
        relative = command.islower()
        current = (x, y)

        if upper == "M":
            nx = values[0] + (x if relative else 0.0)
            ny = values[1] + (y if relative else 0.0)
            finish()
            x, y = nx, ny
            start_x, start_y = x, y
            add_point((x, y))
            previous_upper = "M"
            last_cubic_control = None
            last_quadratic_control = None
            command = "l" if relative else "L"
            continue

        if not points:
            raise ValueError("path drawing command occurs before moveto")

        generated: list[tuple[float, float]] = []
        if upper == "L":
            nx = values[0] + (x if relative else 0.0)
            ny = values[1] + (y if relative else 0.0)
            generated = [(nx, ny)]
            last_cubic_control = None
            last_quadratic_control = None
        elif upper == "H":
            nx = values[0] + (x if relative else 0.0)
            ny = y
            generated = [(nx, ny)]
            last_cubic_control = None
            last_quadratic_control = None
        elif upper == "V":
            nx = x
            ny = values[0] + (y if relative else 0.0)
            generated = [(nx, ny)]
            last_cubic_control = None
            last_quadratic_control = None
        elif upper == "C":
            c1 = (values[0] + (x if relative else 0.0), values[1] + (y if relative else 0.0))
            c2 = (values[2] + (x if relative else 0.0), values[3] + (y if relative else 0.0))
            end = (values[4] + (x if relative else 0.0), values[5] + (y if relative else 0.0))
            generated = [
                _cubic_point(current, c1, c2, end, step / curve_samples)
                for step in range(1, curve_samples + 1)
            ]
            nx, ny = end
            last_cubic_control = c2
            last_quadratic_control = None
        elif upper == "S":
            if previous_upper in {"C", "S"} and last_cubic_control is not None:
                c1 = (2.0 * x - last_cubic_control[0], 2.0 * y - last_cubic_control[1])
            else:
                c1 = current
            c2 = (values[0] + (x if relative else 0.0), values[1] + (y if relative else 0.0))
            end = (values[2] + (x if relative else 0.0), values[3] + (y if relative else 0.0))
            generated = [
                _cubic_point(current, c1, c2, end, step / curve_samples)
                for step in range(1, curve_samples + 1)
            ]
            nx, ny = end
            last_cubic_control = c2
            last_quadratic_control = None
        elif upper == "Q":
            control = (
                values[0] + (x if relative else 0.0),
                values[1] + (y if relative else 0.0),
            )
            end = (
                values[2] + (x if relative else 0.0),
                values[3] + (y if relative else 0.0),
            )
            generated = [
                _quadratic_point(current, control, end, step / curve_samples)
                for step in range(1, curve_samples + 1)
            ]
            nx, ny = end
            last_quadratic_control = control
            last_cubic_control = None
        elif upper == "T":
            if previous_upper in {"Q", "T"} and last_quadratic_control is not None:
                control = (
                    2.0 * x - last_quadratic_control[0],
                    2.0 * y - last_quadratic_control[1],
                )
            else:
                control = current
            end = (
                values[0] + (x if relative else 0.0),
                values[1] + (y if relative else 0.0),
            )
            generated = [
                _quadratic_point(current, control, end, step / curve_samples)
                for step in range(1, curve_samples + 1)
            ]
            nx, ny = end
            last_quadratic_control = control
            last_cubic_control = None
        elif upper == "A":
            end = (
                values[5] + (x if relative else 0.0),
                values[6] + (y if relative else 0.0),
            )
            generated = _arc_points(
                current,
                values[0],
                values[1],
                values[2],
                bool(int(values[3])),
                bool(int(values[4])),
                end,
                curve_samples,
            )
            nx, ny = end
            last_cubic_control = None
            last_quadratic_control = None
        else:  # pragma: no cover - PATH_PARAMS already constrains this
            raise ValueError(f"unsupported path command: {command}")

        for point in generated:
            add_point(point)
        x, y = nx, ny
        subpath_segments += 1
        total_segments += 1
        previous_upper = upper

    finish()
    return widths, total_segments


def union_bounds(bounds: Iterable[Bounds]) -> Bounds | None:
    items = list(bounds)
    if not items:
        return None
    return (
        min(item[0] for item in items),
        min(item[1] for item in items),
        max(item[2] for item in items),
        max(item[3] for item in items),
    )


def bounds_intersect(left: Bounds, right: Bounds) -> bool:
    return not (
        left[2] < right[0]
        or left[0] > right[2]
        or left[3] < right[1]
        or left[1] > right[3]
    )


def parse_path_bounds(path_data: str) -> Bounds | None:
    """Conservative bounds using endpoints/control points and expanded arc radii."""
    tokens = PATH_TOKEN_RE.findall(path_data)
    if not tokens:
        return None
    i = 0
    command: str | None = None
    x = y = 0.0
    start_x = start_y = 0.0
    bounds = [math.inf, math.inf, -math.inf, -math.inf]
    have_point = False

    def include(px: float, py: float) -> None:
        nonlocal have_point
        _include_point(bounds, px, py)
        have_point = True

    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            command = token
            i += 1
            if command.upper() == "Z":
                include(start_x, start_y)
                x, y = start_x, start_y
                command = None
                continue
        if command is None:
            raise ValueError("path data contains numbers without a command")
        upper = command.upper()
        count = PATH_PARAMS.get(upper)
        if count is None or count == 0:
            raise ValueError(f"unsupported path command: {command}")
        if i + count > len(tokens) or any(value.isalpha() for value in tokens[i : i + count]):
            raise ValueError(f"incomplete path command: {command}")
        values = [float(value) for value in tokens[i : i + count]]
        i += count
        relative = command.islower()

        if upper == "M":
            x = values[0] + (x if relative else 0.0)
            y = values[1] + (y if relative else 0.0)
            start_x, start_y = x, y
            include(x, y)
            command = "l" if relative else "L"
            continue
        if upper == "L":
            x = values[0] + (x if relative else 0.0)
            y = values[1] + (y if relative else 0.0)
            include(x, y)
        elif upper == "H":
            x = values[0] + (x if relative else 0.0)
            include(x, y)
        elif upper == "V":
            y = values[0] + (y if relative else 0.0)
            include(x, y)
        elif upper == "C":
            absolute = [
                (values[j] + (x if relative else 0.0), values[j + 1] + (y if relative else 0.0))
                for j in (0, 2, 4)
            ]
            for px, py in absolute:
                include(px, py)
            x, y = absolute[-1]
        elif upper in {"S", "Q"}:
            absolute = [
                (values[j] + (x if relative else 0.0), values[j + 1] + (y if relative else 0.0))
                for j in (0, 2)
            ]
            for px, py in absolute:
                include(px, py)
            x, y = absolute[-1]
        elif upper == "T":
            x = values[0] + (x if relative else 0.0)
            y = values[1] + (y if relative else 0.0)
            include(x, y)
        elif upper == "A":
            rx, ry = abs(values[0]), abs(values[1])
            nx = values[5] + (x if relative else 0.0)
            ny = values[6] + (y if relative else 0.0)
            # Conservative for rotated arcs: expand by the larger radius around both endpoints.
            radius = max(rx, ry)
            include(x - radius, y - radius)
            include(x + radius, y + radius)
            include(nx - radius, ny - radius)
            include(nx + radius, ny + radius)
            x, y = nx, ny
    return tuple(bounds) if have_point else None  # type: ignore[return-value]


def numeric_attr(element: etree._Element, name: str, default: float = 0.0) -> float | None:
    value = element.get(name)
    if value is None:
        return default
    match = re.fullmatch(rf"\s*({NUM})(?:[A-Za-z%]+)?\s*", value)
    return float(match.group(1)) if match else None


def local_graphic_bounds(element: etree._Element) -> Bounds | None:
    name = local_name(element)
    if name == "path":
        return parse_path_bounds(element.get("d") or "")
    if name in {"polygon", "polyline"}:
        values = [float(value) for value in re.findall(NUM, element.get("points") or "")]
        if len(values) < 2 or len(values) % 2:
            return None
        xs = values[0::2]
        ys = values[1::2]
        return min(xs), min(ys), max(xs), max(ys)
    if name == "circle":
        cx = numeric_attr(element, "cx")
        cy = numeric_attr(element, "cy")
        radius = numeric_attr(element, "r")
        if cx is None or cy is None or radius is None or radius < 0:
            return None
        return cx - radius, cy - radius, cx + radius, cy + radius
    if name == "ellipse":
        cx = numeric_attr(element, "cx")
        cy = numeric_attr(element, "cy")
        rx = numeric_attr(element, "rx")
        ry = numeric_attr(element, "ry")
        if None in {cx, cy, rx, ry} or rx < 0 or ry < 0:  # type: ignore[operator]
            return None
        return cx - rx, cy - ry, cx + rx, cy + ry  # type: ignore[operator]
    if name in {"rect", "image"}:
        x = numeric_attr(element, "x")
        y = numeric_attr(element, "y")
        width = numeric_attr(element, "width")
        height = numeric_attr(element, "height")
        if None in {x, y, width, height} or width < 0 or height < 0:  # type: ignore[operator]
            return None
        return x, y, x + width, y + height  # type: ignore[operator]
    if name == "line":
        x1 = numeric_attr(element, "x1")
        y1 = numeric_attr(element, "y1")
        x2 = numeric_attr(element, "x2")
        y2 = numeric_attr(element, "y2")
        if None in {x1, y1, x2, y2}:
            return None
        return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)  # type: ignore[type-var]
    return None


def graphic_branch_bounds(
    element: etree._Element, parent_matrix: Matrix = IDENTITY_MATRIX
) -> tuple[Bounds | None, bool]:
    """Return conservative branch bounds and whether every renderable child was analyzable."""
    name = local_name(element)
    if not name or name in NONRENDERING_TAGS:
        return None, True
    local_matrix = parse_transform(element.get("transform"))
    if local_matrix is None:
        return None, False
    matrix = multiply_matrix(parent_matrix, local_matrix)

    if name in {"g", "a", "svg"}:
        child_bounds: list[Bounds] = []
        complete = True
        for child in element:
            bounds, child_complete = graphic_branch_bounds(child, matrix)
            complete = complete and child_complete
            if bounds is not None:
                child_bounds.append(bounds)
        return union_bounds(child_bounds), complete

    local_bounds = local_graphic_bounds(element)
    if local_bounds is None:
        # text/use/foreignObject and other renderable constructs are intentionally
        # not guessed. An enclosing branch containing them is not declared off-artboard.
        return None, False
    return transform_bounds(local_bounds, matrix), True


def analyze_off_artboard(root: etree._Element, report: SvgReport) -> None:
    viewport = parse_viewbox_bounds(root)
    if viewport is None:
        return
    for child in root:
        name = local_name(child)
        if not name or name in NONRENDERING_TAGS:
            continue
        try:
            bounds, complete = graphic_branch_bounds(child)
        except (ValueError, OverflowError):
            report.off_artboard_analysis_errors += 1
            continue
        if not complete or bounds is None or bounds_intersect(bounds, viewport):
            continue
        report.off_artboard_top_level_elements += 1
        report.off_artboard_bytes_estimate += len(etree.tostring(child, encoding="utf-8"))
        if name == "image":
            href = child.get(f"{{{XLINK}}}href") or child.get("href") or ""
            if href and not href.startswith("data:"):
                report.off_artboard_external_images += 1



CSS_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
CSS_DECL_RE = re.compile(r"([\w-]+)\s*:\s*([^;]+)")


def parse_style_declarations(text: str | None) -> dict[str, str]:
    if not text:
        return {}
    return {
        match.group(1).strip().lower(): match.group(2).strip()
        for match in CSS_DECL_RE.finditer(text)
    }


def parse_class_styles(root: etree._Element) -> dict[str, dict[str, str]]:
    """Parse simple `.class { ... }` rules used by Illustrator exports.

    Compound selectors are intentionally ignored rather than approximated.
    """
    styles: dict[str, dict[str, str]] = {}
    style_text = "\n".join(root.xpath(".//s:style/text()", namespaces=NS))
    for match in CSS_RULE_RE.finditer(style_text):
        declarations = parse_style_declarations(match.group(2))
        if not declarations:
            continue
        for selector in match.group(1).split(","):
            selector = selector.strip()
            class_match = re.fullmatch(r"\.([\w-]+)", selector)
            if class_match:
                styles.setdefault(class_match.group(1), {}).update(declarations)
    return styles


INHERITED_PAINT_PROPERTIES = {
    "fill",
    "fill-opacity",
    "stroke",
    "stroke-opacity",
    "stroke-width",
    "stroke-linecap",
    "stroke-linejoin",
    "stroke-miterlimit",
    "opacity",
}


def effective_paint_properties(
    element: etree._Element, class_styles: dict[str, dict[str, str]]
) -> dict[str, str]:
    props: dict[str, str] = {}
    chain = list(element.iterancestors())[::-1] + [element]
    for node in chain:
        classes = (node.get("class") or "").split()
        for class_name in classes:
            for key, value in class_styles.get(class_name, {}).items():
                if key in INHERITED_PAINT_PROPERTIES:
                    props[key] = value
        for key in INHERITED_PAINT_PROPERTIES:
            value = node.get(key)
            if value is not None:
                props[key] = value.strip()
        for key, value in parse_style_declarations(node.get("style")).items():
            if key in INHERITED_PAINT_PROPERTIES:
                props[key] = value
    return props


NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "green": (0, 128, 0),
    "blue": (0, 0, 255),
}


def parse_css_rgb(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    text = value.strip().lower()
    if text in {"none", "transparent", "currentcolor", "inherit", "initial"}:
        return None
    if text in NAMED_COLORS:
        return NAMED_COLORS[text]
    if text.startswith("#"):
        hex_value = text[1:]
        if len(hex_value) == 3:
            hex_value = "".join(char * 2 for char in hex_value)
        if len(hex_value) == 6 and re.fullmatch(r"[0-9a-f]{6}", hex_value):
            return tuple(int(hex_value[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
        return None
    match = re.fullmatch(
        r"rgb\(\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*\)",
        text,
    )
    if match:
        rgb = tuple(max(0, min(255, int(value))) for value in match.groups())
        return rgb  # type: ignore[return-value]
    return None


def color_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(3)))


def point_segment_distance_and_t(
    point: tuple[int, int, int],
    start: tuple[int, int, int],
    end: tuple[int, int, int],
) -> tuple[float, float]:
    vector = tuple(end[index] - start[index] for index in range(3))
    length_sq = sum(value * value for value in vector)
    if length_sq <= 0:
        return color_distance(point, start), 0.0
    offset = tuple(point[index] - start[index] for index in range(3))
    raw_t = sum(offset[index] * vector[index] for index in range(3)) / length_sq
    t = max(0.0, min(1.0, raw_t))
    projected = tuple(start[index] + t * vector[index] for index in range(3))
    distance = math.sqrt(sum((point[index] - projected[index]) ** 2 for index in range(3)))
    return distance, raw_t


def analyze_flat_fill_palette(
    root: etree._Element,
    report: SvgReport,
    class_styles: dict[str, dict[str, str]],
) -> None:
    path_counts: Counter[tuple[int, int, int]] = Counter()
    path_bytes: Counter[tuple[int, int, int]] = Counter()
    for path in root.xpath(".//s:path", namespaces=NS):
        props = effective_paint_properties(path, class_styles)
        fill = parse_css_rgb(props.get("fill"))
        if fill is None:
            continue
        path_data = path.get("d") or ""
        if not path_data:
            continue
        report.flat_fill_paths += 1
        path_counts[fill] += 1
        path_bytes[fill] += len(path_data.encode("utf-8"))

    colors = list(path_counts)
    report.distinct_flat_fill_colors = len(colors)
    if len(colors) < 2:
        return

    endpoint_distance_sq, start, end = max(
        (
            (sum((left[index] - right[index]) ** 2 for index in range(3)), left, right)
            for color_index, left in enumerate(colors)
            for right in colors[color_index + 1 :]
        ),
        key=lambda item: item[0],
    )
    report.palette_endpoint_distance = math.sqrt(endpoint_distance_sq)
    total_bytes = sum(path_bytes.values())
    line_bytes = 0
    intermediate_colors = 0
    intermediate_paths = 0
    intermediate_bytes = 0
    for color in colors:
        distance, t = point_segment_distance_and_t(color, start, end)
        if distance <= 8.0:
            line_bytes += path_bytes[color]
            if 0.02 < t < 0.98:
                intermediate_colors += 1
                intermediate_paths += path_counts[color]
                intermediate_bytes += path_bytes[color]

    report.palette_linearity_fraction = line_bytes / total_bytes if total_bytes else 0.0
    report.palette_intermediate_colors = intermediate_colors
    report.palette_intermediate_paths = intermediate_paths
    report.palette_intermediate_path_data_bytes = intermediate_bytes


def normalized_matrix(matrix: Matrix | None) -> tuple[float, ...] | None:
    if matrix is None:
        return None
    return tuple(round(value, 9) for value in matrix)


def analyze_duplicate_fill_stroke_geometry(
    root: etree._Element,
    report: SvgReport,
    class_styles: dict[str, dict[str, str]],
) -> None:
    groups: dict[tuple[str, tuple[float, ...]], list[tuple[str, tuple[int, int, int], int]]] = {}
    for path in root.xpath(".//s:path", namespaces=NS):
        path_data = path.get("d") or ""
        if not path_data:
            continue
        matrix = normalized_matrix(cumulative_transform(path))
        if matrix is None:
            continue
        props = effective_paint_properties(path, class_styles)
        fill_text = (props.get("fill") or "black").strip().lower()
        stroke_text = (props.get("stroke") or "none").strip().lower()
        fill = parse_css_rgb(fill_text)
        stroke = parse_css_rgb(stroke_text)
        opacity = (props.get("opacity") or "1").strip()
        fill_opacity = (props.get("fill-opacity") or "1").strip()
        stroke_opacity = (props.get("stroke-opacity") or "1").strip()
        if opacity not in {"1", "1.0", "1.00"}:
            continue
        if fill is not None and stroke is None and fill_opacity in {"1", "1.0", "1.00"}:
            paint = ("fill", fill, len(path_data.encode("utf-8")))
        elif fill_text == "none" and stroke is not None and stroke_opacity in {"1", "1.0", "1.00"}:
            paint = ("stroke", stroke, len(path_data.encode("utf-8")))
        else:
            continue
        groups.setdefault((path_data, matrix), []).append(paint)

    for (path_data, _matrix), paints in groups.items():
        fills = Counter(color for kind, color, _size in paints if kind == "fill")
        strokes = Counter(color for kind, color, _size in paints if kind == "stroke")
        for color in fills.keys() & strokes.keys():
            pairs = min(fills[color], strokes[color])
            report.duplicate_fill_stroke_pairs += pairs
            report.duplicate_fill_stroke_path_data_bytes += (
                len(path_data.encode("utf-8")) * pairs
            )

def classify(report: SvgReport) -> None:
    if report.parse_error:
        report.classification = "parse-error"
        report.severity = "error"
        report.signals.append(report.parse_error)
        return

    gradient_total = report.linear_gradients + report.radial_gradients
    embedded_fraction = (
        report.embedded_image_bytes_estimate / report.size_bytes if report.size_bytes else 0.0
    )
    palette_ratio = report.gradient_palettes / gradient_total if gradient_total else 1.0

    # Strongest evidence: the raw Illustrator source still contains grouped blend stacks
    # matching the experimentally verified Ruby Monday structure.
    if report.confirmed_blend_stacks:
        report.classification = "flattened-blend-stack"
        report.severity = "high"
        stack_desc = ", ".join(
            f"{stack.steps}x{stack.glyphs_per_step}" for stack in report.confirmed_blend_stacks
        )
        report.signals.append(f"confirmed translated blend stacks: {stack_desc}")

    # Fallback for minified assets where group structure has been removed.
    elif (
        report.linear_gradients >= 250
        and report.geometry_elements >= 250
        and report.gradient_palettes <= 12
        and palette_ratio <= 0.05
        and report.embedded_images == 0
    ):
        report.classification = "likely-flattened-blend"
        report.severity = "high"
        report.signals.append(
            f"{report.linear_gradients} linear gradients collapse to "
            f"{report.gradient_palettes} stop palettes"
        )
        report.signals.append(
            f"{report.geometry_elements} path/polygon elements accompany gradient explosion"
        )

    # Guijia-family signature. Keep thresholds broad enough to find variants while
    # retaining all component signals in the report for later corpus tuning.
    elif (
        report.linear_gradients >= 40
        and report.gradient_palettes <= 3
        and report.circles >= 20
        and report.masks >= 1
        and report.filters >= 1
        and report.embedded_images >= 1
        and (report.embedded_image_bytes_estimate >= 100_000 or embedded_fraction >= 0.25)
    ):
        report.classification = "flattened-gradient-mask"
        report.severity = "high"
        report.signals.append(
            f"{report.linear_gradients} linear gradients collapse to "
            f"{report.gradient_palettes} stop palette(s)"
        )
        report.signals.append(
            f"{report.masks} masks + {report.filters} filters + "
            f"{report.embedded_images} embedded image(s)"
        )
        report.signals.append(
            f"embedded raster payload ~{report.embedded_image_bytes_estimate} bytes "
            f"({embedded_fraction:.1%} of SVG size)"
        )

    # Wolfgang-style pathological compound paths: tens of thousands of tiny closed
    # contours dominate a very large path payload. This is intentionally a much
    # stronger signature than plain "large path data" so detailed normal artwork is
    # not conflated with distressed/traced-outline explosions.
    elif (
        report.path_data_bytes >= 250_000
        and report.path_segment_count >= 50_000
        and report.closed_path_subpaths >= 5_000
        and report.micro_subpath_fraction >= 0.50
        and report.vector_data_fraction >= 0.50
        and report.embedded_images == 0
        and gradient_total == 0
    ):
        report.classification = "micro-contour-explosion"
        report.severity = "high"
        report.signals.append(
            f"{report.closed_path_subpaths} closed subpaths; "
            f"{report.micro_subpaths} ({report.micro_subpath_fraction:.1%}) fit within "
            f"{report.micro_subpath_span:.4g} SVG units"
        )
        report.signals.append(
            f"{report.path_segment_count} parsed path segments in "
            f"~{report.path_data_bytes} bytes of path data"
        )
        if report.paths_with_100_subpaths:
            report.signals.append(
                f"{report.paths_with_100_subpaths} compound paths contain >=100 subpaths; "
                f"maximum {report.max_subpaths_in_path}"
            )

    # Exact structural debris: large top-level graphic branches whose conservative
    # transformed bounds cannot intersect the document viewBox. This is intentionally
    # based only on fully analyzable branches; unsupported text/use content is skipped.
    elif (
        report.off_artboard_bytes_estimate >= 50_000
        and report.off_artboard_fraction >= 0.20
    ):
        report.classification = "off-artboard-content"
        report.severity = "medium"
        report.signals.append(
            f"{report.off_artboard_top_level_elements} top-level graphic branch(es) are "
            f"wholly outside the viewBox; ~{report.off_artboard_bytes_estimate} bytes "
            f"({report.off_artboard_fraction:.1%} of SVG size)"
        )
        if report.off_artboard_external_images:
            report.signals.append(
                f"off-artboard external images: {report.off_artboard_external_images}"
            )

    # Exact duplicate path geometry where one copy paints the fill and another paints
    # the same-colour stroke. The paths can be represented by one fill+stroke element.
    elif (
        report.duplicate_fill_stroke_pairs >= 8
        and report.duplicate_fill_stroke_path_data_bytes >= 4_000
    ):
        report.classification = "duplicate-fill-stroke-geometry"
        report.severity = "medium"
        report.signals.append(
            f"{report.duplicate_fill_stroke_pairs} exact fill/stroke path pair(s); "
            f"~{report.duplicate_fill_stroke_path_data_bytes} bytes of duplicated path data"
        )

    # Shaolin-style raster/vector trace signature: many flat colours lie almost entirely
    # on one RGB interpolation axis, with numerous intermediate shades represented by
    # small paths. Coupled with persistent subpixel geometry this is strong evidence that
    # antialiased raster pixels were traced back into vector shapes.
    elif (
        gradient_total == 0
        and report.flat_fill_paths >= 100
        and report.distinct_flat_fill_colors >= 16
        and report.palette_endpoint_distance >= 120.0
        and report.palette_linearity_fraction >= 0.90
        and report.palette_intermediate_colors >= 8
        and report.palette_intermediate_paths >= 25
        and report.subpixel_path_data_fraction_256 >= 0.15
    ):
        report.classification = "palette-fragmented-trace"
        report.severity = "medium"
        report.signals.append(
            f"{report.distinct_flat_fill_colors} flat fill colours; "
            f"{report.palette_linearity_fraction:.1%} of flat-fill path data lies near one "
            "RGB interpolation axis"
        )
        report.signals.append(
            f"{report.palette_intermediate_colors} intermediate colours occur across "
            f"{report.palette_intermediate_paths} path(s); persistent subpixel path data "
            f"at 256 px={report.subpixel_path_data_fraction_256:.1%}"
        )

    # Other useful standalone issue classes. These remain deliberately broad and
    # detection-only: they identify assets worth inspecting without guessing how
    # they should be rewritten.
    elif report.embedded_image_bytes_estimate >= 100_000 and embedded_fraction >= 0.40:
        report.classification = "embedded-raster-heavy"
        report.severity = "medium"
        report.signals.append(
            f"embedded raster payload ~{report.embedded_image_bytes_estimate} bytes "
            f"({embedded_fraction:.1%} of SVG size)"
        )

    elif (
        report.path_data_bytes >= 250_000
        and report.vector_data_fraction >= 0.50
        and report.embedded_images == 0
        and gradient_total == 0
    ):
        report.classification = "oversized-path-data"
        report.severity = "medium"
        report.signals.append(
            f"path/polygon data ~{report.vector_data_bytes} bytes "
            f"({report.vector_data_fraction:.1%} of SVG size)"
        )
        report.signals.append(
            f"largest single path data payload ~{report.largest_path_data_bytes} bytes"
        )

    # Supporting warnings for assets that do not yet fit a known class.
    if gradient_total >= 250:
        report.signals.append(f"gradient explosion: {gradient_total} gradients")
    if report.geometry_elements >= 500:
        report.signals.append(f"geometry explosion: {report.geometry_elements} paths/polygons")
    if report.embedded_image_bytes_estimate >= 100_000:
        report.signals.append(
            f"large embedded raster payload: ~{report.embedded_image_bytes_estimate} bytes"
        )
    if report.embedded_pngs_analyzed:
        if report.embedded_monochrome_alpha_images:
            report.signals.append(
                f"effectively single-colour alpha PNGs: {report.embedded_monochrome_alpha_images}/"
                f"{report.embedded_pngs_analyzed} analyzed"
            )
        if report.embedded_disc_like_images or report.embedded_ring_like_images:
            report.signals.append(
                f"simple alpha primitives: {report.embedded_disc_like_images} disc-like + "
                f"{report.embedded_ring_like_images} ring-like"
            )
    if report.embedded_raster_analysis_errors:
        report.signals.append(
            "deep raster analysis skipped/failed for "
            f"{report.embedded_raster_analysis_errors} image(s)"
        )
    if report.off_artboard_bytes_estimate >= 10_000:
        report.signals.append(
            f"off-artboard top-level content: {report.off_artboard_top_level_elements} branch(es), "
            f"~{report.off_artboard_bytes_estimate} bytes"
        )
    if report.off_artboard_analysis_errors:
        report.signals.append(
            f"off-artboard bounds analysis skipped/failed for "
            f"{report.off_artboard_analysis_errors} branch(es)"
        )
    if report.path_data_bytes >= 100_000:
        report.signals.append(f"large path data payload: ~{report.path_data_bytes} bytes")
    if report.largest_path_data_bytes >= 100_000:
        report.signals.append(
            f"very large single path: ~{report.largest_path_data_bytes} bytes"
        )
    if report.closed_path_subpaths >= 1_000:
        report.signals.append(
            f"compound-path density: {report.closed_path_subpaths} closed subpaths"
        )
    if report.micro_subpath_fraction >= 0.50 and report.closed_path_subpaths >= 500:
        report.signals.append(
            f"micro-contour concentration: {report.micro_subpath_fraction:.1%} of closed subpaths"
        )
    if report.repeated_subpath_count_groups >= 3:
        report.signals.append(
            "repeated compound-path contour counts: "
            f"{report.repeated_subpath_count_groups} groups, "
            f"{report.repeated_subpath_count_members} path members"
        )
    if report.path_analysis_errors:
        report.signals.append(
            f"path contour analysis skipped/failed for {report.path_analysis_errors} path(s)"
        )
    if gradient_total >= 40 and report.gradient_palettes > 0 and palette_ratio <= 0.10:
        report.signals.append(
            f"high gradient palette repetition: {report.gradient_palettes}/{gradient_total} unique"
        )

    if report.external_images_existing or report.external_images_remote:
        report.advisories.append("external-image-reference")
        parts: list[str] = []
        if report.external_images_existing:
            parts.append(f"{report.external_images_existing} local target(s) present")
        if report.external_images_remote:
            parts.append(f"{report.external_images_remote} remote/non-local reference(s)")
        report.signals.append(
            "external image reference(s): " + ", ".join(parts) + "; SVG is not fully self-contained"
        )
    if report.external_images_missing:
        report.advisories.append("missing-external-image")
        missing = ", ".join(report.external_image_missing_references[:4])
        if report.external_images_missing > 4:
            missing += f", +{report.external_images_missing - 4} more"
        report.signals.append(
            f"missing external image target(s): {report.external_images_missing}"
            + (f" ({missing})" if missing else "")
        )
    if report.duplicate_fill_stroke_pairs and report.classification != "duplicate-fill-stroke-geometry":
        report.signals.append(
            f"exact duplicate fill/stroke geometry: {report.duplicate_fill_stroke_pairs} pair(s), "
            f"~{report.duplicate_fill_stroke_path_data_bytes} duplicated path-data bytes"
        )
    palette_fragmentation_signal = (
        gradient_total == 0
        and report.distinct_flat_fill_colors >= 12
        and report.palette_endpoint_distance >= 120.0
        and report.palette_linearity_fraction >= 0.85
    )
    if palette_fragmentation_signal:
        report.signals.append(
            f"fragmented flat palette: {report.distinct_flat_fill_colors} colours; "
            f"{report.palette_linearity_fraction:.1%} path-data linearity"
        )

    # Mild version of the Shaolin signature. This intentionally remains advisory-only:
    # it catches Qapu-like files where a traced-antialias palette is detectable but the
    # amount of affected geometry is too small to justify the stronger classification.
    if (
        report.classification != "palette-fragmented-trace"
        and palette_fragmentation_signal
        and report.palette_linearity_fraction >= 0.90
        and report.palette_intermediate_colors >= 5
        and report.palette_intermediate_paths >= 5
    ):
        report.advisories.append("palette-fragmentation")
        report.signals.append(
            f"palette-fragmentation advisory: {report.palette_intermediate_colors} "
            f"intermediate colours across {report.palette_intermediate_paths} path(s); "
            f"~{report.palette_intermediate_path_data_bytes} path-data bytes"
        )

    # Conservative path-payload advisory. This is intentionally weaker than the
    # oversized-path-data classification: it surfaces medium-sized outliers such as
    # Denma Connolly without asserting that detailed vector geometry is pathological.
    # Corpus tuning showed that >=100 KiB at >=90% of the whole SVG isolates this
    # review class while ordinary detailed symbols remain below the threshold.
    if (
        report.classification is None
        and gradient_total == 0
        and report.embedded_images == 0
        and report.path_data_bytes >= 100_000
        and report.vector_data_fraction >= 0.90
        and report.largest_path_data_bytes >= 20_000
    ):
        report.advisories.append("large-path-payload")
        report.signals.append(
            f"large-path-payload advisory: ~{report.vector_data_bytes} vector-data bytes "
            f"({report.vector_data_fraction:.1%} of SVG); largest path "
            f"~{report.largest_path_data_bytes} bytes"
        )

    # Target-size advisory: significant path payload is spent on closed features whose
    # estimated 2A/P width is below one rendered pixel at 128 px. This is deliberately
    # advisory-only because engraving and intentional fine detail can have the same shape.
    if (
        report.classification is None
        and report.subpixel_closed_subpaths_128 >= 20
        and report.subpixel_path_data_bytes_estimate_128 >= 8_000
        and report.subpixel_path_data_fraction_128 >= 0.05
    ):
        report.advisories.append("subpixel-detail-heavy")
        report.signals.append(
            "subpixel-detail-heavy: "
            f"at 128 px, {report.subpixel_closed_subpaths_128} closed contours "
            f"({report.subpixel_closed_subpath_fraction_128:.1%}) have estimated width <1 px; "
            f"~{report.subpixel_path_data_bytes_estimate_128} path-data bytes "
            f"({report.subpixel_path_data_fraction_128:.1%}) are associated with them"
        )

    # Flag generic suspicious files too, but keep them separate from known classes.
    if report.classification is None and (
        gradient_total >= 250
        or report.geometry_elements >= 500
        or report.embedded_image_bytes_estimate >= 250_000
        or (report.off_artboard_bytes_estimate >= 100_000 and report.off_artboard_fraction >= 0.20)
        or (report.path_data_bytes >= 250_000 and report.vector_data_fraction >= 0.50)
        or (
            report.closed_path_subpaths >= 5_000
            and report.micro_subpath_fraction >= 0.50
        )
    ):
        report.classification = "suspicious-structure"
        report.severity = "medium"

def resolve_external_image_reference(svg_path: Path, href: str) -> str:
    """Classify an external image href as existing, missing, or remote/non-local.

    Relative references are resolved against the SVG directory. Local file: URLs and
    ordinary filesystem paths are checked without performing any network access.
    """
    raw = href.strip()
    if not raw or raw.startswith("#"):
        return "remote"

    # Windows drive-letter paths look like URL schemes to urlsplit(), so handle them first.
    if re.match(r"^[A-Za-z]:[\\/]", raw):
        return "existing" if Path(raw).is_file() else "missing"

    parsed = urlsplit(raw)
    scheme = parsed.scheme.lower()
    if scheme and scheme != "file":
        return "remote"

    if scheme == "file":
        file_path = url2pathname(unquote(parsed.path))
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            file_path = f"//{parsed.netloc}{file_path}"
        # url2pathname on Windows-style file:///C:/... may retain a leading slash
        # when executed on a non-Windows host; Path existence is all we need here.
        candidate = Path(file_path)
    else:
        local_text = unquote(parsed.path)
        candidate = Path(local_text)
        if not candidate.is_absolute():
            candidate = svg_path.parent / candidate

    return "existing" if candidate.is_file() else "missing"


def scan_file(
    path: Path,
    display_path: str,
    *,
    confirm_blends: bool,
    geometry_tolerance: float,
    translation_tolerance: float,
    deep_raster: bool,
    micro_contour_span_ratio: float,
    small_contour_span_ratio: float,
    subpixel_detail: bool,
    subpixel_min_path_data_bytes: int,
    subpixel_curve_samples: int,
) -> SvgReport:
    report = SvgReport(
        path=display_path,
        size_bytes=path.stat().st_size,
        sha256=sha256_file(path),
    )
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        recover=False,
        huge_tree=True,
        remove_blank_text=False,
    )
    try:
        tree = etree.parse(str(path), parser)
    except (etree.XMLSyntaxError, OSError) as exc:
        report.parse_error = str(exc).splitlines()[0]
        classify(report)
        return report

    root = tree.getroot()
    counts = Counter(local_name(element) for element in root.iter())
    report.paths = counts["path"]
    report.polygons = counts["polygon"]
    report.circles = counts["circle"]
    report.groups = counts["g"]
    report.uses = counts["use"]
    report.linear_gradients = counts["linearGradient"]
    report.radial_gradients = counts["radialGradient"]
    report.masks = counts["mask"]
    report.filters = counts["filter"]
    report.clip_paths = counts["clipPath"]
    report.images = counts["image"]

    analyze_off_artboard(root, report)
    class_styles = parse_class_styles(root)
    analyze_flat_fill_palette(root, report, class_styles)
    analyze_duplicate_fill_stroke_geometry(root, report, class_styles)

    report.viewbox_max_dimension = parse_viewbox_max_dimension(root)
    report.micro_subpath_span = report.viewbox_max_dimension * micro_contour_span_ratio
    report.small_subpath_span = report.viewbox_max_dimension * small_contour_span_ratio
    degenerate_span = max(report.viewbox_max_dimension * 1e-7, 1e-9)

    path_sizes: list[int] = []
    subpath_counts: list[int] = []
    path_records: list[tuple[etree._Element, str, int]] = []
    for path_element in root.xpath(".//s:path", namespaces=NS):
        path_data = path_element.get("d") or ""
        size = len(path_data.encode("utf-8"))
        path_sizes.append(size)
        path_records.append((path_element, path_data, size))
        report.path_command_count += len(PATH_COMMAND_RE.findall(path_data))
        try:
            subpaths, segment_count = analyze_path_subpaths(path_data)
        except (ValueError, OverflowError):
            report.path_analysis_errors += 1
            continue
        report.path_segment_count += segment_count
        subpath_counts.append(len(subpaths))
        report.path_subpaths += len(subpaths)
        report.max_subpaths_in_path = max(report.max_subpaths_in_path, len(subpaths))
        if len(subpaths) >= 100:
            report.paths_with_100_subpaths += 1
        for span, closed in subpaths:
            if not closed:
                continue
            report.closed_path_subpaths += 1
            if span <= degenerate_span:
                report.degenerate_subpaths += 1
            if report.micro_subpath_span > 0 and span <= report.micro_subpath_span:
                report.micro_subpaths += 1
            if report.small_subpath_span > 0 and span <= report.small_subpath_span:
                report.small_subpaths += 1

    report.path_data_bytes = sum(path_sizes)
    report.largest_path_data_bytes = max(path_sizes, default=0)
    report.polygon_points_bytes = sum(
        len((polygon.get("points") or "").encode("utf-8"))
        for polygon in root.xpath(".//s:polygon", namespaces=NS)
    )

    if (
        subpixel_detail
        and report.viewbox_max_dimension > 0
        and report.path_data_bytes >= subpixel_min_path_data_bytes
    ):
        thresholds = {
            64: report.viewbox_max_dimension / 64.0,
            128: report.viewbox_max_dimension / 128.0,
            256: report.viewbox_max_dimension / 256.0,
        }
        count_by_size = {64: 0, 128: 0, 256: 0}
        bytes_by_size = {64: 0.0, 128: 0.0, 256: 0.0}
        for path_element, path_data, path_size in path_records:
            matrix = cumulative_transform(path_element)
            if matrix is None:
                report.subpixel_detail_analysis_errors += 1
                continue
            try:
                widths, total_segments = analyze_path_feature_widths(
                    path_data,
                    matrix,
                    curve_samples=subpixel_curve_samples,
                )
            except (ValueError, OverflowError, ZeroDivisionError):
                report.subpixel_detail_analysis_errors += 1
                continue
            report.subpixel_detail_paths_analyzed += 1
            if total_segments <= 0 or not widths:
                continue
            for render_size, threshold in thresholds.items():
                selected = [(width, segments) for width, segments in widths if width < threshold]
                count_by_size[render_size] += len(selected)
                selected_segments = sum(segments for _width, segments in selected)
                bytes_by_size[render_size] += path_size * selected_segments / total_segments

        report.subpixel_closed_subpaths_64 = count_by_size[64]
        report.subpixel_closed_subpaths_128 = count_by_size[128]
        report.subpixel_closed_subpaths_256 = count_by_size[256]
        report.subpixel_path_data_bytes_estimate_64 = round(bytes_by_size[64])
        report.subpixel_path_data_bytes_estimate_128 = round(bytes_by_size[128])
        report.subpixel_path_data_bytes_estimate_256 = round(bytes_by_size[256])

    repeated_counts = Counter(count for count in subpath_counts if count >= 20)
    repeated = {count: members for count, members in repeated_counts.items() if members >= 2}
    report.repeated_subpath_count_groups = len(repeated)
    report.repeated_subpath_count_members = sum(repeated.values())

    gradients = {
        gradient.get("id"): gradient
        for gradient in root.xpath(".//s:linearGradient", namespaces=NS)
        if gradient.get("id")
    }
    palette_counts = Counter(
        resolve_gradient_stops(gradients, gradient_id) for gradient_id in gradients
    )
    # Empty unresolved palettes are still structurally useful, but don't let a mass of
    # empty gradients disguise the number of actual stop palettes.
    nonempty_palette_counts = Counter(
        {palette: count for palette, count in palette_counts.items() if palette}
    )
    effective = nonempty_palette_counts or palette_counts
    report.gradient_palettes = len(effective)
    families = sorted(effective.values(), reverse=True)
    report.largest_palette_family = families[0] if families else 0
    report.top3_palette_family = sum(families[:3])
    gradient_total = report.linear_gradients + report.radial_gradients
    report.palette_repetition_ratio = (
        1.0 - report.gradient_palettes / gradient_total if gradient_total else 0.0
    )

    deep_raster_for_file = deep_raster and not (
        report.linear_gradients >= 40
        and report.circles >= 20
        and report.masks >= 1
        and report.filters >= 1
    )
    for image in root.xpath(".//s:image", namespaces=NS):
        href = image.get(f"{{{XLINK}}}href") or image.get("href") or ""
        if not href.startswith("data:"):
            if href:
                report.external_images += 1
                report.external_image_references.append(href)
                status = resolve_external_image_reference(path, href)
                if status == "existing":
                    report.external_images_existing += 1
                elif status == "missing":
                    report.external_images_missing += 1
                    report.external_image_missing_references.append(href)
                else:
                    report.external_images_remote += 1
            continue
        report.embedded_images += 1
        report.embedded_image_bytes_estimate += estimate_data_url_bytes(href)
        decoded_url = decode_data_url(href)
        if decoded_url is None:
            continue
        media_type, data = decoded_url
        if media_type != "image/png" and not data.startswith(PNG_SIGNATURE):
            continue
        report.embedded_pngs += 1
        if not deep_raster_for_file:
            continue
        raster = analyze_embedded_png(data)
        if raster is None:
            report.embedded_raster_analysis_errors += 1
            continue
        report.embedded_pngs_analyzed += 1
        monochrome_alpha, primitive = raster
        if monochrome_alpha:
            report.embedded_monochrome_alpha_images += 1
        if primitive == "disc":
            report.embedded_disc_like_images += 1
        elif primitive == "ring":
            report.embedded_ring_like_images += 1

    # Exact grouped confirmation is only worth doing on already gradient-heavy files.
    if confirm_blends and report.linear_gradients >= 100 and report.groups >= 20:
        style_text = "\n".join(root.xpath(".//s:style/text()", namespaces=NS))
        class_fill = {
            match.group(1): match.group(2)
            for match in CLASS_FILL_RE.finditer(style_text)
        }
        if class_fill:
            for group in root.xpath(".//s:g", namespaces=NS):
                evidence = analyze_blend_stack(
                    group,
                    class_fill,
                    gradients,
                    geometry_tolerance,
                    translation_tolerance,
                )
                if evidence is not None:
                    report.confirmed_blend_stacks.append(evidence)

    classify(report)
    return report

def iter_svg_paths(root: Path, recursive: bool) -> Iterable[Path]:
    if root.is_file():
        if root.suffix.lower() == ".svg":
            yield root
        return
    pattern = "**/*.svg" if recursive else "*.svg"
    yield from sorted(path for path in root.glob(pattern) if path.is_file())


def human_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def print_report(reports: list[SvgReport], *, show_all: bool) -> None:
    visible = reports if show_all else [report for report in reports if report.flagged]
    if not visible:
        print("No suspicious SVG structures detected.")
        return

    severity_rank = {"error": 0, "high": 1, "medium": 2, None: 3}
    visible = sorted(
        visible,
        key=lambda report: (severity_rank.get(report.severity, 9), -report.size_bytes, report.path),
    )
    for report in visible:
        if report.parse_error:
            print(f"[ERROR] {report.path}")
            print(f"  {report.parse_error}")
            continue
        if report.classification:
            label = report.classification.upper()
        elif report.advisories:
            label = "ADVISORY:" + ",".join(report.advisories).upper()
        else:
            label = "OK"
        print(f"[{label}] {report.path}")
        print(
            "  "
            f"{human_bytes(report.size_bytes)} | paths/polygons={report.geometry_elements} | "
            f"circles={report.circles} | "
            f"gradients={report.linear_gradients + report.radial_gradients} | "
            f"palettes={report.gradient_palettes} | masks={report.masks} | "
            f"filters={report.filters} | embedded-images={report.embedded_images} | "
            f"external-images={report.external_images} (present={report.external_images_existing}, missing={report.external_images_missing}, remote={report.external_images_remote}) | palette-colors={report.distinct_flat_fill_colors} | "
            f"dup-fill-stroke={report.duplicate_fill_stroke_pairs} | "
            f"subpaths={report.path_subpaths} | vector-data={human_bytes(report.vector_data_bytes)} | "
            f"off-artboard={human_bytes(report.off_artboard_bytes_estimate)} | "
            f"subpixel@128={report.subpixel_closed_subpaths_128}"
        )
        for signal in dict.fromkeys(report.signals):
            print(f"  - {signal}")


def report_to_dict(report: SvgReport) -> dict[str, Any]:
    data = asdict(report)
    data["geometry_elements"] = report.geometry_elements
    data["vector_data_bytes"] = report.vector_data_bytes
    data["vector_data_fraction"] = report.vector_data_fraction
    data["micro_subpath_fraction"] = report.micro_subpath_fraction
    data["small_subpath_fraction"] = report.small_subpath_fraction
    data["embedded_monochrome_fraction"] = report.embedded_monochrome_fraction
    data["off_artboard_fraction"] = report.off_artboard_fraction
    data["subpixel_closed_subpath_fraction_64"] = report.subpixel_closed_subpath_fraction_64
    data["subpixel_closed_subpath_fraction_128"] = report.subpixel_closed_subpath_fraction_128
    data["subpixel_closed_subpath_fraction_256"] = report.subpixel_closed_subpath_fraction_256
    data["subpixel_path_data_fraction_64"] = report.subpixel_path_data_fraction_64
    data["subpixel_path_data_fraction_128"] = report.subpixel_path_data_fraction_128
    data["subpixel_path_data_fraction_256"] = report.subpixel_path_data_fraction_256
    data["flagged"] = report.flagged
    return data


def write_json(
    path: Path,
    summary: ScanSummary,
    reports: list[SvgReport],
    duplicate_groups: list[dict[str, Any]],
) -> None:
    payload = {
        "summary": asdict(summary),
        "duplicate_groups": duplicate_groups,
        "files": [report_to_dict(report) for report in reports],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path: Path, reports: list[SvgReport]) -> None:
    fieldnames = [
        "path",
        "size_bytes",
        "sha256",
        "exact_duplicate_group_size",
        "classification",
        "severity",
        "paths",
        "polygons",
        "circles",
        "groups",
        "uses",
        "linear_gradients",
        "radial_gradients",
        "gradient_palettes",
        "largest_palette_family",
        "top3_palette_family",
        "palette_repetition_ratio",
        "masks",
        "filters",
        "clip_paths",
        "images",
        "embedded_images",
        "embedded_image_bytes_estimate",
        "embedded_pngs",
        "embedded_pngs_analyzed",
        "embedded_monochrome_alpha_images",
        "embedded_monochrome_fraction",
        "embedded_disc_like_images",
        "embedded_ring_like_images",
        "embedded_raster_analysis_errors",
        "external_images",
        "external_images_existing",
        "external_images_missing",
        "external_images_remote",
        "external_image_references",
        "external_image_missing_references",
        "off_artboard_top_level_elements",
        "off_artboard_bytes_estimate",
        "off_artboard_fraction",
        "off_artboard_external_images",
        "off_artboard_analysis_errors",
        "path_data_bytes",
        "largest_path_data_bytes",
        "path_command_count",
        "path_segment_count",
        "polygon_points_bytes",
        "path_subpaths",
        "closed_path_subpaths",
        "degenerate_subpaths",
        "micro_subpaths",
        "micro_subpath_fraction",
        "small_subpaths",
        "small_subpath_fraction",
        "paths_with_100_subpaths",
        "max_subpaths_in_path",
        "repeated_subpath_count_groups",
        "repeated_subpath_count_members",
        "path_analysis_errors",
        "viewbox_max_dimension",
        "micro_subpath_span",
        "small_subpath_span",
        "subpixel_detail_paths_analyzed",
        "subpixel_detail_analysis_errors",
        "subpixel_closed_subpaths_64",
        "subpixel_closed_subpath_fraction_64",
        "subpixel_closed_subpaths_128",
        "subpixel_closed_subpath_fraction_128",
        "subpixel_closed_subpaths_256",
        "subpixel_closed_subpath_fraction_256",
        "subpixel_path_data_bytes_estimate_64",
        "subpixel_path_data_fraction_64",
        "subpixel_path_data_bytes_estimate_128",
        "subpixel_path_data_fraction_128",
        "subpixel_path_data_bytes_estimate_256",
        "subpixel_path_data_fraction_256",
        "flat_fill_paths",
        "distinct_flat_fill_colors",
        "palette_endpoint_distance",
        "palette_linearity_fraction",
        "palette_intermediate_colors",
        "palette_intermediate_paths",
        "palette_intermediate_path_data_bytes",
        "duplicate_fill_stroke_pairs",
        "duplicate_fill_stroke_path_data_bytes",
        "vector_data_bytes",
        "vector_data_fraction",
        "confirmed_blend_stacks",
        "advisories",
        "signals",
        "parse_error",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for report in reports:
            row = report_to_dict(report)
            row["confirmed_blend_stacks"] = ";".join(
                f"{stack.steps}x{stack.glyphs_per_step}" for stack in report.confirmed_blend_stacks
            )
            row["external_image_references"] = ";".join(report.external_image_references)
            row["external_image_missing_references"] = ";".join(
                report.external_image_missing_references
            )
            row["advisories"] = ";".join(report.advisories)
            row["signals"] = " | ".join(report.signals)
            writer.writerow({key: row.get(key) for key in fieldnames})


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recursively scan SVGs for suspicious or wasteful SVG structures (v8.8)."
    )
    parser.add_argument("input", type=Path, help="SVG file or folder to scan")
    parser.add_argument("--no-recursive", action="store_true", help="scan only the input folder")
    parser.add_argument("--all", action="store_true", help="print unflagged files too")
    parser.add_argument("--json", type=Path, help="write a machine-readable JSON report")
    parser.add_argument("--csv", type=Path, help="write a CSV report")
    parser.add_argument(
        "--no-confirm-blends",
        action="store_true",
        help="skip the deeper preserved-group blend confirmation pass",
    )
    parser.add_argument(
        "--no-deep-raster",
        action="store_true",
        help="skip pixel-level analysis of supported embedded PNGs",
    )
    parser.add_argument("--geometry-tolerance", type=float, default=0.011)
    parser.add_argument("--translation-tolerance", type=float, default=0.021)
    parser.add_argument(
        "--micro-contour-span-ratio",
        type=float,
        default=0.0002,
        help=(
            "micro-contour max span as a fraction of the SVG viewBox max dimension "
            "(default: 0.0002)"
        ),
    )
    parser.add_argument(
        "--small-contour-span-ratio",
        type=float,
        default=0.0005,
        help=(
            "small-contour max span as a fraction of the SVG viewBox max dimension "
            "(default: 0.0005)"
        ),
    )
    parser.add_argument(
        "--no-subpixel-detail",
        action="store_true",
        help="skip target-size closed-contour feature-width analysis",
    )
    parser.add_argument(
        "--subpixel-min-path-data-bytes",
        type=int,
        default=20_000,
        help="minimum path-data payload before subpixel analysis runs (default: 20000)",
    )
    parser.add_argument(
        "--subpixel-curve-samples",
        type=int,
        default=6,
        help="minimum polygonization samples per curve for subpixel analysis (default: 6)",
    )
    args = parser.parse_args()
    if args.micro_contour_span_ratio < 0 or args.small_contour_span_ratio < 0:
        parser.error("contour span ratios must be non-negative")
    if args.small_contour_span_ratio < args.micro_contour_span_ratio:
        parser.error("--small-contour-span-ratio must be >= --micro-contour-span-ratio")
    if args.subpixel_min_path_data_bytes < 0:
        parser.error("--subpixel-min-path-data-bytes must be non-negative")
    if args.subpixel_curve_samples < 2:
        parser.error("--subpixel-curve-samples must be >= 2")

    root = args.input.resolve()
    if not root.exists():
        parser.error(f"input does not exist: {args.input}")

    paths = list(iter_svg_paths(root, recursive=not args.no_recursive))
    if not paths:
        print("No SVG files found.", file=sys.stderr)
        return 2

    base = root if root.is_dir() else root.parent
    reports: list[SvgReport] = []
    for path in paths:
        try:
            display_path = str(path.relative_to(base))
        except ValueError:
            display_path = str(path)
        reports.append(
            scan_file(
                path,
                display_path,
                confirm_blends=not args.no_confirm_blends,
                geometry_tolerance=args.geometry_tolerance,
                translation_tolerance=args.translation_tolerance,
                deep_raster=not args.no_deep_raster,
                micro_contour_span_ratio=args.micro_contour_span_ratio,
                small_contour_span_ratio=args.small_contour_span_ratio,
                subpixel_detail=not args.no_subpixel_detail,
                subpixel_min_path_data_bytes=args.subpixel_min_path_data_bytes,
                subpixel_curve_samples=args.subpixel_curve_samples,
            )
        )

    duplicate_groups = build_duplicate_groups(reports)

    classifications = Counter(
        report.classification for report in reports if report.classification is not None
    )
    advisories = Counter(
        advisory for report in reports for advisory in report.advisories
    )
    summary = ScanSummary(
        root=str(root),
        svg_files=len(reports),
        flagged_files=sum(report.flagged for report in reports),
        parse_errors=sum(report.parse_error is not None for report in reports),
        exact_duplicate_groups=len(duplicate_groups),
        classifications=dict(sorted(classifications.items())),
        advisories=dict(sorted(advisories.items())),
    )

    print_report(reports, show_all=args.all)
    print()
    print(
        f"Scanned {summary.svg_files} SVGs; flagged {summary.flagged_files}; "
        f"parse errors {summary.parse_errors}."
    )
    if summary.exact_duplicate_groups:
        print(f"Exact duplicate source groups: {summary.exact_duplicate_groups}")
    if summary.classifications:
        print(
            "Classifications: "
            + ", ".join(f"{name}={count}" for name, count in summary.classifications.items())
        )
    if summary.advisories:
        print(
            "Advisories: "
            + ", ".join(f"{name}={count}" for name, count in summary.advisories.items())
        )

    if args.json:
        write_json(args.json, summary, reports, duplicate_groups)
        print(f"JSON report: {args.json}")
    if args.csv:
        write_csv(args.csv, reports)
        print(f"CSV report: {args.csv}")

    return 1 if summary.parse_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
