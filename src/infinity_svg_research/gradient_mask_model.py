from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
from lxml import etree
from PIL import Image

from . import gradient_mask_reconstruct as legacy
from . import render_compare
from . import scan

DEFAULT_SIZES = (64, 128, 256, 512, 1024, 1600)
DEFAULT_FIT_SIZE = 1600

# Guijia-derived compact model expressed relative to the detected circular scaffold.
# Cross-family structural comparison found the same circle sequence and effectively the
# same gradient-coordinate sequence in all six unique flattened-gradient-mask families.
GRAY_BASE_RELATIVE = {
    "x1": (37.469 - 41.1) / 32.02,
    "y1": (70.8 - 41.1) / 32.02,
    "x2": (44.766 - 41.1) / 32.02,
    "y2": (11.114 - 41.1) / 32.02,
}
ACCENT_BASE_RELATIVE = {
    "x1": (16.506 - 41.1) / 24.69,
    "y1": (39.69 - 41.1) / 24.69,
    "x2": (48.529 - 41.1) / 24.69,
    "y2": (41.526 - 41.1) / 24.69,
}
ACCENT_RADIAL_1_RELATIVE = {
    "cx": (42.077 - 41.1) / 24.69,
    "cy": (13.377 - 41.1) / 24.69,
    "r": 35.879 / 24.69,
    "start_opacity": 1.0,
}
ACCENT_RADIAL_2_RELATIVE = {
    "cx": (48.593 - 41.1) / 24.69,
    "cy": (47.359 - 41.1) / 24.69,
    "r": 19.04 / 24.69,
    "start_opacity": 0.34304,
}

# Weak-mask default refitted from the raw Guijia source. The fitting stage below keeps
# this shared default when the source-render evidence is weak; it only solves a full
# family-specific radial field when the measured mask contribution is materially stronger.
WEAK_GRAY_SHADOW_RELATIVE = {
    "cx": (41.584874267689635 - 41.1) / 32.02,
    "cy": (41.41635273707423 - 41.1) / 32.02,
    "r": 32.553825521715844 / 32.02,
    "start_offset": 0.9920510099625911,
    "max_opacity": 0.1221293050842926,
}
STRONG_SHADOW_P99_THRESHOLD = 0.20


class ModelError(RuntimeError):
    pass


def _format(value: float) -> str:
    return legacy._format_number(value)


def _hex_rgb(value: str | None) -> tuple[int, int, int] | None:
    if not value or not value.startswith("#"):
        return None
    text = value[1:]
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    if len(text) != 6:
        return None
    try:
        return tuple(
            int(text[index : index + 2], 16) for index in (0, 2, 4)
        )  # type: ignore[return-value]
    except ValueError:
        return None


def _rgb_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{value:02x}" for value in rgb)


def _gray_palette(scaffold: dict[str, Any]) -> tuple[str, str]:
    colors: list[tuple[int, int, int]] = []
    for node in scaffold["outer_stripes"].iter():
        if not isinstance(node.tag, str) or legacy._local(node) not in {"path", "polygon", "rect"}:
            continue
        rgb = _hex_rgb(legacy._resolved_property(node, "fill"))
        if rgb is None or max(rgb) - min(rgb) > 6:
            continue
        colors.append(rgb)
    if not colors:
        return "#dbdddf", "#ffffff"
    dark = min(colors, key=lambda rgb: sum(rgb))
    light = max(colors, key=lambda rgb: sum(rgb))
    return _rgb_hex(dark), _rgb_hex(light)


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
    return legacy._make_linear_gradient(
        root,
        prefix=prefix,
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        coordinates=coordinates,
        stops=stops,
    )


def _make_radial_gradient(
    root: etree._Element,
    *,
    prefix: str,
    cx: float,
    cy: float,
    radius: float,
    stops: list[tuple[str, str, str | None]],
) -> tuple[str, etree._Element]:
    gradient_id = legacy._unique_id(root, prefix)
    gradient = etree.Element(f"{{{scan.SVG}}}radialGradient")
    gradient.set("id", gradient_id)
    gradient.set("gradientUnits", "userSpaceOnUse")
    gradient.set("cx", _format(cx))
    gradient.set("cy", _format(cy))
    gradient.set("r", _format(radius))
    for offset, color, opacity in stops:
        stop = etree.SubElement(gradient, f"{{{scan.SVG}}}stop")
        stop.set("offset", offset)
        stop.set("stop-color", color)
        if opacity is not None:
            stop.set("stop-opacity", opacity)
    return gradient_id, gradient


