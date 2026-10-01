from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

ARMY_STYLE_RE = re.compile(r"^(?:\d+px-)?(.+)-1-1\.png$", re.IGNORECASE)
VYO_MARKER_RE = re.compile(r"(?:^|[-_])vyo(?:[-_.]|$)", re.IGNORECASE)


def _basename(path: str) -> str:
    return PureWindowsPath(path).name


def provenance_hints(png_relative_path: str) -> list[str]:
    value = png_relative_path.replace("/", "\\")
    lower = value.lower()
    filename = _basename(value)
    name_lower = filename.lower()
    hints: list[str] = []
    if "\\thumb\\" in lower:
        hints.append("wiki-thumbnail")
    if ARMY_STYLE_RE.match(filename):
        hints.append("army-style-render-name")
    if "-n3-" in name_lower:
        hints.append("historical-n3-marker")
    if "-a6-" in name_lower:
        hints.append("historical-a6-marker")
    if "-old-" in name_lower:
        hints.append("historical-old-marker")
    if VYO_MARKER_RE.search(filename):
        hints.append("vyo-fan-vector-marker")
    if "assets.corvusbelli.net" in lower:
        hints.append("corvus-belli-origin-path-hint")
    if not hints:
        hints.append("generic-human-sphere-media")
    return hints


def relation_label(candidate: dict[str, Any]) -> str:
    visual = candidate.get("visual_score")
    lexical = float(candidate.get("lexical_score", 0.0))
    if visual is None:
        return "not-visually-scored"
    visual = float(visual)
    if visual >= 0.98 and lexical >= 0.70:
        return "near-identical-render-correspondence"
    if visual >= 0.90 and lexical >= 0.65:
        return "strong-visual-correspondence"
    if visual >= 0.75 and lexical >= 0.55:
        return "probable-visual-correspondence"
    if visual >= 0.55 and lexical >= 0.40:
        return "possible-visual-correspondence"
    return "weak-or-unrelated"


def evidence_role(hints: list[str], relation: str, provenance: dict[str, Any] | None = None) -> str:
    provenance = provenance or {}
    authority = provenance.get("source_authority")
    status = provenance.get("provenance_status")
    independence = provenance.get("independence")
    if authority in {"first-party-current", "first-party-historical"} and status == "verified":
        return "verified-first-party-reference"
    if "vyo-fan-vector-marker" in hints:
        return "likely-vyo-fan-vector-reference-low-authority"
    if independence in {"derived", "likely-derived"}:
        return "likely-derived-reference-low-independent-value"
    strong = relation in {
        "near-identical-render-correspondence",
        "strong-visual-correspondence",
        "probable-visual-correspondence",
    }
    if "army-style-render-name" in hints:
        return "likely-derivative-or-current-render-lead-low-independent-value"
    if any(x.startswith("historical-") for x in hints):
        return "historical-third-party-reference-review" if strong else "historical-third-party-lead-review"
    if "corvus-belli-origin-path-hint" in hints:
        return "possible-first-party-origin-requires-independent-verification"
    if strong:
        return "third-party-visual-reference-review"
    return "third-party-lead-only"


def review_value(hints: list[str], relation: str, provenance: dict[str, Any] | None = None) -> str:
    provenance = provenance or {}
    authority = provenance.get("source_authority")
    status = provenance.get("provenance_status")
    if authority in {"first-party-current", "first-party-historical"} and status == "verified":
        if relation in {"near-identical-render-correspondence", "strong-visual-correspondence"}:
            return "verified-first-party-high-value"
        if relation == "probable-visual-correspondence":
            return "verified-first-party-medium-value"
    if "vyo-fan-vector-marker" in hints:
        return "fan-reference-only"
    if "army-style-render-name" in hints:
        if relation in {"near-identical-render-correspondence", "strong-visual-correspondence"}:
            return "derivative-check-only"
        return "low"
    historical = any(x.startswith("historical-") for x in hints)
    if historical and relation in {"near-identical-render-correspondence", "strong-visual-correspondence"}:
        return "high-review-value"
    if historical and relation == "probable-visual-correspondence":
        return "medium-review-value"
    if relation in {"near-identical-render-correspondence", "strong-visual-correspondence"}:
        return "medium-review-value"
    if relation == "probable-visual-correspondence":
        return "low-review-value"
    return "low"


