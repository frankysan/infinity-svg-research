from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from lxml import etree
from PIL import Image

from . import scan
from .historical_probe_analyze import _png_effective_geometry, _resolve_saved_path
from .palette_repair import _farthest_endpoints, _palette_path_records, _parse_svg
from .reference_reconstruct import _contour_path, _rgb_hex, _viewbox
from .render_compare import (
    ShellRenderJob,
    compare_pair_outputs,
    find_inkscape,
    render_svg,
    render_svg_pairs_shell_batch,
)

SVG_NS = 'http://www.w3.org/2000/svg'
DEFAULT_SIMPLIFY = (0.75, 1.0, 1.5, 2.0)
DEFAULT_SIZES = (64, 128, 256, 512, 1024, 1600)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _parse_float_list(text: str) -> tuple[float, ...]:
    values = tuple(float(x.strip()) for x in text.split(',') if x.strip())
    if not values or any(value <= 0 for value in values):
        raise argparse.ArgumentTypeError('expected comma-separated positive numbers')
    return values


def _parse_int_list(text: str) -> tuple[int, ...]:
    values = tuple(int(x.strip()) for x in text.split(',') if x.strip())
    if not values or any(value <= 0 for value in values):
        raise argparse.ArgumentTypeError('expected comma-separated positive integers')
    return values