def _relative_shadow(
    gray_cx: float,
    gray_cy: float,
    gray_r: float,
    relative: dict[str, float] = WEAK_GRAY_SHADOW_RELATIVE,
) -> dict[str, float | str]:
    return {
        "mode": "shared-weak",
        "cx": gray_cx + relative["cx"] * gray_r,
        "cy": gray_cy + relative["cy"] * gray_r,
        "r": relative["r"] * gray_r,
        "start_offset": relative["start_offset"],
        "max_opacity": relative["max_opacity"],
    }


def _add_gray_shadow(
    root: etree._Element,
    *,
    gray_group: etree._Element,
    gray_cx: float,
    gray_cy: float,
    gray_r: float,
    shadow: dict[str, Any],
) -> dict[str, Any]:
    defs = legacy._ensure_defs(root)
    shadow_id, gradient = _make_radial_gradient(
        root,
        prefix="svg-research-gray-shadow",
        cx=float(shadow["cx"]),
        cy=float(shadow["cy"]),
        radius=float(shadow["r"]),
        stops=[
            (_format(float(shadow["start_offset"])), "#040505", "0"),
            ("1", "#040505", _format(float(shadow["max_opacity"]))),
        ],
    )
    defs.append(gradient)
    circle = etree.Element(f"{{{scan.SVG}}}circle")
    circle.set("cx", _format(gray_cx))
    circle.set("cy", _format(gray_cy))
    circle.set("r", _format(gray_r))
    circle.set("fill", f"url(#{shadow_id})")
    circle.set("data-svg-research", "reconstructed-gray-shadow")
    gray_group.append(circle)
    return {
        "id": shadow_id,
        "mode": shadow.get("mode", "provided"),
        "cx": float(shadow["cx"]),
        "cy": float(shadow["cy"]),
        "r": float(shadow["r"]),
        "start_offset": float(shadow["start_offset"]),
        "max_opacity": float(shadow["max_opacity"]),
    }