def describe_candidate(
    candidate: dict[str, Any] | None,
    provenance_lookup: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if candidate is None:
        return None
    png = candidate["png"]
    hints = provenance_hints(png["relative_path"])
    relation = relation_label(candidate)
    provenance_lookup = provenance_lookup or {}
    provenance = provenance_lookup.get(f"sha256:{png.get('sha256')}") or provenance_lookup.get(
        f"path:{png['relative_path'].replace('/', '\\').lower()}"
    ) or {}
    return {
        "rank": candidate.get("rank"),
        "png": png["relative_path"],
        "png_sha256": png.get("sha256"),
        "width": png.get("width"),
        "height": png.get("height"),
        "lexical_score": candidate.get("lexical_score"),
        "visual_score": candidate.get("visual_score"),
        "combined_score": candidate.get("combined_score", candidate.get("lexical_score")),
        "edge_correlation": candidate.get("edge_correlation"),
        "gray_correlation": candidate.get("gray_correlation"),
        "alpha_iou": candidate.get("alpha_iou"),
        "provenance_hints": hints,
        "provenance_override": provenance or None,
        "relation": relation,
        "evidence_role": evidence_role(hints, relation, provenance),
        "review_value": review_value(hints, relation, provenance),
    }


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[float, float, str]:
    visual = candidate.get("visual_score")
    combined = candidate.get("combined_score", candidate.get("lexical_score", 0.0))
    return (
        float(visual) if visual is not None else -1.0,
        float(combined),
        candidate["png"]["relative_path"].lower(),
    )


def choose(candidates: list[dict[str, Any]], predicate) -> dict[str, Any] | None:
    eligible = [c for c in candidates if predicate(c)]
    return max(eligible, key=_candidate_sort_key) if eligible else None


def provenance_ledger(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    lookup: dict[str, dict[str, Any]] = {}
    for entry in payload.get("entries", []):
        sha = entry.get("png_sha256")
        rel = entry.get("png_relative_path")
        if sha:
            lookup[f"sha256:{sha}"] = entry
        if rel:
            lookup[f"path:{str(rel).replace('/', '\\').lower()}"] = entry
    return lookup


def scan_index(scan_path: Path | None) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    if scan_path is None:
        return {}, None
    payload = json.loads(scan_path.read_text(encoding="utf-8"))
    rows = payload.get("files", [])
    index = {str(row.get("path", "")).replace("/", "\\").lower(): row for row in rows}
    return index, payload.get("summary")


def flatten(prefix: str, item: dict[str, Any] | None) -> dict[str, Any]:
    keys = [
        "rank", "png", "png_sha256", "width", "height", "lexical_score", "visual_score",
        "combined_score", "edge_correlation", "gray_correlation", "alpha_iou", "relation",
        "evidence_role", "review_value",
    ]
    out: dict[str, Any] = {}
    if item is None:
        for key in keys:
            out[f"{prefix}_{key}"] = ""
        out[f"{prefix}_provenance_hints"] = ""
        return out
    for key in keys:
        out[f"{prefix}_{key}"] = item.get(key, "")
    out[f"{prefix}_provenance_hints"] = ";".join(item.get("provenance_hints", []))
    provenance = item.get("provenance_override") or {}
    for key in ["source_authority", "independence", "provenance_status", "source_url", "note"]:
        out[f"{prefix}_provenance_{key}"] = provenance.get(key, "")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Review Human Sphere candidate matches without treating Human Sphere as authoritative."
    )
    parser.add_argument("matches", type=Path, help="matches.json produced by human_sphere_match.py")
    parser.add_argument("--scan", type=Path, help="optional scanner JSON; when present only flagged SVGs are emitted by default")
    parser.add_argument("--include-unflagged", action="store_true")
    parser.add_argument(
        "--provenance-ledger",
        type=Path,
        help="optional manual provenance ledger; verified entries override filename heuristics",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("human-sphere-review"))
    args = parser.parse_args()

    payload = json.loads(args.matches.read_text(encoding="utf-8"))
    scan, scan_summary = scan_index(args.scan)
    provenance_lookup = provenance_ledger(args.provenance_ledger)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    csv_rows: list[dict[str, Any]] = []
    for entry in payload.get("matches", []):
        svg = entry["svg"]
        rel = svg["relative_path"].replace("/", "\\")
        scan_row = scan.get(rel.lower())
        if args.scan and not args.include_unflagged and not (scan_row and scan_row.get("flagged")):
            continue

        candidates = entry.get("candidates", [])
        top = candidates[0] if candidates else None
        historical = choose(
            candidates,
            lambda c: any(
                h.startswith("historical-") for h in provenance_hints(c["png"]["relative_path"])
            ),
        )
        non_derivative = choose(
            candidates,
            lambda c: "army-style-render-name" not in provenance_hints(c["png"]["relative_path"]),
        )
        cb_origin = choose(
            candidates,
            lambda c: "corvus-belli-origin-path-hint" in provenance_hints(c["png"]["relative_path"]),
        )

        top_desc = describe_candidate(top, provenance_lookup)
        historical_desc = describe_candidate(historical, provenance_lookup)
        non_derivative_desc = describe_candidate(non_derivative, provenance_lookup)
        cb_origin_desc = describe_candidate(cb_origin, provenance_lookup)

        # Prefer historical visual correspondence as an investigation lead, then a potential CB-origin
        # path, then other non-derivative correspondence. This is a review queue, never acceptance.
        review_desc = None
        review_reason = "no-useful-candidate"
        for candidate_desc, reason in [
            (historical_desc, "historical-third-party-reference"),
            (cb_origin_desc, "possible-origin-verification"),
            (non_derivative_desc, "non-derivative-visual-lead"),
            (top_desc, "top-ranked-lead"),
        ]:
            if candidate_desc is None:
                continue
            if candidate_desc["relation"] not in {"weak-or-unrelated", "not-visually-scored"}:
                review_desc = candidate_desc
                review_reason = reason
                break
        if review_desc is None:
            review_desc = top_desc

        row = {
            "svg": svg,
            "scan": {
                "flagged": bool(scan_row.get("flagged")) if scan_row else None,
                "classification": scan_row.get("classification") if scan_row else None,
                "severity": scan_row.get("severity") if scan_row else None,
                "advisories": scan_row.get("advisories", []) if scan_row else [],
                "signals": scan_row.get("signals", []) if scan_row else [],
            },
            "top_candidate": top_desc,
            "best_historical_candidate": historical_desc,
            "best_non_derivative_candidate": non_derivative_desc,
            "best_cb_origin_hint_candidate": cb_origin_desc,
            "review_candidate": review_desc,
            "review_reason": review_reason,
        }
        rows.append(row)

        flat = {
            "svg": rel,
            "classification": row["scan"]["classification"] or "",
            "severity": row["scan"]["severity"] or "",
            "advisories": ";".join(row["scan"]["advisories"]),
            "review_reason": review_reason,
        }
        flat.update(flatten("review", review_desc))
        flat.update(flatten("top", top_desc))
        flat.update(flatten("historical", historical_desc))
        flat.update(flatten("non_derivative", non_derivative_desc))
        csv_rows.append(flat)

    authority_counts = Counter(
        (row["review_candidate"] or {}).get("review_value", "none") for row in rows
    )
    relation_counts = Counter(
        (row["review_candidate"] or {}).get("relation", "none") for row in rows
    )
    output = {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Human Sphere match review with explicit source-authority and independence guardrails",
        "policy": {
            "human_sphere_authority": "third-party-non-authoritative",
            "automatic_acceptance": False,
            "independence_not_assumed": True,
            "filename_provenance_hints_are_heuristic": True,
            "corvus_belli_origin_path_hint_requires_verification": True,
            "vyo_filename_marker_is_fan_provenance_warning": True,
            "manual_provenance_overrides_require_explicit_verified_status": True,
            "note": (
                "A matching Human Sphere PNG is evidence for investigation only. Presence, high visual "
                "similarity, or a first-party-looking filename/path does not establish current canonical artwork."
            ),
        },
        "source_matches": str(args.matches),
        "source_scan": str(args.scan) if args.scan else None,
        "source_provenance_ledger": str(args.provenance_ledger) if args.provenance_ledger else None,
        "scan_summary": scan_summary,
        "summary": {
            "reviewed_svgs": len(rows),
            "review_value_counts": dict(authority_counts),
            "review_relation_counts": dict(relation_counts),
        },
        "reviews": rows,
    }
    (args.output_dir / "review.json").write_text(json.dumps(output, indent=2), encoding="utf-8")

    fieldnames = list(csv_rows[0].keys()) if csv_rows else ["svg"]
    with (args.output_dir / "review.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)

    investigation_leads = [
        row for row in csv_rows
        if row.get("review_relation") not in {"", "none", "weak-or-unrelated", "not-visually-scored"}
        and row.get("review_review_value") != "derivative-check-only"
    ]
    with (args.output_dir / "investigation-leads.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(investigation_leads)

    restoration_leads = [
        row for row in csv_rows
        if row.get("review_review_value") in {
            "verified-first-party-high-value",
            "verified-first-party-medium-value",
            "high-review-value",
            "medium-review-value",
        }
        and "vyo-fan-vector-marker" not in row.get("review_provenance_hints", "")
    ]
    with (args.output_dir / "restoration-leads.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(restoration_leads)

    fan_derived = [
        row for row in csv_rows
        if "vyo-fan-vector-marker" in row.get("review_provenance_hints", "")
    ]
    with (args.output_dir / "fan-derived-reference-leads.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(fan_derived)

    derivative = [row for row in csv_rows if row.get("top_review_value") == "derivative-check-only"]
    with (args.output_dir / "derivative-like-top-matches.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(derivative)

    print(f"Reviewed SVGs: {len(rows)}")
    print(f"Investigation leads: {len(investigation_leads)}")
    print(f"Restoration/reference review leads: {len(restoration_leads)}")
    print(f"Likely Vyo/fan-derived review leads: {len(fan_derived)}")
    print(f"Derivative-like top matches: {len(derivative)}")
    print(f"Wrote {args.output_dir / 'review.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
