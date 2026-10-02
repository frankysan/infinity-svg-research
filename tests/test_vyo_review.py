from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from infinity_svg_research import vyo_review


class DecisionTests(unittest.TestCase):
    def report(self):
        return {
            "summary": {},
            "assets": [
                {
                    "army_path": "units/example-1-1.svg",
                    "scope": "unit",
                    "subjects": ["example"],
                    "unit_slugs": ["example"],
                    "profile_names": ["Standard"],
                    "identity_status": "name-candidate",
                    "action": "reuse",
                    "evidence": [],
                    "source_assets": [
                        {"path": "units/example-1-1.svg", "sha256": "army", "url": "x"}
                    ],
                    "candidates": [
                        {
                            "path": "Faction/Example [Vyo].svg",
                            "sha256": "vyo",
                            "subject": "Example",
                            "tags": ["N3"],
                            "matched_by": ["exact-normalized-name"],
                            "action": "reuse",
                            "reasons": [],
                        }
                    ],
                }
            ],
        }

    def test_reuse_review_records_profile_and_hashes(self):
        updated = vyo_review.update_decisions(
            self.report(),
            {"rules": []},
            {
                "army_path": "units/example-1-1.svg",
                "decision": "reuse",
                "vyo_paths": ["Faction/Example [Vyo].svg"],
                "reasons": [],
                "evidence": "Visual comparison: same device and composition.",
            },
        )
        rule = updated["rules"][0]
        self.assertEqual(rule["status"], "reviewed-match")
        self.assertEqual(rule["action"], "reuse")
        self.assertEqual(
            rule["review_source_assets"],
            [{"path": "units/example-1-1.svg", "sha256": "army"}],
        )
        self.assertEqual(
            rule["review_vyo_assets"],
            [{"path": "Faction/Example [Vyo].svg", "sha256": "vyo"}],
        )

    def test_cleanup_requires_reason_and_evidence(self):
        base = {
            "army_path": "units/example-1-1.svg",
            "decision": "cleanup",
            "vyo_paths": ["Faction/Example [Vyo].svg"],
            "reasons": [],
            "evidence": "review",
        }
        with self.assertRaisesRegex(ValueError, "reason"):
            vyo_review.update_decisions(self.report(), {"rules": []}, base)
        base["reasons"] = ["align-palette-to-first-party"]
        base["evidence"] = ""
        with self.assertRaisesRegex(ValueError, "evidence"):
            vyo_review.update_decisions(self.report(), {"rules": []}, base)

    def test_confirmed_missing_is_guarded(self):
        payload = {
            "army_path": "units/example-1-1.svg",
            "decision": "missing",
            "vyo_paths": [],
            "reasons": [],
            "evidence": "Reviewed the relevant archive drawings.",
            "confirm_missing": False,
        }
        with self.assertRaisesRegex(ValueError, "explicit confirmation"):
            vyo_review.update_decisions(self.report(), {"rules": []}, payload)
        payload["confirm_missing"] = True
        rule = vyo_review.update_decisions(self.report(), {"rules": []}, payload)["rules"][0]
        self.assertEqual(rule["status"], "confirmed-missing")
        self.assertNotIn("vyo_paths", rule)

    def test_unresolved_removes_exact_review_but_not_alias_rules(self):
        decisions = {
            "rules": [
                {
                    "army_subjects": ["example"],
                    "status": "alias-candidate",
                    "evidence": "name lead",
                },
                {
                    "army_paths": ["units/example-1-1.svg"],
                    "status": "reviewed-match",
                    "vyo_paths": ["Faction/Example [Vyo].svg"],
                    "action": "reuse",
                    "evidence": "old review",
                },
            ]
        }
        updated = vyo_review.update_decisions(
            self.report(),
            decisions,
            {"army_path": "units/example-1-1.svg", "decision": "unresolved"},
        )
        self.assertEqual(len(updated["rules"]), 1)
        self.assertEqual(updated["rules"][0]["status"], "alias-candidate")

    def test_subject_scoped_review_is_not_rewritten(self):
        decisions = {
            "rules": [
                {
                    "army_subjects": ["example"],
                    "status": "reviewed-match",
                    "vyo_paths": ["Faction/Example [Vyo].svg"],
                    "evidence": "legacy broad review",
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "subject-scoped"):
            vyo_review.update_decisions(
                self.report(),
                decisions,
                {"army_path": "units/example-1-1.svg", "decision": "unresolved"},
            )

    def test_public_state_exposes_only_exact_editable_review(self):
        decisions = {
            "rules": [
                {
                    "army_paths": ["units/example-1-1.svg"],
                    "status": "reviewed-match",
                    "action": "reuse",
                    "vyo_paths": ["Faction/Example [Vyo].svg"],
                    "evidence": "review",
                }
            ]
        }
        state = vyo_review.public_state(self.report(), decisions)
        self.assertEqual(state["assets"][0]["review"]["action"], "reuse")
        self.assertEqual(state["assets"][0]["army_source"]["sha256"], "army")


class AssetTests(unittest.TestCase):
    def test_safe_svg_path_rejects_escape_and_non_svg(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ok.svg").write_text("<svg/>", encoding="utf-8")
            self.assertEqual(vyo_review.safe_svg_path(root, "ok.svg"), (root / "ok.svg").resolve())
            with self.assertRaises(ValueError):
                vyo_review.safe_svg_path(root, "../escape.svg")
            with self.assertRaises(ValueError):
                vyo_review.safe_svg_path(root, "notes.txt")

    def test_square_framing_preserves_transparency_and_centers_art(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            target = root / "target.png"
            image = Image.new("RGBA", (80, 40), (0, 0, 0, 0))
            for x in range(10, 70):
                for y in range(5, 35):
                    image.putpixel((x, y), (255, 0, 0, 255))
            image.save(source)
            vyo_review._fit_square(source, target, 200)
            with Image.open(target) as framed:
                self.assertEqual(framed.size, (200, 200))
                bbox = framed.getbbox()
                self.assertIsNotNone(bbox)
                self.assertEqual((bbox[0] + bbox[2]) // 2, 100)
                self.assertEqual((bbox[1] + bbox[3]) // 2, 100)

    def test_atomic_json_write_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decision.json"
            vyo_review.atomic_write_json(path, {"rules": [{"evidence": "åäö"}]})
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["rules"][0]["evidence"], "åäö")


if __name__ == "__main__":
    unittest.main()