def reconstruct_decomposed_tree(
    tree: etree._ElementTree,
    *,
    gray_shadow: dict[str, Any] | None | str = "default",
) -> dict[str, Any]:
    root = tree.getroot()
    scaffold = legacy.find_gradient_mask_scaffold(root)
    palette = legacy._dominant_gradient_palette(root)
    accent_light, accent_dark = legacy._palette_colors(palette)
    gray_dark, gray_light = _gray_palette(scaffold)

    removed_nodes: list[etree._Element] = scaffold["removed_nodes"]
    removed_ids = set().union(*(legacy._ids_in(child) for child in removed_nodes))
    remaining_refs = legacy._refs_outside_removed(root, removed_nodes)
    dangling = sorted(removed_ids & remaining_refs)
    if dangling:
        raise ModelError(
            "remaining artwork references ids defined inside the scaffold slated for removal: "
            + ", ".join(dangling)
        )

    inner_cx, inner_cy, inner_r = scaffold["inner_geometry"]
    gray_cx, gray_cy, gray_r = scaffold["ring_geometry"]
    defs = legacy._ensure_defs(root)

    gray_base_id, gray_base = _make_linear_gradient(
        root,
        prefix="svg-research-gray-base",
        center_x=gray_cx,
        center_y=gray_cy,
        radius=gray_r,
        coordinates=GRAY_BASE_RELATIVE,
        stops=[("0", gray_dark, None), ("1", gray_light, None)],
    )
    accent_base_id, accent_base = _make_linear_gradient(
        root,
        prefix="svg-research-accent-base-2d",
        center_x=inner_cx,
        center_y=inner_cy,
        radius=inner_r,
        coordinates=ACCENT_BASE_RELATIVE,
        stops=[("0", accent_light, None), ("1", accent_dark, None)],
    )
    radial_1_id, radial_1 = _make_radial_gradient(
        root,
        prefix="svg-research-accent-radial-1",
        cx=inner_cx + ACCENT_RADIAL_1_RELATIVE["cx"] * inner_r,
        cy=inner_cy + ACCENT_RADIAL_1_RELATIVE["cy"] * inner_r,
        radius=ACCENT_RADIAL_1_RELATIVE["r"] * inner_r,
        stops=[("0", accent_light, None), ("1", accent_light, "0")],
    )
    radial_2_id, radial_2 = _make_radial_gradient(
        root,
        prefix="svg-research-accent-radial-2",
        cx=inner_cx + ACCENT_RADIAL_2_RELATIVE["cx"] * inner_r,
        cy=inner_cy + ACCENT_RADIAL_2_RELATIVE["cy"] * inner_r,
        radius=ACCENT_RADIAL_2_RELATIVE["r"] * inner_r,
        stops=[
            ("0", accent_light, _format(ACCENT_RADIAL_2_RELATIVE["start_opacity"])),
            ("1", accent_light, "0"),
        ],
    )
    defs.extend((gray_base, accent_base, radial_1, radial_2))

    gray_group = etree.Element(f"{{{scan.SVG}}}g")
    gray_group.set("data-svg-research", "reconstructed-gray-field")
    gray_circle = etree.SubElement(gray_group, f"{{{scan.SVG}}}circle")
    gray_circle.set("cx", _format(gray_cx))
    gray_circle.set("cy", _format(gray_cy))
    gray_circle.set("r", _format(gray_r))
    gray_circle.set("fill", f"url(#{gray_base_id})")
    gray_circle.set("data-svg-research", "reconstructed-gray-disc")

    shadow_summary: dict[str, Any] | None = None
    if gray_shadow == "default":
        gray_shadow = _relative_shadow(gray_cx, gray_cy, gray_r)
    if isinstance(gray_shadow, dict):
        shadow_summary = _add_gray_shadow(
            root,
            gray_group=gray_group,
            gray_cx=gray_cx,
            gray_cy=gray_cy,
            gray_r=gray_r,
            shadow=gray_shadow,
        )

    accent_group = etree.Element(f"{{{scan.SVG}}}g")
    accent_group.set("data-svg-research", "reconstructed-accent-field")
    for gradient_id, marker in (
        (accent_base_id, "reconstructed-accent-base"),
        (radial_1_id, "reconstructed-accent-radial-1"),
        (radial_2_id, "reconstructed-accent-radial-2"),
    ):
        circle = etree.SubElement(accent_group, f"{{{scan.SVG}}}circle")
        circle.set("cx", _format(inner_cx))
        circle.set("cy", _format(inner_cy))
        circle.set("r", _format(inner_r))
        circle.set("fill", f"url(#{gradient_id})")
        circle.set("data-svg-research", marker)

    insert_parent: etree._Element = scaffold["insert_parent"]
    insert_at: int = scaffold["insert_index"]
    insert_parent.insert(insert_at, gray_group)
    insert_parent.insert(insert_at + 1, accent_group)
    removed_count = legacy._remove_nodes(removed_nodes)
    css_stats = legacy.prune_unused_class_rules_outside_defs(root)
    defs_stats = legacy.prune_unreferenced_defs(root)

    return {
        "model": "decomposed-concentric",
        "geometry_policy": "concentric-authorial",
        "geometry_invariant": {
            "center": {"cx": inner_cx, "cy": inner_cy},
            "gray_radius": gray_r,
            "accent_radius": inner_r,
        },
        "match_mode": scaffold.get("match_mode", "unknown"),
        "removed_scaffold_nodes": removed_count,
        "outer_stripe_geometry_removed": legacy._stripe_geometry_count(scaffold["outer_stripes"]),
        "inner_stripe_geometry_removed": legacy._stripe_geometry_count(scaffold["inner_stripes"]),
        "multiply_circles_removed": legacy._geometry_count(scaffold["multiply_stack"], "circle"),
        "inner_geometry": {"cx": inner_cx, "cy": inner_cy, "r": inner_r},
        "gray_geometry": {"cx": gray_cx, "cy": gray_cy, "r": gray_r},
        "gray_colors": [gray_dark, gray_light],
        "accent_colors": [accent_light, accent_dark],
        "gradient_count": 4 + (1 if shadow_summary else 0),
        "circle_count": 4 + (1 if shadow_summary else 0),
        "gray_shadow": shadow_summary,
        "css_pruning": css_stats,
        "defs_pruning": defs_stats,
        "dominant_palette": [
            {"offset": offset, "color": color, "opacity": opacity, "style": style}
            for offset, color, opacity, style in palette
        ],
    }


