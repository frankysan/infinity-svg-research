from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from infinity_svg_research import viewport_normalize as viewport
from infinity_svg_research import viewport_validate
from infinity_svg_research import vyo_identity as identity


class ViewportTests(unittest.TestCase):
    def document(self, width="8.5in", height="11in", box="0 0 8500 11000", content=""):
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="{box}">{content}</svg>'
        ).encode()

    def test_old_placement_is_converted_from_css_pixels_to_user_units(self):
        root = viewport.parse_svg(self.document())
        expected = [-3937, 7063, 7874, 7874]
        actual = viewport.pixels_to_user_bounds(root, [-377.952, 678.048, 755.904, 755.904])
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, places=7)

    def test_new_n4_placement_uses_mm_scale(self):
        root = viewport.parse_svg(self.document("215.9mm", "279.4mm", "0 0 21590 27940"))
        expected = [0, 7940, 20000, 20000]
        pixels = [v * 96 / 2540 for v in expected]
        for a, b in zip(viewport.pixels_to_user_bounds(root, pixels), expected):
            self.assertAlmostEqual(a, b, places=7)

    def test_nonzero_viewbox_and_alignment_offset(self):
        data = self.document("200", "100", "10 20 100 100")
        data = viewport.replace_root_attributes(data, {"preserveAspectRatio": "xMaxYMin meet"})
        self.assertEqual(
            viewport.pixels_to_user_bounds(viewport.parse_svg(data), [100, 0, 100, 100]),
            [10, 20, 100, 100],
        )

    def test_root_only_change_preserves_styles_geometry_and_doctype_bytes(self):
        prefix = b'<?xml version="1.0"?><!DOCTYPE svg PUBLIC "x" "https://invalid.test/x.dtd">\n'
        children = '<defs><style><![CDATA[.x {fill:red}]]></style></defs><g transform="translate(4 9)"><circle class="x" cx="0" cy="11000" r="3937"/></g>'
        data = prefix + self.document(content=children)
        candidate, metadata = viewport.normalize(data, [-377.952, 678.048, 755.904, 755.904])
        self.assertTrue(candidate.startswith(prefix))
        self.assertEqual(
            candidate[candidate.index(b"><defs>") + 1 :], data[data.index(b"><defs>") + 1 :]
        )
        root = viewport.parse_svg(candidate)
        self.assertIsNone(root.get("width"))
        self.assertIsNone(root.get("height"))
        self.assertEqual(root.get("preserveAspectRatio"), "xMidYMid meet")
        self.assertLess(float(metadata["new_viewport"]["viewBox"].split()[0]), -3937)

    def test_example_svg_inside_comment_is_not_modified(self):
        comment = b'<!-- Example: <svg width="42"> -->'
        data = comment + self.document()
        candidate, _ = viewport.normalize(data, [0, 0, 100, 100])
        self.assertTrue(candidate.startswith(comment))
        self.assertIsNone(viewport.parse_svg(candidate).get("width"))

    def test_rectangular_artwork_keeps_intrinsic_ratio_without_fixed_dimensions(self):
        candidate, metadata = viewport.normalize(self.document(), [0, 0, 200, 100], padding=0)
        root = viewport.parse_svg(candidate)
        _, _, w, h = map(float, root.get("viewBox").split())
        self.assertIsNone(root.get("width"))
        self.assertIsNone(root.get("height"))
        self.assertAlmostEqual(metadata["intrinsic_aspect_ratio"], w / h)
        self.assertGreater(w / h, 1.99)
        self.assertEqual(root.get("preserveAspectRatio"), "xMidYMid meet")

    def test_attribute_removal_preserves_child_sizes_and_other_root_attributes(self):
        data = self.document(content='<rect width="40" height="20"/>')
        data = viewport.replace_root_attributes(data, {"aria-label": "badge"})
        candidate = viewport.replace_root_attributes(data, {"width": None, "height": None})
        root = viewport.parse_svg(candidate)
        self.assertIsNone(root.get("width"))
        self.assertIsNone(root.get("height"))
        self.assertEqual(root.get("aria-label"), "badge")
        self.assertEqual(root[0].get("width"), "40")
        self.assertEqual(root[0].get("height"), "20")

    def test_query_root_id_and_css_viewport_dependencies_are_blocked(self):
        data = viewport.replace_root_attributes(
            self.document(content="<style>#badge {fill:red}</style>"), {"id": "badge"}
        )
        self.assertIn("referenced-root-id", viewport.blockers(viewport.parse_svg(data)))
        data = viewport.replace_root_attributes(self.document(), {"style": "width:200px"})
        self.assertIn("css-root-size", viewport.blockers(viewport.parse_svg(data)))

    def test_text_external_references_and_percent_geometry_are_blocked(self):
        for content, reason in [
            ("<text>A</text>", "font-dependent-text"),
            ('<image href="image.png"/>', "external-reference"),
            ('<rect width="100%"/>', "viewport-relative-percentage"),
        ]:
            root = viewport.parse_svg(self.document(content=content))
            self.assertIn(reason, viewport.blockers(root))
            with self.assertRaises(ValueError):
                viewport.normalize(self.document(content=content), [0, 0, 100, 100])

    def test_nonfinite_or_empty_bounds_and_invalid_padding_are_rejected(self):
        for bounds in [[0, 0, float("nan"), 1], [0, 0, 0, 100], [0, 0, 10, -1]]:
            with self.assertRaises(ValueError):
                viewport.normalize(self.document(), bounds)
        with self.assertRaises(ValueError):
            viewport.normalize(self.document(), [0, 0, 100, 100], padding=-0.1)

    def test_validation_rejects_changed_source_before_rendering(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            source = run / "source"
            source.mkdir()
            (source / "a.svg").write_bytes(self.document())
            report = {
                "format": "infinity-svg-viewport-normalization",
                "source_root": str(source),
                "files": [
                    {
                        "path": "a.svg",
                        "status": "normalized-review-required",
                        "source_sha256": "wrong",
                        "candidate_sha256": "wrong",
                    }
                ],
            }
            path = run / "report.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "input hash mismatch"):
                viewport_validate.validate_run(path, inkscape="must-not-run")


class IdentityTests(unittest.TestCase):
    def fixture(self):
        inventory = {
            "summary": {"archive": "test.zip"},
            "files": [
                {
                    "path": "P/Indigo.svg",
                    "folder": "PanOceania",
                    "subject": "Indigo Spec-Ops v2",
                    "sha256": "vyo-hash",
                    "tags": ["N3"],
                    "images": 0,
                    "texts": 0,
                    "features": [],
                }
            ],
        }
        paths = [
            "units/indigo-team-ops-1-1.svg",
            "units/indigo-brother-konstantinos-1-1.svg",
            "units/indigo-team-ops-2-1.svg",
        ]
        assets = [
            {
                "archivePath": p,
                "url": "https://example.test/" + p,
                "sha256": "shared" if i < 2 else "different",
            }
            for i, p in enumerate(paths)
        ]
        refs = [
            {
                "kind": "unit-profile",
                "authoritative": True,
                "unitId": i,
                "unitSlug": identity.subject_from_path(p),
                "profileName": str(i),
                "assetUrl": assets[i]["url"],
            }
            for i, p in enumerate(paths)
        ]
        # Audit-only references must not introduce current emblems.
        refs.append(
            dict(refs[0], authoritative=False, unitSlug="obsolete-audit-name", kind="resume-audit")
        )
        army = {
            "snapshot": {"armyArtifact": {"name": "test.zip", "sha256": "snapshot"}},
            "assets": assets,
            "references": refs,
        }
        publication = {
            "sourceSnapshot": {"armyArtifact": {"sha256": "snapshot"}},
            "canonicalArchivePathToPublishedPath": {paths[0]: "one.svg", paths[2]: "two.svg"},
            "sourceArchivePathToPublishedPath": {
                paths[0]: "one.svg",
                paths[1]: "one.svg",
                paths[2]: "two.svg",
            },
        }
        return inventory, army, publication, {"rules": []}

    def test_unmatched_name_is_unresolved_never_confirmed_missing(self):
        report = identity.build_identity_map(*self.fixture())
        self.assertEqual(report["summary"]["identity_status"], {"unresolved": 2})

    def test_shared_emblem_preserves_names_and_different_profile_stays_separate(self):
        inputs = list(self.fixture())
        inputs[3] = {
            "rules": [
                {
                    "army_subjects": ["indigo-team-ops"],
                    "status": "alias-candidate",
                    "vyo_paths": ["P/Indigo.svg"],
                    "evidence": "test lead",
                }
            ]
        }
        rows = identity.build_identity_map(*inputs)["assets"]
        first = next(r for r in rows if r["army_path"].endswith("-1-1.svg"))
        self.assertEqual(first["subjects"], ["indigo-brother-konstantinos", "indigo-team-ops"])
        self.assertEqual(len(rows), 2)
        self.assertNotIn("obsolete-audit-name", first["unit_slugs"])
        self.assertEqual(first["identity_status"], "name-candidate")
        self.assertFalse(first["publication_approved"])

    def test_reviewed_decision_is_scoped_to_one_profile_and_can_record_redesign(self):
        inputs = list(self.fixture())
        inputs[3] = {
            "rules": [
                {
                    "army_paths": ["units/indigo-team-ops-1-1.svg"],
                    "status": "reviewed-match",
                    "vyo_paths": ["P/Indigo.svg"],
                    "action": "reconstruct",
                    "reasons": ["different-current-design"],
                    "evidence": "visual review",
                }
            ]
        }
        rows = identity.build_identity_map(*inputs)["assets"]
        self.assertEqual([r["identity_status"] for r in rows], ["reviewed-match", "unresolved"])
        self.assertEqual(rows[0]["action"], "reconstruct")
        self.assertIn("different-current-design", rows[0]["candidates"][0]["reasons"])

    def test_absence_requires_profile_scope_and_cannot_reference_vyo(self):
        for rule in [
            {
                "army_subjects": ["indigo-team-ops"],
                "status": "confirmed-missing",
                "evidence": "review",
            },
            {
                "army_paths": ["units/indigo-team-ops-1-1.svg"],
                "status": "confirmed-missing",
                "evidence": "review",
                "vyo_paths": ["P/Indigo.svg"],
            },
        ]:
            inputs = list(self.fixture())
            inputs[3] = {"rules": [rule]}
            with self.assertRaises(ValueError):
                identity.build_identity_map(*inputs)

    def test_snapshot_mismatch_and_conflicting_reviews_fail(self):
        inputs = list(self.fixture())
        publication = copy.deepcopy(inputs[2])
        publication["sourceSnapshot"]["armyArtifact"]["sha256"] = "wrong"
        with self.assertRaises(ValueError):
            identity.build_identity_map(inputs[0], inputs[1], publication, inputs[3])
        rule = {
            "army_paths": ["units/indigo-team-ops-1-1.svg"],
            "status": "confirmed-missing",
            "evidence": "review",
        }
        inputs[3] = {"rules": [rule, rule]}
        with self.assertRaises(ValueError):
            identity.build_identity_map(*inputs)

    def test_source_exceptions_affect_actions_not_identity(self):
        self.assertEqual(identity.classify({"images": 1})[0], "reconstruct")
        self.assertEqual(identity.classify({"features": ["text", "gradient"]})[0], "minor-cleanup")
        self.assertEqual(identity.classify({"features": ["transform"]})[0], "reuse")

    def test_recorded_source_hash_invalidates_stale_review(self):
        inputs = list(self.fixture())
        inputs[3] = {
            "rules": [
                {
                    "army_paths": ["units/indigo-team-ops-1-1.svg"],
                    "status": "reviewed-match",
                    "vyo_paths": ["P/Indigo.svg"],
                    "evidence": "review",
                    "review_source_assets": [
                        {"path": "units/indigo-team-ops-1-1.svg", "sha256": "old-hash"}
                    ],
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "reviewed Army source changed"):
            identity.build_identity_map(*inputs)

    def test_design_mismatch_retains_current_army_fallback(self):
        inputs = list(self.fixture())
        inputs[3] = {
            "rules": [
                {
                    "army_paths": ["units/indigo-team-ops-1-1.svg"],
                    "status": "reviewed-design-mismatch",
                    "vyo_paths": ["P/Indigo.svg"],
                    "action": "reconstruct",
                    "evidence": "old/current designs differ",
                    "fallback": {"source": "current-army", "action": "reuse"},
                }
            ]
        }
        row = identity.build_identity_map(*inputs)["assets"][0]
        self.assertEqual(row["identity_status"], "reviewed-design-mismatch")
        self.assertEqual(row["fallback"]["action"], "reuse")


if __name__ == "__main__":
    unittest.main()
