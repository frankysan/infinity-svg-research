from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from lxml import etree
from PIL import Image

from .palette_repair import _parse_svg, snap_fragmented_palette
from .render_compare import find_inkscape, render_svg

SVG_NS = "http://www.w3.org/2000/svg"
DEFAULT_SIMPLIFY = (0.75, 1.0, 1.5, 2.0)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _rgb_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{v:02x}" for v in rgb)


def _parse_float_list(text: str) -> tuple[float, ...]:
    values = tuple(float(x.strip()) for x in text.split(",") if x.strip())
    if not values or any(v <= 0 for v in values):
        raise argparse.ArgumentTypeError("expected comma-separated positive numbers")
    return values


def _viewbox(root: etree._Element) -> tuple[float, float, float, float]:
    raw = root.get("viewBox")
    if not raw:
        raise RuntimeError("source SVG has no viewBox")
    values = tuple(float(v) for v in raw.replace(",", " ").split())
    if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
        raise RuntimeError(f"unsupported viewBox: {raw}")
    return values  # type: ignore[return-value]


def _reference_two_colours(rgba: np.ndarray) -> tuple[list[tuple[int, int, int]], dict[str, Any]]:
    alpha = rgba[:, :, 3]
    opaque = alpha >= 250
    if int(opaque.sum()) < 100:
        opaque = alpha >= 128
    rgb = rgba[:, :, :3]
    counts = Counter(map(tuple, rgb[opaque].reshape(-1, 3)))
    if len(counts) < 2:
        raise RuntimeError("reference does not contain two distinguishable opaque colours")
    top = counts.most_common(2)
    colors = [tuple(int(v) for v in color) for color, _ in top]
    top = [(tuple(int(v) for v in color), int(count)) for color, count in top]
    top_exact_fraction = sum(count for _, count in top) / max(1, int(opaque.sum()))
    return colors, {
        "opaque_pixels": int(opaque.sum()),
        "top_exact_colors": [{"rgb": list(c), "count": int(n)} for c, n in top],
        "top_two_exact_fraction": top_exact_fraction,
    }


def _source_endpoints(source: Path) -> tuple[tuple[int, int, int], tuple[int, int, int], dict[str, Any]]:
    tree = _parse_svg(source)
    stats = snap_fragmented_palette(tree)
    if not stats.get("changed"):
        raise RuntimeError("source does not expose the expected fragmented two-endpoint palette")
    a = tuple(int(v) for v in stats["endpoint_start"])
    b = tuple(int(v) for v in stats["endpoint_end"])
    return a, b, stats


def _assign_palette(
    reference: list[tuple[int, int, int]], source: tuple[tuple[int, int, int], tuple[int, int, int]]
) -> list[tuple[int, int, int]]:
    r0 = np.array(reference[0], dtype=np.float64)
    r1 = np.array(reference[1], dtype=np.float64)
    s0 = np.array(source[0], dtype=np.float64)
    s1 = np.array(source[1], dtype=np.float64)
    direct = np.linalg.norm(r0 - s0) + np.linalg.norm(r1 - s1)
    crossed = np.linalg.norm(r0 - s1) + np.linalg.norm(r1 - s0)
    return [source[0], source[1]] if direct <= crossed else [source[1], source[0]]


def _classify_reference(
    rgba: np.ndarray,
    colors: list[tuple[int, int, int]],
    *,
    alpha_threshold: int,
) -> tuple[np.ndarray, np.ndarray, list[int], int, int]:
    rgb = rgba[:, :, :3].astype(np.int32)
    alpha = rgba[:, :, 3]
    palette = [np.array(c, dtype=np.int32) for c in colors]
    distance = np.stack([((rgb - c) ** 2).sum(axis=2) for c in palette], axis=2)
    labels = distance.argmin(axis=2)
    foreground = alpha >= alpha_threshold
    class_counts = [int(np.logical_and(labels == i, foreground).sum()) for i in range(len(colors))]
    base_index = int(np.argmax(class_counts))
    overlay_index = 1 - base_index
    return labels, foreground, class_counts, base_index, overlay_index


def _contour_path(
    mask: np.ndarray,
    viewbox: tuple[float, float, float, float],
    *,
    simplify_px: float,
    decimals: int = 3,
) -> tuple[str, dict[str, int]]:
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    x0, y0, width, height = viewbox
    image_height, image_width = mask.shape
    pieces: list[str] = []
    points_before = 0
    points_after = 0
    kept_contours = 0
    for contour in contours:
        points_before += len(contour)
        approx = cv2.approxPolyDP(contour, simplify_px, True)
        if len(approx) < 3:
            continue
        coords = approx[:, 0, :].astype(np.float64)
        points_after += len(coords)
        kept_contours += 1
        mapped: list[tuple[float, float]] = []
        for px, py in coords:
            sx = x0 + (px / max(1, image_width - 1)) * width
            sy = y0 + (py / max(1, image_height - 1)) * height
            mapped.append((sx, sy))
        fmt = f"{{:.{decimals}f}}"
        first = mapped[0]
        path = "M" + fmt.format(first[0]) + "," + fmt.format(first[1])
        path += "".join("L" + fmt.format(x) + "," + fmt.format(y) for x, y in mapped[1:])
        path += "Z"
        pieces.append(path)
    return "".join(pieces), {
        "contours": kept_contours,
        "points_before": points_before,
        "points_after": points_after,
    }


