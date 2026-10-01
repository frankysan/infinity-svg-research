"""Build a provenance-preserving Vyo/Army identity and review ledger.

Names propose identities. Only explicit review decisions can confirm a match or
absence; neither a low similarity score nor an archive-name gap proves absence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def subject_from_path(path: str) -> str:
    subject = re.sub(r"-\d+-\d+$", "", Path(path).stem)
    return re.sub(r"-null-\d+$", "", subject.removeprefix("reinf-"))


def name_tokens(name: str) -> tuple[str, ...]:
    name = re.sub(r"\[[^]]*\]", " ", name)
    name = re.sub(r"\b(?:v\d+|copy)\b", " ", name, flags=re.IGNORECASE)
    name = re.sub(r"\bremote\s+\d+\b", " ", name, flags=re.IGNORECASE)
    name = unicodedata.normalize("NFKD", name.casefold()).encode("ascii", "ignore").decode()
    return tuple(re.findall(r"[a-z0-9]+", name))


def name_relation(army: str, vyo: str) -> str | None:
    left, right = name_tokens(army), name_tokens(vyo)
    if not left or not right:
        return None
    if left == right:
        return "exact-normalized-name"
    # Singular/plural and descriptor containment remain review proposals.
    singular = lambda words: tuple(w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words)
    a, b = singular(left), singular(right)
    if a == b:
        return "singular-plural-name"
    short, long = sorted((a, b), key=len)
    if sum(map(len, short)) < 5:
        return None
    if any(long[i : i + len(short)] == short for i in range(len(long) - len(short) + 1)):
        return "descriptor-containment"
    return None


def classify(file: dict) -> tuple[str, list[str]]:
    features = set(file.get("features", []))
    if file.get("images", 0) or "embedded_or_external_image" in features:
        return "reconstruct", ["raster-or-external-image"]
    reasons = []
    if file.get("texts", 0) or "text" in features:
        reasons.append("font-resolution-and-publication-outlining")
    if "gradient" in features:
        reasons.append("review-intentional-gradient")
    if "clip_path" in features:
        reasons.append("review-clip-semantics")
    return ("minor-cleanup", reasons) if reasons else ("reuse", [])


def build_identity_map(inventory: dict, army: dict, publication: dict, decisions: dict) -> dict:
    artifact = army["snapshot"]["armyArtifact"]
    if publication["sourceSnapshot"]["armyArtifact"]["sha256"] != artifact["sha256"]:
        raise ValueError("Army and publication manifests describe different snapshots")
    files = {f["path"]: f for f in inventory["files"]}
    if len(files) != len(inventory["files"]):
        raise ValueError("duplicate Vyo inventory paths")
    assets = {a["url"]: a for a in army["assets"]}
    assets_by_path = {a["archivePath"]: a for a in army["assets"]}
    canonical = publication["canonicalArchivePathToPublishedPath"]
    published_to_canonical = {v: k for k, v in canonical.items()}
    if len(published_to_canonical) != len(canonical):
        raise ValueError("publication canonical destinations must be unique")
    groups = defaultdict(list)
    for reference in army["references"]:
        if reference.get("authoritative") is not True:
            continue
        asset = assets[reference["assetUrl"]]
        published = publication["sourceArchivePathToPublishedPath"][asset["archivePath"]]
        groups[published_to_canonical[published]].append((reference, asset))
    exact_hash_subjects = defaultdict(set)
    for pairs in groups.values():
        for _, asset in pairs:
            exact_hash_subjects[asset["sha256"]].add(subject_from_path(asset["archivePath"]))
    for rule in decisions.get("rules", []):
        if rule["status"] not in {
            "alias-candidate",
            "reviewed-match",
            "reviewed-design-mismatch",
            "confirmed-missing",
        }:
            raise ValueError(f"invalid decision status: {rule['status']}")
        if not rule.get("evidence"):
            raise ValueError("identity decisions need evidence")
        if rule.get("action") not in {None, "reuse", "minor-cleanup", "reconstruct"}:
            raise ValueError("invalid review action")
        for path in rule.get("vyo_paths", []):
            if path not in files:
                raise ValueError(f"decision references absent Vyo path: {path}")
        if rule["status"] in {"reviewed-match", "reviewed-design-mismatch"} and not rule.get(
            "vyo_paths"
        ):
            raise ValueError("reviewed matches need explicit Vyo paths")
        if rule["status"] == "confirmed-missing" and rule.get("vyo_paths"):
            raise ValueError("missing decisions cannot select Vyo paths")
        if rule["status"] == "confirmed-missing" and not rule.get("army_paths"):
            raise ValueError("confirmed absence must be scoped to explicit Army profile paths")
        if rule.get("army_paths") and not set(rule["army_paths"]).issubset(canonical):
            raise ValueError("decision references absent canonical Army path")
        for source in rule.get("review_source_assets", []):
            actual = assets_by_path.get(source["path"])
            if actual is None or actual["sha256"] != source["sha256"]:
                raise ValueError(f"reviewed Army source changed: {source['path']}")
        for source in rule.get("review_vyo_assets", []):
            actual = files.get(source["path"])
            if actual is None or actual["sha256"] != source["sha256"]:
                raise ValueError(f"reviewed Vyo source changed: {source['path']}")
        if rule["status"] in {"reviewed-match", "reviewed-design-mismatch"} and not rule.get(
            "army_paths"
        ):
            raise ValueError("reviewed matches must be scoped to explicit Army profile paths")
    rows = []
    used_rules = set()
    for path, published in sorted(canonical.items()):
        pairs = groups.get(path, [])
        kinds = sorted({r["kind"] for r, _ in pairs})
        scope = "unit" if "unit-profile" in kinds else "faction" if "faction" in kinds else "static"
        subjects = {subject_from_path(a["archivePath"]) for _, a in pairs}
        aliases = set(subjects)
        for _, asset in pairs:
            aliases.update(exact_hash_subjects[asset["sha256"]])
        candidates = {}
        if scope == "unit":
            for file in files.values():
                if (
                    file["folder"] in {"Aristeia", "Others"}
                    or "Logo" in file["subject"]
                    or "Sectorial" in file["subject"]
                ):
                    continue
                reasons = sorted(
                    {
                        relation
                        for name in aliases
                        if (relation := name_relation(name, file["subject"]))
                    }
                )
                if reasons:
                    candidates[file["path"]] = reasons
        rules = []
        for index, rule in enumerate(decisions.get("rules", [])):
            applies = (
                path in rule.get("army_paths", [])
                if rule.get("army_paths")
                else bool(subjects.intersection(rule.get("army_subjects", [])))
            )
            if applies:
                used_rules.add(index)
                rules.append(rule)
                for candidate in rule.get("vyo_paths", []):
                    candidates.setdefault(candidate, []).append("explicit-identity-rule")
        reviewed = [
            r
            for r in rules
            if r["status"] in {"reviewed-match", "reviewed-design-mismatch", "confirmed-missing"}
        ]
        if len(reviewed) > 1:
            raise ValueError(f"conflicting reviewed decisions for {path}")
        decision = reviewed[0] if reviewed else None
        if decision and decision["status"] == "confirmed-missing":
            candidates = {}
        elif decision:
            candidates = {p: ["explicit-reviewed-match"] for p in decision["vyo_paths"]}
        candidate_rows = []
        for vyo_path, reasons in sorted(candidates.items()):
            file = files[vyo_path]
            action, blockers = classify(file)
            if decision and decision.get("action"):
                action = decision["action"]
                blockers = sorted(set(blockers + decision.get("reasons", [])))
            candidate_rows.append(
                {
                    "path": vyo_path,
                    "sha256": file["sha256"],
                    "subject": file["subject"],
                    "tags": file["tags"],
                    "matched_by": sorted(set(reasons)),
                    "action": action,
                    "reasons": blockers,
                    "source_authority": "second-party",
                    "source_type": "fan-vector",
                }
            )
        if decision:
            status = decision["status"]
        elif scope == "static":
            status = "out-of-scope"
        elif candidate_rows:
            status = "name-candidate"
        else:
            status = "unresolved"
        actions = {c["action"] for c in candidate_rows}
        action = next((a for a in ("reuse", "minor-cleanup", "reconstruct") if a in actions), None)
        row = {
            "army_path": path,
            "published_path": published,
            "scope": scope,
            "subjects": sorted(subjects),
            "exact_source_hash_aliases": sorted(aliases - subjects),
            "source_assets": [
                {"path": p, "sha256": h, "url": u, "source_method": m}
                for p, h, u, m in sorted(
                    {
                        (a["archivePath"], a["sha256"], a["url"], a.get("sourceMethod", "unknown"))
                        for _, a in pairs
                    }
                )
            ],
            "profile_references": [
                {"unit_id": i, "unit_slug": s, "profile_name": n, "source_path": p}
                for i, s, n, p in sorted(
                    {
                        (r["unitId"], r["unitSlug"], r.get("profileName", ""), a["archivePath"])
                        for r, a in pairs
                        if "unitId" in r
                    }
                )
            ],
            "unit_ids": sorted({r["unitId"] for r, _ in pairs if "unitId" in r}),
            "unit_slugs": sorted({r["unitSlug"] for r, _ in pairs if "unitSlug" in r}),
            "profile_names": sorted({r["profileName"] for r, _ in pairs if "profileName" in r}),
            "identity_status": status,
            "action": action,
            "action_status": "review-required",
            "candidates": candidate_rows,
            "evidence": [r["evidence"] for r in rules],
            "viewport_normalization": "separate-metadata-stage",
            "publication_approved": False,
        }
        if decision and decision.get("fallback"):
            row["fallback"] = decision["fallback"]
        if decision and decision["status"] == "confirmed-missing":
            row["action"] = "reconstruct"
        rows.append(row)
    unused = set(range(len(decisions.get("rules", [])))) - used_rules
    if unused:
        raise ValueError(f"identity rules did not match current Army assets: {sorted(unused)}")
    return {
        "format": "infinity-svg-vyo-army-identity-map",
        "version": 1,
        "army_snapshot": artifact,
        "vyo_archive": inventory["summary"]["archive"],
        "summary": {
            "canonical_assets": len(rows),
            "scope": dict(Counter(r["scope"] for r in rows)),
            "identity_status": dict(Counter(r["identity_status"] for r in rows)),
            "candidate_actions": dict(Counter(c["action"] for r in rows for c in r["candidates"])),
        },
        "policy": "Name/alias candidates require visual review. Only explicit profile-scoped absence decisions enter the missing list.",
        "assets": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("army_manifest", type=Path)
    parser.add_argument("publication_manifest", type=Path)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    inputs = [args.inventory, args.army_manifest, args.publication_manifest, args.decisions]
    report = build_identity_map(*(json.loads(p.read_text(encoding="utf-8")) for p in inputs))
    report["input_sha256"] = {
        name: digest(path)
        for name, path in zip(
            ("inventory", "army_manifest", "publication_manifest", "decisions"), inputs
        )
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "vyo-army-identity-map.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    missing = [r for r in report["assets"] if r["identity_status"] == "confirmed-missing"]
    unresolved = [r for r in report["assets"] if r["identity_status"] == "unresolved"]
    reconstruction = [
        r
        for r in report["assets"]
        if r["action"] == "reconstruct"
        and r["identity_status"]
        in {"reviewed-match", "reviewed-design-mismatch", "confirmed-missing"}
        and r.get("fallback", {}).get("action") != "reuse"
    ]
    for name, rows in (
        ("missing-vyo", missing),
        ("unresolved-vyo", unresolved),
        ("reconstruction-queue", reconstruction),
    ):
        (args.output / f"{name}.json").write_text(
            json.dumps(
                {"army_snapshot": report["army_snapshot"], "assets": rows},
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    lines = [
        "# Vyo / Army identity map",
        "",
        f"Army snapshot: `{report['army_snapshot']['name']}`.",
        "",
        "Each row represents one published emblem; all authoritative source/profile references are retained.",
        "Name candidates and unreviewed variants are review-required. Static assets are outside this identity study.",
        "",
        "| Identity status | Assets |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| {key} | {value} |"
        for key, value in sorted(report["summary"]["identity_status"].items())
    )
    lines.extend(
        [
            "",
            "## Confirmed missing Vyo",
            "",
            "Only profile-scoped visual/identity review decisions belong here.",
            "",
        ]
    )
    lines.extend(f"- `{r['army_path']}` — {'; '.join(r['evidence'])}" for r in missing)
    if not missing:
        lines.append(
            "No confirmed absence decisions yet. This does **not** mean complete coverage."
        )
    lines.extend(
        [
            "",
            "## Reviewed source identities",
            "",
            "These decisions identify a source base; publication remains review-required.",
            "",
            "| Army emblem | Action | Vyo base |",
            "| --- | --- | --- |",
        ]
    )
    for row in report["assets"]:
        if row["identity_status"] in {"reviewed-match", "reviewed-design-mismatch"}:
            names = "; ".join(
                c["subject"] + " [" + ",".join(c["tags"]) + "]" for c in row["candidates"]
            )
            action = row["action"]
            if row.get("fallback"):
                action += f" (fallback: {row['fallback']['action']} {row['fallback']['source']})"
            lines.append(f"| `{row['army_path']}` | {action} | {names} |")
    lines.extend(["", "## Reconstruction queue", ""])
    lines.extend(f"- `{r['army_path']}` — {'; '.join(r['evidence'])}" for r in reconstruction)
    lines.extend(
        ["", "## Unresolved identity", "", "These are review work, not a true missing list.", ""]
    )
    lines.extend(f"- `{r['army_path']}`" for r in unresolved)
    (args.output / "vyo-army-identity-map.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return 0