def apply_gray_shadow(tree: etree._ElementTree, shadow: dict[str, Any]) -> dict[str, Any]:
    root = tree.getroot()
    groups = root.xpath(".//*[@data-svg-research='reconstructed-gray-field']", namespaces=scan.NS)
    if len(groups) != 1:
        raise ModelError(f"expected one reconstructed gray field, found {len(groups)}")
    group = groups[0]
    base_circle = group.xpath(
        "./s:circle[@data-svg-research='reconstructed-gray-disc']",
        namespaces=scan.NS,
    )
    if len(base_circle) != 1:
        raise ModelError("reconstructed gray field is missing its base circle")
    gray_cx, gray_cy, gray_r = legacy._circle_geometry(base_circle[0])
    return _add_gray_shadow(
        root,
        gray_group=group,
        gray_cx=gray_cx,
        gray_cy=gray_cy,
        gray_r=gray_r,
        shadow=shadow,
    )


def _load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"), dtype=np.float64)


def _view_box(root: etree._Element) -> tuple[float, float, float, float]:
    text = root.get("viewBox")
    if not text:
        raise ModelError("gray-shadow fitting requires an SVG viewBox")
    parts = [float(value) for value in text.replace(",", " ").split()]
    if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
        raise ModelError(f"invalid viewBox for gray-shadow fitting: {text!r}")
    return parts[0], parts[1], parts[2], parts[3]


def _shadow_fit_samples(
    source: np.ndarray,
    baseline: np.ndarray,
    *,
    view_box: tuple[float, float, float, float],
    gray_geometry: tuple[float, float, float],
) -> dict[str, Any]:
    if source.shape != baseline.shape:
        raise ModelError(f"shadow-fit render dimensions differ: {source.shape} != {baseline.shape}")
    height, width = source.shape[:2]
    min_x, min_y, vb_width, vb_height = view_box
    yy, xx = np.mgrid[0:height, 0:width]
    x = min_x + (xx + 0.5) * vb_width / width
    y = min_y + (yy + 0.5) * vb_height / height
    gray_cx, gray_cy, gray_r = gray_geometry
    radius = np.hypot(x - gray_cx, y - gray_cy)
    source_chroma = source.max(axis=2) - source.min(axis=2)
    baseline_chroma = baseline.max(axis=2) - baseline.min(axis=2)
    source_luma = source.mean(axis=2)
    baseline_luma = baseline.mean(axis=2)
    mask = (
        (radius >= gray_r - 3.0)
        & (radius <= gray_r)
        & (source_chroma < 15)
        & (baseline_chroma < 8)
        & (baseline_luma > 180)
        & (source_luma > 40)
    )
    alpha = np.clip(1.0 - source_luma / np.maximum(baseline_luma, 1.0), 0.0, 0.9)
    indexes = np.flatnonzero(mask.ravel())
    if indexes.size < 1000:
        raise ModelError(f"too few neutral gray-ring pixels for shadow fit: {indexes.size}")
    values = alpha.ravel()[indexes]
    p99 = float(np.percentile(values, 99))
    return {"x": x, "y": y, "alpha": alpha, "indexes": indexes, "p99": p99}