def _write_candidate(
    destination: Path,
    viewbox: tuple[float, float, float, float],
    paths: list[str],
    colours: list[tuple[int, int, int]],
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    root = etree.Element(
        f'{{{SVG_NS}}}svg',
        nsmap={None: SVG_NS},
        viewBox=' '.join(f'{value:g}' for value in viewbox),
    )
    for path_data, colour in zip(paths, colours, strict=True):
        if not path_data:
            continue
        etree.SubElement(
            root,
            f'{{{SVG_NS}}}path',
            fill=_rgb_hex(colour),
            d=path_data,
            **{'fill-rule': 'evenodd'},
        )
    etree.ElementTree(root).write(
        str(destination), encoding='UTF-8', xml_declaration=False, pretty_print=False
    )


def _source_palette(source: Path, *, extra_colour_distance: float) -> dict[str, Any]:
    root = _parse_svg(source).getroot()
    records, path_counts, path_bytes = _palette_path_records(root)
    colours = list(path_counts)
    if len(colours) < 2:
        raise RuntimeError('source has fewer than two flat-fill colours')
    start, end, endpoint_distance = _farthest_endpoints(colours)
    path_extras: list[dict[str, Any]] = []
    for colour in colours:
        distance, t = scan.point_segment_distance_and_t(colour, start, end)
        if distance > extra_colour_distance:
            path_extras.append(
                {
                    'rgb': colour,
                    'axis_distance': distance,
                    'axis_t': t,
                    'paths': int(path_counts[colour]),
                    'path_data_bytes': int(path_bytes[colour]),
                    'discovered_by': 'path-fill',
                }
            )
    path_extras.sort(key=lambda item: (item['path_data_bytes'], item['paths']), reverse=True)
    return {
        'endpoint_start': start,
        'endpoint_end': end,
        'endpoint_distance': endpoint_distance,
        'flat_fill_paths': len(records),
        'distinct_flat_fill_colours': len(colours),
        'path_extra_colours': path_extras,
    }


def _discover_render_extra_colours(
    rgba: np.ndarray,
    start: tuple[int, int, int],
    end: tuple[int, int, int],
    *,
    extra_colour_distance: float,
    min_fraction: float,
) -> list[dict[str, Any]]:
    opaque = rgba[:, :, 3] >= 250
    opaque_count = int(opaque.sum())
    if opaque_count == 0:
        return []
    counts = Counter(map(tuple, rgba[:, :, :3][opaque].reshape(-1, 3)))
    candidates: list[dict[str, Any]] = []
    for colour_raw, count in counts.items():
        colour = tuple(int(v) for v in colour_raw)
        distance, t = scan.point_segment_distance_and_t(colour, start, end)
        fraction = count / opaque_count
        if distance <= extra_colour_distance or fraction < min_fraction:
            continue
        candidates.append(
            {
                'rgb': colour,
                'axis_distance': distance,
                'axis_t': t,
                'opaque_pixels': int(count),
                'opaque_fraction': fraction,
                'discovered_by': 'rendered-opaque-pixels',
            }
        )
    candidates.sort(key=lambda item: item['opaque_pixels'], reverse=True)
    return candidates


def _merge_extra_colours(
    path_extras: list[dict[str, Any]],
    render_extras: list[dict[str, Any]],
    *,
    max_extra_colours: int,
    cluster_distance: float = 16.0,
) -> list[dict[str, Any]]:
    # Rendered dominant colours are preferred because this experiment reconstructs
    # the actual first-party rendered appearance. Path-only extras still preserve
    # small accent colours that may be visually significant but occupy few pixels.
    merged: list[dict[str, Any]] = []
    for item in [*render_extras, *path_extras]:
        rgb = np.asarray(item['rgb'], dtype=np.float64)
        if any(np.linalg.norm(rgb - np.asarray(existing['rgb'], dtype=np.float64)) <= cluster_distance for existing in merged):
            continue
        merged.append(item)
    if len(merged) > max_extra_colours:
        raise RuntimeError(
            f'source exposes {len(merged)} significant off-axis colour clusters; maximum is {max_extra_colours}. '
            'This experiment is intentionally limited to compact flat palettes.'
        )
    return merged


def _classify_render(
    rgba: np.ndarray,
    palette: list[tuple[int, int, int]],
    *,
    alpha_threshold: int,
) -> tuple[np.ndarray, np.ndarray, list[int], int]:
    rgb = rgba[:, :, :3].astype(np.int32)
    alpha = rgba[:, :, 3]
    colours = [np.asarray(colour, dtype=np.int32) for colour in palette]
    distances = np.stack([((rgb - colour) ** 2).sum(axis=2) for colour in colours], axis=2)
    labels = distances.argmin(axis=2)
    foreground = alpha >= alpha_threshold
    counts = [int(np.logical_and(labels == index, foreground).sum()) for index in range(len(palette))]
    base_index = int(np.argmax(counts))
    return labels, foreground, counts, base_index


def _summary(metrics: list[Any]) -> dict[str, Any]:
    return {
        'sizes': [int(metric.size) for metric in metrics],
        'max_changed_pixel_fraction': max((metric.changed_pixel_fraction for metric in metrics), default=0.0),
        'max_channel_diff': max((metric.max_channel_diff for metric in metrics), default=0),
        'max_rgba_rmse': max((metric.rgba_rmse for metric in metrics), default=0.0),
        'max_premultiplied_rgba_rmse': max((metric.premultiplied_rgba_rmse for metric in metrics), default=0.0),
        'max_white_background_rgb_rmse': max((metric.white_background_rgb_rmse for metric in metrics), default=0.0),
        'max_alpha_rmse': max((metric.alpha_rmse for metric in metrics), default=0.0),
    }


def _historical_guardrail(
    probe_results: Path | None,
    *,
    target: str | None,
) -> dict[str, Any] | None:
    if probe_results is None or target is None:
        return None
    payload = json.loads(probe_results.read_text(encoding='utf-8'))
    candidates = []
    for record in payload.get('records', []):
        if record.get('target') != target:
            continue
        if record.get('retrieval') != 'wayback' or record.get('kind') != 'png':
            continue
        provenance = record.get('provenance') or {}
        if provenance.get('source_authority') != 'first-party-historical':
            continue
        if not record.get('validation', {}).get('valid'):
            continue
        resolved = _resolve_saved_path(record.get('saved_path'), probe_results)
        if not resolved:
            continue
        geometry = _png_effective_geometry(resolved)
        candidates.append((geometry['effective_max_dimension'], resolved, record, geometry))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    _dimension, resolved, record, geometry = candidates[0]
    return {
        'path': resolved,
        'record': record,
        'geometry': geometry,
    }


def _crop_alpha(path: Path) -> Image.Image:
    with Image.open(path) as image:
        rgba = image.convert('RGBA')
        alpha = rgba.getchannel('A')
        bbox = alpha.point(lambda value: 255 if value > 8 else 0).getbbox()
        if bbox is None:
            return rgba.copy()
        return rgba.crop(bbox)


def _gray_white(rgba: np.ndarray) -> np.ndarray:
    arr = rgba.astype(np.float64)
    alpha = arr[:, :, 3:4] / 255.0
    rgb = arr[:, :, :3] * alpha + 255.0 * (1.0 - alpha)
    return 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]


