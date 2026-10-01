from __future__ import annotations

import argparse
import csv
import hashlib
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from lxml import etree
from PIL import Image

from .human_sphere_match import _descriptor, find_inkscape, render_svg_batch, visual_similarity

FIRST_PARTY_HOSTS = {"assets.infinitythegame.net", "assets.corvusbelli.net", "downloads.corvusbelli.com"}
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()



def first_party_url(url: str) -> bool:
    return (urllib.parse.urlparse(url).hostname or "").lower() in FIRST_PARTY_HOSTS


def validate_asset(data: bytes, kind: str) -> dict[str, Any]:
    if kind == "png":
        if not data.startswith(PNG_MAGIC):
            return {"valid": False, "error": "missing PNG signature"}
        try:
            with Image.open(BytesIO(data)) as image:
                image.verify()
            with Image.open(BytesIO(data)) as image:
                return {
                    "valid": True,
                    "format": image.format,
                    "width": image.width,
                    "height": image.height,
                    "mode": image.mode,
                }
        except Exception as exc:  # Pillow gives useful format errors here.
            return {"valid": False, "error": f"Pillow validation failed: {exc}"}
    if kind == "svg":
        try:
            root = etree.fromstring(data)
        except Exception as exc:
            return {"valid": False, "error": f"XML parse failed: {exc}"}
        local = etree.QName(root).localname if isinstance(root.tag, str) else ""
        return {"valid": local.lower() == "svg", "root": local}
    return {"valid": False, "error": f"unsupported kind {kind!r}"}


def http_get(url: str, *, timeout: float) -> tuple[bytes | None, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "InfinityDB-SVG-research/8.4 (+non-commercial provenance research)",
            "Accept-Encoding": "identity",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            data = response.read()
            return data, {
                "ok": True,
                "status": getattr(response, "status", 200),
                "final_url": response.geturl(),
                "content_type": response.headers.get_content_type(),
                "content_length_header": response.headers.get("Content-Length"),
            }
    except urllib.error.HTTPError as exc:
        return None, {"ok": False, "status": exc.code, "error": f"HTTPError: {exc}"}
    except Exception as exc:
        return None, {"ok": False, "status": None, "error": f"{type(exc).__name__}: {exc}"}


def cdx_query(url: str, *, start_year: int, end_year: int, timeout: float) -> tuple[list[dict[str, str]], dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "url": url,
            "output": "json",
            "filter": "statuscode:200",
            "from": str(start_year),
            "to": str(end_year),
            "collapse": "digest",
            "fl": "timestamp,original,mimetype,statuscode,digest,length",
        }
    )
    cdx_url = f"https://web.archive.org/cdx/search/cdx?{params}"
    data, meta = http_get(cdx_url, timeout=timeout)
    if data is None:
        return [], {"query_url": cdx_url, **meta}
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except Exception as exc:
        return [], {"query_url": cdx_url, "ok": False, "error": f"CDX JSON parse failed: {exc}"}
    if not payload or not isinstance(payload, list) or len(payload) < 2:
        return [], {"query_url": cdx_url, "ok": True, "captures": 0}
    headers = payload[0]
    captures = [dict(zip(headers, row, strict=False)) for row in payload[1:] if isinstance(row, list)]
    captures.sort(key=lambda row: row.get("timestamp", ""))
    return captures, {"query_url": cdx_url, "ok": True, "captures": len(captures)}


def select_captures(captures: list[dict[str, str]], maximum: int) -> list[dict[str, str]]:
    if maximum <= 0 or len(captures) <= maximum:
        return captures
    if maximum == 1:
        return [captures[-1]]
    indexes = {round(i * (len(captures) - 1) / (maximum - 1)) for i in range(maximum)}
    return [captures[i] for i in sorted(indexes)]


def archived_url(capture: dict[str, str]) -> str:
    original = capture["original"]
    if not first_party_url(original):
        raise ValueError(f"CDX capture did not preserve a first-party original URL: {original}")
    return f"https://web.archive.org/web/{capture['timestamp']}id_/{original}"