def _pattern_fit_radial_shadow(
    samples: dict[str, Any],
    *,
    gray_geometry: tuple[float, float, float],
) -> dict[str, Any]:
    x: np.ndarray = samples["x"]
    y: np.ndarray = samples["y"]
    alpha: np.ndarray = samples["alpha"]
    indexes: np.ndarray = samples["indexes"]
    values = alpha.ravel()[indexes]
    positive = indexes[values > 0.01]
    quiet = indexes[values <= 0.01]
    rng = np.random.default_rng(42)
    if positive.size > 12_000:
        positive = rng.choice(positive, 12_000, replace=False)
    if quiet.size > 12_000:
        quiet = rng.choice(quiet, 12_000, replace=False)
    selected = np.concatenate((positive, quiet))
    xs = x.ravel()[selected]
    ys = y.ravel()[selected]
    target = alpha.ravel()[selected]
    weights = np.where(target > 0.01, 2.0, 1.0)

    gray_cx, gray_cy, gray_r = gray_geometry
    p99 = float(samples["p99"])
    parameters = np.array(
        [gray_cx + 0.6, gray_cy + 0.3, gray_r + 0.65, 0.984, max(0.15, min(0.8, p99))],
        dtype=np.float64,
    )
    lower = np.array([gray_cx - 1.5, gray_cy - 1.5, gray_r - 1.0, 0.90, 0.02])
    upper = np.array([gray_cx + 1.5, gray_cy + 1.5, gray_r + 2.0, 0.999, 0.95])
    steps = np.array([0.25, 0.25, 0.25, 0.006, 0.08])

    def objective(candidate: np.ndarray) -> float:
        cx, cy, radius, start_offset, max_opacity = candidate
        normalized = np.hypot(xs - cx, ys - cy) / radius
        predicted = max_opacity * np.clip(
            (normalized - start_offset) / max(1e-9, 1.0 - start_offset), 0.0, 1.0
        )
        return float(np.average((predicted - target) ** 2, weights=weights))

    best = objective(parameters)
    for _ in range(24):
        improved = False
        for index in range(parameters.size):
            for sign in (-1.0, 1.0):
                candidate = parameters.copy()
                candidate[index] = np.clip(
                    candidate[index] + sign * steps[index],
                    lower[index],
                    upper[index],
                )
                score = objective(candidate)
                if score + 1e-12 < best:
                    parameters = candidate
                    best = score
                    improved = True
        if not improved:
            steps *= 0.5
        if max(steps[0], steps[1], steps[2]) < 0.001 and steps[3] < 0.00005 and steps[4] < 0.001:
            break

    return {
        "mode": "fitted-strong",
        "cx": float(parameters[0]),
        "cy": float(parameters[1]),
        "r": float(parameters[2]),
        "start_offset": float(parameters[3]),
        "max_opacity": float(parameters[4]),
        "fit_alpha_rmse": float(best**0.5),
        "target_alpha_p99": p99,
        "sample_count": int(selected.size),
    }


def fit_gray_shadow_from_renders(
    source_png: Path,
    no_shadow_png: Path,
    *,
    view_box: tuple[float, float, float, float],
    gray_geometry: tuple[float, float, float],
) -> dict[str, Any]:
    source = _load_rgb(source_png)
    baseline = _load_rgb(no_shadow_png)
    samples = _shadow_fit_samples(
        source,
        baseline,
        view_box=view_box,
        gray_geometry=gray_geometry,
    )
    if float(samples["p99"]) < STRONG_SHADOW_P99_THRESHOLD:
        shadow = _relative_shadow(*gray_geometry)
        shadow.update(
            {
                "mode": "shared-weak",
                "target_alpha_p99": float(samples["p99"]),
                "fit_alpha_rmse": None,
                "sample_count": int(samples["indexes"].size),
            }
        )
        return shadow
    return _pattern_fit_radial_shadow(samples, gray_geometry=gray_geometry)


def _scan_summary(path: Path) -> dict[str, Any]:
    return legacy._scan_summary(path)


def _metric_summary(metrics: list[render_compare.RenderMetrics]) -> dict[str, Any]:
    return legacy._metric_summary(metrics)


def _apply_fit_report(
    tree: etree._ElementTree,
    reconstruction: dict[str, Any],
    fit_report: dict[str, Any],
) -> None:
    reconstruction["gray_shadow"] = apply_gray_shadow(tree, fit_report)
    reconstruction["gray_shadow"].update(
        {
            key: value
            for key, value in fit_report.items()
            if key in {"target_alpha_p99", "fit_alpha_rmse", "sample_count"}
        }
    )
    reconstruction["gradient_count"] = 5
    reconstruction["circle_count"] = 5