def _write_candidate(
    destination: Path,
    viewbox: tuple[float, float, float, float],
    base_path: str,
    overlay_path: str,
    base_color: tuple[int, int, int],
    overlay_color: tuple[int, int, int],
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    root = etree.Element(
        f"{{{SVG_NS}}}svg",
        nsmap={None: SVG_NS},
        viewBox=" ".join(f"{v:g}" for v in viewbox),
    )
    etree.SubElement(
        root,
        f"{{{SVG_NS}}}path",
        fill=_rgb_hex(base_color),
        d=base_path,
        **{"fill-rule": "evenodd"},
    )
    etree.SubElement(
        root,
        f"{{{SVG_NS}}}path",
        fill=_rgb_hex(overlay_color),
        d=overlay_path,
        **{"fill-rule": "evenodd"},
    )
    etree.ElementTree(root).write(str(destination), encoding="UTF-8", xml_declaration=False, pretty_print=False)


def _premultiplied(rgba: np.ndarray) -> np.ndarray:
    arr = rgba.astype(np.float64)
    arr[:, :, :3] *= arr[:, :, 3:4] / 255.0
    return arr


def _white_bg(rgba: np.ndarray) -> np.ndarray:
    arr = rgba.astype(np.float64)
    alpha = arr[:, :, 3:4] / 255.0
    return arr[:, :, :3] * alpha + 255.0 * (1.0 - alpha)


def _compare_png(left_path: Path, right_path: Path) -> dict[str, Any]:
    with Image.open(left_path) as left_im, Image.open(right_path) as right_im:
        left = np.asarray(left_im.convert("RGBA"), dtype=np.uint8)
        right_image = right_im.convert("RGBA")
        if right_image.size != left_im.size:
            right_image = right_image.resize(left_im.size, Image.Resampling.LANCZOS)
        right = np.asarray(right_image, dtype=np.uint8)
    diff = left.astype(np.int16) - right.astype(np.int16)
    changed = np.any(diff != 0, axis=2)
    return {
        "width": int(left.shape[1]),
        "height": int(left.shape[0]),
        "changed_pixels": int(changed.sum()),
        "changed_pixel_fraction": float(changed.mean()),
        "max_channel_diff": int(np.abs(diff).max()),
        "rgba_rmse": float(np.sqrt(np.mean(diff.astype(np.float64) ** 2))),
        "premultiplied_rgba_rmse": float(
            np.sqrt(np.mean((_premultiplied(left) - _premultiplied(right)) ** 2))
        ),
        "white_background_rgb_rmse": float(
            np.sqrt(np.mean((_white_bg(left) - _white_bg(right)) ** 2))
        ),
        "alpha_rmse": float(
            np.sqrt(np.mean((left[:, :, 3].astype(np.float64) - right[:, :, 3].astype(np.float64)) ** 2))
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reference-guided two-colour boundary reconstruction experiment.")
    parser.add_argument("source", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("reference-reconstruction"))
    parser.add_argument("--inkscape")
    parser.add_argument("--reference-size", type=int, default=2048)
    parser.add_argument(
        "--reference-source-kind",
        choices=["human-sphere-third-party", "first-party-current", "first-party-historical", "other-third-party"],
        default="human-sphere-third-party",
        help="provenance label recorded in the manifest; it does not change acceptance behavior",
    )
    parser.add_argument("--alpha-threshold", type=int, default=96)
    parser.add_argument("--simplify-px", type=_parse_float_list, default=DEFAULT_SIMPLIFY)
    args = parser.parse_args()

    started = time.perf_counter()
    if not 1 <= args.alpha_threshold <= 254:
        parser.error("--alpha-threshold must be in 1..254")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    inkscape = find_inkscape(args.inkscape)

    source_tree = _parse_svg(args.source)
    viewbox = _viewbox(source_tree.getroot())
    with Image.open(args.reference) as im:
        reference_rgba = np.asarray(im.convert("RGBA"), dtype=np.uint8)
    reference_colors, reference_stats = _reference_two_colours(reference_rgba)
    source_a, source_b, snap_stats = _source_endpoints(args.source)
    source_mapping = _assign_palette(reference_colors, (source_a, source_b))

    labels, foreground, class_counts, base_idx, overlay_idx = _classify_reference(
        reference_rgba, reference_colors, alpha_threshold=args.alpha_threshold
    )
    base_mask = (foreground.astype(np.uint8) * 255)
    overlay_mask = (np.logical_and(labels == overlay_idx, foreground).astype(np.uint8) * 255)

    render_source = args.output_dir / "source-reference-size.png"
    render_svg(args.source, render_source, args.reference_size, inkscape=inkscape)
    reference_native = args.output_dir / "reference-normalized.png"
    with Image.open(args.reference) as im:
        im.convert("RGBA").resize((args.reference_size, args.reference_size), Image.Resampling.LANCZOS).save(reference_native)
    source_to_reference = _compare_png(reference_native, render_source)

    variants: list[dict[str, Any]] = []
    for epsilon in args.simplify_px:
        base_path, base_geometry = _contour_path(base_mask, viewbox, simplify_px=epsilon)
        overlay_path, overlay_geometry = _contour_path(overlay_mask, viewbox, simplify_px=epsilon)
        for palette_name, mapped in (
            ("source-palette", source_mapping),
            ("reference-palette", reference_colors),
        ):
            base_color = mapped[base_idx]
            overlay_color = mapped[overlay_idx]
            stem = f"reconstructed-eps-{epsilon:g}-{palette_name}"
            svg_path = args.output_dir / f"{stem}.svg"
            png_path = args.output_dir / f"{stem}.png"
            _write_candidate(svg_path, viewbox, base_path, overlay_path, base_color, overlay_color)
            render_svg(svg_path, png_path, args.reference_size, inkscape=inkscape)
            variants.append(
                {
                    "simplify_px": epsilon,
                    "palette": palette_name,
                    "candidate": {
                        "path": str(svg_path),
                        "sha256": sha256(svg_path),
                        "bytes": svg_path.stat().st_size,
                        "path_count": 2,
                    },
                    "geometry": {"base": base_geometry, "overlay": overlay_geometry},
                    "reference_comparison": _compare_png(reference_native, png_path),
                    "source_comparison": _compare_png(render_source, png_path),
                }
            )

    variants.sort(
        key=lambda item: (
            item["reference_comparison"]["premultiplied_rgba_rmse"],
            item["candidate"]["bytes"],
        )
    )
    manifest = {
        "schema_version": 2,
        "experiment": "reference-guided-two-colour-boundary-reconstruction",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "automatic_acceptance": False,
        "reference_policy": {
            "source_kind": args.reference_source_kind,
            "authoritative_for_current_artwork": args.reference_source_kind == "first-party-current",
            "automatic_acceptance": False,
            "independence_not_assumed": True,
            "note": (
                "Reference-guided output is experimental. Human Sphere and other third-party references "
                "are never authoritative solely because they match visually; historical first-party "
                "references can also differ from the current revision."
            ),
        },
        "source": {"path": str(args.source), "sha256": sha256(args.source), "bytes": args.source.stat().st_size},
        "reference": {
            "path": str(args.reference),
            "sha256": sha256(args.reference),
            "width": int(reference_rgba.shape[1]),
            "height": int(reference_rgba.shape[0]),
            **reference_stats,
            "dominant_colors": [list(c) for c in reference_colors],
        },
        "source_palette": {
            "endpoints": [list(source_a), list(source_b)],
            "reference_color_mapping": [list(c) for c in source_mapping],
            "snap_detection": snap_stats,
        },
        "mask_policy": {
            "alpha_threshold": args.alpha_threshold,
            "class_counts": class_counts,
            "base_reference_color_index": base_idx,
            "overlay_reference_color_index": overlay_idx,
            "rule": "base path follows the reference alpha silhouette; overlay path follows the second dominant colour mask; paths use evenodd fill so holes reveal the base colour",
        },
        "baseline_source_to_reference": source_to_reference,
        "variants": variants,
        "best_by_reference_rmse": variants[0] if variants else None,
        "timing_seconds": {"total": time.perf_counter() - started},
        "notes": [
            "This is reference-guided restoration, not a lossless optimization.",
            "Human Sphere is a third-party source; its artwork is supporting evidence only and must not override first-party current artwork.",
            "A reference can represent an older revision or a derivative copy; candidate geometry must be reviewed before publication.",
            "Source-palette variants isolate geometry restoration while reference-palette variants measure fidelity to the external reference artwork.",
        ],
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Source -> reference premultiplied RGBA RMSE: {source_to_reference['premultiplied_rgba_rmse']:.4f}")
    if variants:
        best = variants[0]
        print(
            "Best reference match: "
            f"eps={best['simplify_px']:g} {best['palette']} "
            f"{best['candidate']['bytes']} B, premultiplied RMSE="
            f"{best['reference_comparison']['premultiplied_rgba_rmse']:.4f}"
        )
    print(f"Wrote {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