def write_asset(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def retrieval_record(
    *,
    target: dict[str, Any],
    locator: dict[str, Any],
    retrieval: str,
    source_url: str,
    data: bytes | None,
    transport: dict[str, Any],
    output_path: Path | None,
    capture: dict[str, str] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "target": target["slug"],
        "current_svg": target["current_svg"],
        "faction_id": target["faction_id"],
        "legacy_logo_id": target["legacy_logo_id"],
        "identity_confidence": target.get("identity_confidence"),
        "kind": locator["kind"],
        "first_party_original_url": locator["url"],
        "url_status": locator.get("url_status"),
        "retrieval": retrieval,
        "source_url": source_url,
        "transport": transport,
        "archive_capture": capture,
        "saved_path": str(output_path) if output_path else None,
    }
    if data is not None:
        validation = validate_asset(data, locator["kind"])
        record.update(
            {
                "bytes": len(data),
                "sha256": sha256_bytes(data),
                "validation": validation,
            }
        )
        if retrieval == "wayback" and validation.get("valid") and first_party_url(locator["url"]):
            record["provenance"] = {
                "source_authority": "first-party-historical",
                "independence": "independent-of-human-sphere",
                "provenance_status": "verified",
                "original_first_party_url": locator["url"],
                "archive_timestamp": (capture or {}).get("timestamp"),
                "archive_digest": (capture or {}).get("digest"),
                "note": "Validated bytes retrieved from a dated Wayback capture of a first-party Infinity Army asset URL.",
            }
        elif retrieval == "direct" and validation.get("valid") and first_party_url(locator["url"]):
            record["provenance"] = {
                "source_authority": "first-party-current",
                "independence": "independent-of-human-sphere",
                "provenance_status": "verified",
                "original_first_party_url": locator["url"],
                "note": "Current retrieval from a first-party URL. The historical age of the URL path does not by itself prove these bytes are historical.",
            }
    return record


def compare_assets(
    records: list[dict[str, Any]],
    *,
    svg_root: Path,
    output_dir: Path,
    inkscape: str,
    size: int,
) -> dict[str, Any]:
    eligible = [r for r in records if r.get("validation", {}).get("valid") and r.get("saved_path")]
    target_current_paths: dict[str, Path] = {}
    for record in eligible:
        current = svg_root / Path(record["current_svg"])
        if current.exists():
            target_current_paths[record["target"]] = current

    svg_render_inputs: list[Path] = []
    render_roles: list[tuple[str, str]] = []
    for target, path in sorted(target_current_paths.items()):
        svg_render_inputs.append(path)
        render_roles.append((target, "current"))
    for record in eligible:
        if record["kind"] == "svg":
            svg_render_inputs.append(Path(record["saved_path"]))
            render_roles.append((record["target"], f"asset:{record['sha256']}"))

    render_dir = output_dir / "comparison-renders"
    render_seconds = render_svg_batch(svg_render_inputs, render_dir, size, inkscape) if svg_render_inputs else 0.0
    render_map: dict[tuple[str, str], Path] = {}
    for index, role in enumerate(render_roles):
        render_map[role] = render_dir / f"svg-{index:05d}.png"

    descriptor_cache: dict[str, Any] = {}
    comparisons = 0
    for record in eligible:
        current_render = render_map.get((record["target"], "current"))
        if current_render is None:
            record["comparison_to_current"] = {"available": False, "reason": "current SVG not found"}
            continue
        current_key = str(current_render)
        left = descriptor_cache.get(current_key)
        if left is None:
            left = _descriptor(current_render)
            descriptor_cache[current_key] = left

        if record["kind"] == "svg":
            candidate_path = render_map[(record["target"], f"asset:{record['sha256']}")]
        else:
            candidate_path = Path(record["saved_path"])
        candidate_key = str(candidate_path)
        right = descriptor_cache.get(candidate_key)
        if right is None:
            right = _descriptor(candidate_path)
            descriptor_cache[candidate_key] = right
        record["comparison_to_current"] = {
            "available": True,
            "render_size": size,
            **visual_similarity(left, right),
        }
        comparisons += 1
    return {"render_seconds": render_seconds, "comparisons": comparisons, "rendered_svgs": len(svg_render_inputs)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe historical first-party Infinity Army logo URLs and optionally retrieve Wayback snapshots."
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path(__file__).with_name("historical-army-assets.json"),
        help="historical Army asset target/evidence manifest",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("historical-army-probe"))
    parser.add_argument("--fetch-direct", action="store_true", help="try the first-party URL as served today")
    parser.add_argument("--wayback", action="store_true", help="query CDX and fetch dated archived captures")
    parser.add_argument("--wayback-max-snapshots", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--svg-root", type=Path, help="current Army SVG root, for visual comparison")
    parser.add_argument("--inkscape", help="Inkscape executable for comparison rendering")
    parser.add_argument("--visual-size", type=int, default=256)
    args = parser.parse_args()

    payload = json.loads(args.evidence.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    plan: list[dict[str, Any]] = []
    for target in payload.get("targets", []):
        for locator in target.get("assets", []):
            if not first_party_url(locator["url"]):
                raise SystemExit(f"Refusing non-first-party asset URL in evidence manifest: {locator['url']}")
            plan.append(
                {
                    "target": target["slug"],
                    "current_svg": target["current_svg"],
                    "kind": locator["kind"],
                    "url": locator["url"],
                    "url_status": locator.get("url_status"),
                    "wayback_from": locator.get("wayback_from"),
                    "wayback_to": locator.get("wayback_to"),
                }
            )

            target_dir = args.output_dir / "assets" / target["slug"]
            if args.fetch_direct:
                data, transport = http_get(locator["url"], timeout=args.timeout)
                suffix = ".svg" if locator["kind"] == "svg" else ".png"
                path = target_dir / f"direct{suffix}" if data is not None else None
                if data is not None:
                    write_asset(path, data)
                records.append(
                    retrieval_record(
                        target=target,
                        locator=locator,
                        retrieval="direct",
                        source_url=locator["url"],
                        data=data,
                        transport=transport,
                        output_path=path,
                    )
                )

            if args.wayback:
                captures, cdx_meta = cdx_query(
                    locator["url"],
                    start_year=int(locator.get("wayback_from", 2000)),
                    end_year=int(locator.get("wayback_to", datetime.now().year)),
                    timeout=args.timeout,
                )
                chosen = select_captures(captures, args.wayback_max_snapshots)
                if not chosen:
                    records.append(
                        {
                            "target": target["slug"],
                            "current_svg": target["current_svg"],
                            "kind": locator["kind"],
                            "first_party_original_url": locator["url"],
                            "url_status": locator.get("url_status"),
                            "retrieval": "wayback",
                            "cdx": cdx_meta,
                            "archive_capture": None,
                            "saved_path": None,
                        }
                    )
                for capture in chosen:
                    source = archived_url(capture)
                    data, transport = http_get(source, timeout=args.timeout)
                    suffix = ".svg" if locator["kind"] == "svg" else ".png"
                    path = target_dir / f"wayback-{capture['timestamp']}{suffix}" if data is not None else None
                    if data is not None:
                        write_asset(path, data)
                    record = retrieval_record(
                        target=target,
                        locator=locator,
                        retrieval="wayback",
                        source_url=source,
                        data=data,
                        transport=transport,
                        output_path=path,
                        capture=capture,
                    )
                    record["cdx"] = cdx_meta
                    records.append(record)

    comparison_summary = None
    if args.svg_root and records:
        inkscape = find_inkscape(args.inkscape)
        comparison_summary = compare_assets(
            records,
            svg_root=args.svg_root,
            output_dir=args.output_dir,
            inkscape=inkscape,
            size=args.visual_size,
        )

    result = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Historical first-party Infinity Army logo provenance probe",
        "policy": payload.get("policy", {}),
        "evidence_file": str(args.evidence),
        "common_evidence": payload.get("common_evidence", []),
        "run": {
            "fetch_direct": args.fetch_direct,
            "wayback": args.wayback,
            "wayback_max_snapshots": args.wayback_max_snapshots,
            "svg_root": str(args.svg_root) if args.svg_root else None,
            "visual_size": args.visual_size if args.svg_root and records else None,
            "comparison": comparison_summary,
        },
        "plan": plan,
        "records": records,
    }
    (args.output_dir / "probe-results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    csv_fields = [
        "target",
        "current_svg",
        "kind",
        "retrieval",
        "first_party_original_url",
        "url_status",
        "archive_timestamp",
        "transport_ok",
        "transport_status",
        "validation_valid",
        "bytes",
        "sha256",
        "source_authority",
        "provenance_status",
        "visual_score_to_current",
        "edge_correlation_to_current",
        "gray_correlation_to_current",
        "alpha_iou_to_current",
        "saved_path",
        "error",
    ]
    csv_rows: list[dict[str, Any]] = []
    for record in records:
        capture = record.get("archive_capture") or {}
        transport = record.get("transport") or {}
        validation = record.get("validation") or {}
        provenance = record.get("provenance") or {}
        comparison = record.get("comparison_to_current") or {}
        csv_rows.append(
            {
                "target": record.get("target", ""),
                "current_svg": record.get("current_svg", ""),
                "kind": record.get("kind", ""),
                "retrieval": record.get("retrieval", ""),
                "first_party_original_url": record.get("first_party_original_url", ""),
                "url_status": record.get("url_status", ""),
                "archive_timestamp": capture.get("timestamp", ""),
                "transport_ok": transport.get("ok", ""),
                "transport_status": transport.get("status", ""),
                "validation_valid": validation.get("valid", ""),
                "bytes": record.get("bytes", ""),
                "sha256": record.get("sha256", ""),
                "source_authority": provenance.get("source_authority", ""),
                "provenance_status": provenance.get("provenance_status", ""),
                "visual_score_to_current": comparison.get("visual_score", ""),
                "edge_correlation_to_current": comparison.get("edge_correlation", ""),
                "gray_correlation_to_current": comparison.get("gray_correlation", ""),
                "alpha_iou_to_current": comparison.get("alpha_iou", ""),
                "saved_path": record.get("saved_path", ""),
                "error": transport.get("error", validation.get("error", "")),
            }
        )
    with (args.output_dir / "probe-results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields)
        writer.writeheader()
        writer.writerows(csv_rows)

    verified = [r for r in records if (r.get("provenance") or {}).get("provenance_status") == "verified"]
    first_party_manifest = {
        "schema_version": 1,
        "generated_at": result["generated_at"],
        "automatic_acceptance": False,
        "assets": [
            {
                "target": r["target"],
                "current_svg": r["current_svg"],
                "asset_kind": r["kind"],
                "asset_sha256": r.get("sha256"),
                "asset_path": r.get("saved_path"),
                "source_url": r.get("source_url"),
                **(r.get("provenance") or {}),
                "comparison_to_current": r.get("comparison_to_current"),
            }
            for r in verified
        ],
    }
    (args.output_dir / "verified-first-party-assets.json").write_text(
        json.dumps(first_party_manifest, indent=2), encoding="utf-8"
    )

    print(f"Targets: {len(payload.get('targets', []))} | asset locators: {len(plan)}")
    if not args.fetch_direct and not args.wayback:
        print("Plan-only run: pass --fetch-direct and/or --wayback to retrieve assets.")
    else:
        print(f"Retrieval records: {len(records)} | verified first-party assets: {len(verified)}")
    if comparison_summary:
        print(
            f"Visual comparisons: {comparison_summary['comparisons']} | "
            f"Inkscape render time: {comparison_summary['render_seconds']:.2f}s"
        )
    print(f"Wrote {args.output_dir / 'probe-results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
