from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _resolve_saved_path(raw: str | None, manifest: Path) -> Path | None:
    if not raw:
        return None
    # Windows manifests use backslashes even when reviewed on another OS.
    normalized = Path(raw.replace('\\', '/'))
    candidates = [normalized]
    if not normalized.is_absolute():
        candidates.extend([
            manifest.parent / normalized,
            manifest.parent.parent / normalized,
        ])
        if normalized.parts and normalized.parts[0].lower() == manifest.parent.name.lower():
            candidates.append(manifest.parent / Path(*normalized.parts[1:]))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _png_effective_geometry(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        rgba = image.convert('RGBA')
        alpha = rgba.getchannel('A')
        bbox = alpha.point(lambda value: 255 if value > 8 else 0).getbbox()
        if bbox is None:
            bbox = (0, 0, rgba.width, rgba.height)
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        effective_max = max(width, height)
        if effective_max <= 32:
            role = 'coarse-icon-guardrail-only'
        elif effective_max <= 128:
            role = 'medium-resolution-reference'
        else:
            role = 'high-resolution-reference'
        return {
            'canvas_width': rgba.width,
            'canvas_height': rgba.height,
            'alpha_bbox': list(bbox),
            'effective_width': width,
            'effective_height': height,
            'effective_max_dimension': effective_max,
            'geometry_evidence_role': role,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description='Summarize authority and usable geometry precision from a historical Army probe.')
    parser.add_argument('probe_results', type=Path)
    parser.add_argument('--svg-root', type=Path)
    parser.add_argument('--output-dir', type=Path, default=Path('historical-evidence-analysis'))
    args = parser.parse_args()

    payload = json.loads(args.probe_results.read_text(encoding='utf-8'))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in payload.get('records', []):
        grouped[record['target']].append(record)

    summaries: list[dict[str, Any]] = []
    for target, records in sorted(grouped.items()):
        current_svg_rel = records[0].get('current_svg')
        current_svg = args.svg_root / Path(current_svg_rel) if args.svg_root and current_svg_rel else None
        current_hash = sha256(current_svg) if current_svg and current_svg.exists() else None

        direct_svg = [r for r in records if r.get('retrieval') == 'direct' and r.get('kind') == 'svg' and r.get('validation', {}).get('valid')]
        historical_svg = [r for r in records if r.get('retrieval') == 'wayback' and r.get('kind') == 'svg' and r.get('validation', {}).get('valid')]
        direct_png = [r for r in records if r.get('retrieval') == 'direct' and r.get('kind') == 'png' and r.get('validation', {}).get('valid')]
        historical_png = [r for r in records if r.get('retrieval') == 'wayback' and r.get('kind') == 'png' and r.get('validation', {}).get('valid')]

        historical_png_details = []
        for record in historical_png:
            resolved = _resolve_saved_path(record.get('saved_path'), args.probe_results)
            detail = {
                'sha256': record.get('sha256'),
                'archive_timestamp': (record.get('archive_capture') or {}).get('timestamp'),
                'original_first_party_url': record.get('first_party_original_url'),
                'resolved_path': str(resolved) if resolved else None,
            }
            if resolved:
                detail.update(_png_effective_geometry(resolved))
            historical_png_details.append(detail)

        direct_png_hashes = {r.get('sha256') for r in direct_png if r.get('sha256')}
        historical_png_hashes = {r.get('sha256') for r in historical_png if r.get('sha256')}
        stable_png_bytes = bool(historical_png_hashes) and historical_png_hashes.issubset(direct_png_hashes)
        direct_svg_hashes = {r.get('sha256') for r in direct_svg if r.get('sha256')}
        direct_svg_matches_current = bool(current_hash and current_hash in direct_svg_hashes)

        roles = [d.get('geometry_evidence_role') for d in historical_png_details if d.get('geometry_evidence_role')]
        if historical_svg:
            best_role = 'historical-vector-reference'
        elif 'high-resolution-reference' in roles:
            best_role = 'high-resolution-first-party-raster-reference'
        elif 'medium-resolution-reference' in roles:
            best_role = 'medium-resolution-first-party-raster-reference'
        elif 'coarse-icon-guardrail-only' in roles:
            best_role = 'coarse-first-party-icon-guardrail-only'
        else:
            best_role = 'no-verified-historical-geometry-reference'

        summaries.append({
            'target': target,
            'current_svg': current_svg_rel,
            'current_svg_sha256': current_hash,
            'direct_current_svg_count': len(direct_svg),
            'direct_svg_matches_local_current': direct_svg_matches_current,
            'historical_svg_count': len(historical_svg),
            'direct_png_count': len(direct_png),
            'historical_png_count': len(historical_png),
            'historical_png_byte_identical_to_direct': stable_png_bytes,
            'best_verified_first_party_geometry_role': best_role,
            'historical_pngs': historical_png_details,
            'boundary_reconstruction_authority': (
                'sufficient-first-party-historical-vector' if historical_svg else
                'insufficient-for-high-resolution-boundaries'
            ),
        })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_json = args.output_dir / 'historical-evidence-summary.json'
    out_csv = args.output_dir / 'historical-evidence-summary.csv'
    result = {
        'schema_version': 1,
        'source_probe': str(args.probe_results),
        'policy': {
            'historical_first_party_authority_does_not_imply_high_resolution_geometry': True,
            'coarse_icons_are_guardrails_not_boundary_sources': True,
            'current_first_party_svg_remains_primary_current_artwork_baseline': True,
        },
        'targets': summaries,
    }
    out_json.write_text(json.dumps(result, indent=2), encoding='utf-8')
    fields = [
        'target','current_svg','direct_svg_matches_local_current','historical_svg_count',
        'historical_png_count','historical_png_byte_identical_to_direct',
        'best_verified_first_party_geometry_role','boundary_reconstruction_authority',
    ]
    with out_csv.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in summaries:
            writer.writerow({k: row.get(k) for k in fields})
    print(f'Analyzed {len(summaries)} target(s).')
    for row in summaries:
        print(f"{row['target']}: {row['best_verified_first_party_geometry_role']}; historical SVGs={row['historical_svg_count']}; historical PNGs={row['historical_png_count']}")
    print(f'Wrote {out_json}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