def _load_fit_report(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelError(f"could not read gray-shadow fit JSON {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ModelError(f"gray-shadow fit JSON must contain an object: {path}")
    required = {"cx", "cy", "r", "start_offset", "max_opacity"}
    missing = sorted(required - set(document))
    if missing:
        raise ModelError(
            f"gray-shadow fit JSON is missing required field(s): {', '.join(missing)}"
        )
    return document


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Experimental decomposed gradient/mask reconstruction: replace the flattened badge "
            "with concentric gray/accent circles, a gray linear field, optional fitted gray edge "
            "shadow, one accent linear field, and two accent radial highlights. Outputs always "
            "require review."
        )
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("gradient-mask-model"))
    parser.add_argument("--sizes", type=render_compare.parse_sizes, default=DEFAULT_SIZES)
    parser.add_argument("--inkscape")
    parser.add_argument("--scour", action="store_true")
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument(
        "--fit-gray-shadow",
        action="store_true",
        help="fit strong gray mask crescents from a source/no-shadow render pair",
    )
    parser.add_argument(
        "--gray-shadow",
        choices=("default", "none"),
        default="default",
        help="gray-shadow mode when not fitting; 'none' is primarily for batch fit preparation",
    )
    parser.add_argument(
        "--gray-shadow-fit-json",
        type=Path,
        help="apply a precomputed gray-shadow fit JSON without launching the renderer",
    )
    parser.add_argument("--fit-size", type=int, default=DEFAULT_FIT_SIZE)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    source = args.source.resolve()
    if not source.is_file():
        parser.error(f"source does not exist: {args.source}")
    if args.fit_gray_shadow and args.no_render:
        parser.error("--fit-gray-shadow requires rendering; remove --no-render")
    if args.fit_gray_shadow and args.gray_shadow_fit_json:
        parser.error("--fit-gray-shadow and --gray-shadow-fit-json are mutually exclusive")
    if args.gray_shadow_fit_json and not args.gray_shadow_fit_json.is_file():
        parser.error(f"gray-shadow fit JSON does not exist: {args.gray_shadow_fit_json}")
    if args.fit_size <= 0:
        parser.error("--fit-size must be positive")

    report = legacy._scan_source(source)
    if report.classification != "flattened-gradient-mask" and not args.force:
        parser.error(
            f"source classification is {report.classification!r}, not 'flattened-gradient-mask'; "
            "use --force for an explicit experiment"
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    tree = legacy._parse_svg(source)
    try:
        initial_shadow: dict[str, Any] | None | str
        if args.fit_gray_shadow or args.gray_shadow_fit_json or args.gray_shadow == "none":
            initial_shadow = None
        else:
            initial_shadow = "default"
        reconstruction = reconstruct_decomposed_tree(tree, gray_shadow=initial_shadow)
    except (legacy.ReconstructionError, ModelError) as exc:
        parser.error(str(exc))

    fit_report: dict[str, Any] | None = None
    if args.gray_shadow_fit_json:
        try:
            fit_report = _load_fit_report(args.gray_shadow_fit_json.resolve())
            _apply_fit_report(tree, reconstruction, fit_report)
        except ModelError as exc:
            parser.error(str(exc))
    elif args.fit_gray_shadow:
        no_shadow = args.output_dir / f"{source.stem}.gradient-mask-decomposed.no-shadow.svg"
        tree.write(str(no_shadow), encoding="UTF-8", xml_declaration=True, pretty_print=False)
        fit_dir = args.output_dir / "gray-shadow-fit"
        fit_dir.mkdir(parents=True, exist_ok=True)
        renderer = render_compare.find_inkscape(args.inkscape)
        render_compare.render_svg_pairs_shell(
            source,
            no_shadow,
            fit_dir,
            (args.fit_size,),
            inkscape=renderer,
        )
        source_png = fit_dir / f"original-{args.fit_size}.png"
        no_shadow_png = fit_dir / f"candidate-{args.fit_size}.png"
        gray = reconstruction["gray_geometry"]
        try:
            fit_report = fit_gray_shadow_from_renders(
                source_png,
                no_shadow_png,
                view_box=_view_box(tree.getroot()),
                gray_geometry=(float(gray["cx"]), float(gray["cy"]), float(gray["r"])),
            )
            _apply_fit_report(tree, reconstruction, fit_report)
        except ModelError as exc:
            parser.error(str(exc))

    reconstructed = args.output_dir / f"{source.stem}.gradient-mask-decomposed.svg"
    tree.write(str(reconstructed), encoding="UTF-8", xml_declaration=True, pretty_print=False)
    candidate = reconstructed
    stages: dict[str, Any] = {
        "reconstructed": {"path": str(reconstructed), "bytes": reconstructed.stat().st_size}
    }
    if args.scour:
        scoured = args.output_dir / f"{source.stem}.gradient-mask-decomposed.scour.svg"
        stages["scoured"] = legacy._scour_svg(reconstructed, scoured)
        stages["scoured"]["path"] = str(scoured)
        candidate = scoured

    payload: dict[str, Any] = {
        "schema_version": 1,
        "experiment": "gradient-mask-decomposed-model",
        "verdict": "experimental-review-required",
        "automatic_acceptance": False,
        "source": str(source),
        "candidate": str(candidate),
        "source_classification": report.classification,
        "source_size_bytes": source.stat().st_size,
        "candidate_size_bytes": candidate.stat().st_size,
        "byte_reduction_fraction": 1.0 - candidate.stat().st_size / source.stat().st_size,
        "reconstruction": reconstruction,
        "gray_shadow_fit": fit_report,
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