def _corr(left: np.ndarray, right: np.ndarray) -> float:
    a = left.ravel().astype(np.float64)
    b = right.ravel().astype(np.float64)
    a -= a.mean()
    b -= b.mean()
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom <= 1e-12:
        return 1.0 if np.allclose(a, b) else 0.0
    return float(np.dot(a, b) / denom)


def _edges(gray: np.ndarray) -> np.ndarray:
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    gx[:, 1:-1] = gray[:, 2:] - gray[:, :-2]
    gy[1:-1, :] = gray[2:, :] - gray[:-2, :]
    return np.hypot(gx, gy)


def _guardrail_metrics(reference: Image.Image, rendered: Path) -> dict[str, Any]:
    with Image.open(rendered) as image:
        candidate = image.convert('RGBA')
    if candidate.size != reference.size:
        candidate = candidate.resize(reference.size, Image.Resampling.LANCZOS)
    left = np.asarray(reference, dtype=np.uint8)
    right = np.asarray(candidate, dtype=np.uint8)
    left_gray = _gray_white(left)
    right_gray = _gray_white(right)
    left_alpha = left[:, :, 3] > 8
    right_alpha = right[:, :, 3] > 8
    union = int(np.logical_or(left_alpha, right_alpha).sum())
    silhouette_left = left_gray < 245
    silhouette_right = right_gray < 245
    silhouette_union = int(np.logical_or(silhouette_left, silhouette_right).sum())
    return {
        'gray_correlation': _corr(left_gray, right_gray),
        'edge_correlation': _corr(_edges(left_gray), _edges(right_gray)),
        'alpha_iou': float(np.logical_and(left_alpha, right_alpha).sum() / union) if union else 1.0,
        'silhouette_iou': (
            float(np.logical_and(silhouette_left, silhouette_right).sum() / silhouette_union)
            if silhouette_union else 1.0
        ),
        'white_background_gray_rmse': float(np.sqrt(np.mean((left_gray - right_gray) ** 2))),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Reconstruct compact flat-colour geometry from the rendered appearance of the current first-party SVG.'
    )
    parser.add_argument('source', type=Path)
    parser.add_argument('--output-dir', type=Path, default=Path('source-reconstruction'))
    parser.add_argument('--inkscape')
    parser.add_argument('--target', help='logical target slug, used to attach historical first-party guardrails')
    parser.add_argument('--historical-probe', type=Path, help='probe-results.json from historical_army_probe.py')
    parser.add_argument('--mask-size', type=int, default=2048)
    parser.add_argument('--alpha-threshold', type=int, default=96)
    parser.add_argument('--extra-colour-distance', type=float, default=32.0)
    parser.add_argument('--extra-colour-min-fraction', type=float, default=0.002)
    parser.add_argument('--max-extra-colours', type=int, default=4)
    parser.add_argument('--simplify-px', type=_parse_float_list, default=DEFAULT_SIMPLIFY)
    parser.add_argument('--sizes', type=_parse_int_list, default=DEFAULT_SIZES)
    args = parser.parse_args()

    started = time.perf_counter()
    if not 1 <= args.alpha_threshold <= 254:
        parser.error('--alpha-threshold must be in 1..254')
    if args.mask_size < 256:
        parser.error('--mask-size must be >= 256')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    inkscape = find_inkscape(args.inkscape)

    source_tree = _parse_svg(args.source)
    viewbox = _viewbox(source_tree.getroot())
    palette_info = _source_palette(
        args.source,
        extra_colour_distance=args.extra_colour_distance,
    )

    mask_render = args.output_dir / f'source-mask-{args.mask_size}.png'
    render_svg(args.source, mask_render, args.mask_size, inkscape=inkscape)
    with Image.open(mask_render) as image:
        rgba = np.asarray(image.convert('RGBA'), dtype=np.uint8)

    start_colour = tuple(int(v) for v in palette_info['endpoint_start'])
    end_colour = tuple(int(v) for v in palette_info['endpoint_end'])
    render_extras = _discover_render_extra_colours(
        rgba,
        start_colour,
        end_colour,
        extra_colour_distance=args.extra_colour_distance,
        min_fraction=args.extra_colour_min_fraction,
    )
    extras = _merge_extra_colours(
        palette_info['path_extra_colours'],
        render_extras,
        max_extra_colours=args.max_extra_colours,
    )
    palette = [start_colour, end_colour] + [tuple(int(v) for v in item['rgb']) for item in extras]
    labels, foreground, class_counts, base_index = _classify_render(
        rgba, palette, alpha_threshold=args.alpha_threshold
    )
    ordered_indexes = [base_index] + [index for index in range(len(palette)) if index != base_index]
    ordered_colours = [palette[index] for index in ordered_indexes]
    masks = [foreground.astype(np.uint8) * 255]
    masks.extend(
        np.logical_and(labels == index, foreground).astype(np.uint8) * 255
        for index in ordered_indexes[1:]
    )

    variants: list[dict[str, Any]] = []
    for epsilon in args.simplify_px:
        paths: list[str] = []
        geometry: list[dict[str, Any]] = []
        for mask in masks:
            path_data, stats = _contour_path(mask, viewbox, simplify_px=epsilon)
            paths.append(path_data)
            geometry.append(stats)
        candidate = args.output_dir / f'source-reconstructed-eps-{epsilon:g}.svg'
        _write_candidate(candidate, viewbox, paths, ordered_colours)
        variants.append(
            {
                'simplify_px': epsilon,
                'candidate': {
                    'path': str(candidate),
                    'sha256': sha256(candidate),
                    'bytes': candidate.stat().st_size,
                    'path_count': sum(1 for path in paths if path),
                    'byte_delta_vs_source': candidate.stat().st_size - args.source.stat().st_size,
                    'byte_reduction_fraction_vs_source': 1.0 - candidate.stat().st_size / args.source.stat().st_size,
                },
                'geometry_layers': [
                    {
                        'role': 'base-alpha-silhouette' if layer == 0 else f'palette-overlay-{layer}',
                        'rgb': list(ordered_colours[layer]),
                        **geometry[layer],
                    }
                    for layer in range(len(geometry))
                ],
            }
        )

    guardrail = _historical_guardrail(args.historical_probe, target=args.target)
    sizes = list(args.sizes)
    if guardrail is not None:
        native_size = int(guardrail['geometry']['effective_max_dimension'])
        if native_size > 0 and native_size not in sizes:
            sizes.append(native_size)
    sizes = sorted(set(sizes))

    jobs = []
    for index, variant in enumerate(variants):
        render_dir = args.output_dir / 'renders' / f'eps-{variant["simplify_px"]:g}'
        variant['render_dir'] = str(render_dir)
        jobs.append(
            ShellRenderJob(
                original=args.source,
                candidate=Path(variant['candidate']['path']),
                output_dir=render_dir,
            )
        )
    render_run = render_svg_pairs_shell_batch(jobs, sizes, inkscape=inkscape)

    for variant in variants:
        render_dir = Path(variant['render_dir'])
        metrics, compare_seconds = compare_pair_outputs(render_dir, sizes)
        configured_size_set = set(args.sizes)
        configured_metrics = [metric for metric in metrics if metric.size in configured_size_set]
        variant['source_comparison'] = {
            'renders': [asdict(metric) for metric in metrics],
            'summary': _summary(configured_metrics),
            'configured_sizes': list(args.sizes),
            'auxiliary_sizes': [metric.size for metric in metrics if metric.size not in configured_size_set],
            'compare_seconds': compare_seconds,
        }
        if guardrail is not None:
            native_size = int(guardrail['geometry']['effective_max_dimension'])
            historical = _crop_alpha(guardrail['path'])
            if historical.size != (native_size, native_size):
                historical = historical.resize((native_size, native_size), Image.Resampling.LANCZOS)
            source_native = render_dir / f'original-{native_size}.png'
            candidate_native = render_dir / f'candidate-{native_size}.png'
            variant['historical_guardrail'] = {
                'authority': 'first-party-historical',
                'geometry_role': guardrail['geometry']['geometry_evidence_role'],
                'archive_timestamp': (guardrail['record'].get('archive_capture') or {}).get('timestamp'),
                'original_first_party_url': guardrail['record'].get('first_party_original_url'),
                'asset_sha256': guardrail['record'].get('sha256'),
                'native_effective_size': native_size,
                'source_metrics': _guardrail_metrics(historical, source_native),
                'candidate_metrics': _guardrail_metrics(historical, candidate_native),
                'note': 'A coarse historical icon can test icon-scale consistency, but cannot establish high-resolution boundary placement.',
            }

    variants.sort(
        key=lambda item: (
            item['source_comparison']['summary']['max_premultiplied_rgba_rmse'],
            item['candidate']['bytes'],
        )
    )
    manifest = {
        'schema_version': 1,
        'experiment': 'first-party-current-render-guided-boundary-reconstruction',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'automatic_acceptance': False,
        'policy': {
            'geometry_source': 'current-first-party-svg-render',
            'human_sphere_geometry_used': False,
            'historical_first_party_low_resolution_used_only_as_guardrail': True,
            'review_required': True,
            'note': (
                'The candidate is reconstructed from the rendered appearance of the current first-party SVG. '
                'Third-party artwork is not used to define geometry. Any historical first-party icon is used only '
                'as an icon-scale consistency check when its resolution is too low for boundary reconstruction.'
            ),
        },
        'source': {
            'path': str(args.source),
            'sha256': sha256(args.source),
            'bytes': args.source.stat().st_size,
            'target': args.target,
        },
        'palette': {
            'endpoint_start': list(palette_info['endpoint_start']),
            'endpoint_end': list(palette_info['endpoint_end']),
            'endpoint_distance': palette_info['endpoint_distance'],
            'extra_colour_distance_threshold': args.extra_colour_distance,
            'extra_colour_min_opaque_fraction': args.extra_colour_min_fraction,
            'path_extra_colours': [
                {**item, 'rgb': list(item['rgb'])} for item in palette_info['path_extra_colours']
            ],
            'render_extra_colours': [
                {**item, 'rgb': list(item['rgb'])} for item in render_extras
            ],
            'extra_colours': [
                {**item, 'rgb': list(item['rgb'])} for item in extras
            ],
            'ordered_render_palette': [list(colour) for colour in ordered_colours],
            'class_pixel_counts': class_counts,
            'base_palette_index': base_index,
        },
        'mask_policy': {
            'render_size': args.mask_size,
            'alpha_threshold': args.alpha_threshold,
            'base': 'entire alpha silhouette',
            'overlays': 'nearest preserved flat-palette colour within the foreground',
        },
        'renderer': {
            'mode': 'shared-inkscape-shell',
            'inkscape_version': render_run.inkscape_version,
            'processes': render_run.renderer_processes,
            'document_opens': render_run.document_opens,
            'exports': render_run.exports,
            'seconds': render_run.render_seconds,
        },
        'historical_guardrail': (
            {
                'available': True,
                'geometry': guardrail['geometry'],
                'archive_timestamp': (guardrail['record'].get('archive_capture') or {}).get('timestamp'),
                'asset_sha256': guardrail['record'].get('sha256'),
                'source_authority': 'first-party-historical',
            }
            if guardrail is not None else {'available': False}
        ),
        'variants': variants,
        'best_by_source_rmse': variants[0] if variants else None,
        'smallest_candidate': min(variants, key=lambda item: item['candidate']['bytes']) if variants else None,
        'timing_seconds': {'total': time.perf_counter() - started},
    }
    manifest_path = args.output_dir / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')

    print(f"Source: {args.source.stat().st_size:,} B; palette layers={len(ordered_colours)}")
    for variant in sorted(variants, key=lambda item: item['simplify_px']):
        summary = variant['source_comparison']['summary']
        reduction = variant['candidate']['byte_reduction_fraction_vs_source']
        size_text = f"{reduction:.1%} reduction" if reduction >= 0 else f"{-reduction:.1%} growth"
        print(
            f"eps={variant['simplify_px']:g}: {variant['candidate']['bytes']:,} B "
            f"({size_text}), max premultiplied RMSE={summary['max_premultiplied_rgba_rmse']:.4f}"
        )
    if guardrail is not None:
        print(
            'Historical guardrail: '
            f"{guardrail['geometry']['effective_width']}x{guardrail['geometry']['effective_height']} effective pixels; "
            f"{guardrail['geometry']['geometry_evidence_role']}"
        )
    print(f'Wrote {manifest_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
