from __future__ import annotations

import unittest

from infinity_svg_research import scan


class ClassificationRegressionTests(unittest.TestCase):
    def test_large_path_payload_is_advisory_only(self) -> None:
        report = scan.SvgReport(
            path="units/denma.svg",
            size_bytes=134_049,
            path_data_bytes=130_107,
            largest_path_data_bytes=31_519,
        )

        scan.classify(report)

        self.assertIsNone(report.classification)
        self.assertIn("large-path-payload", report.advisories)
        self.assertTrue(report.flagged)

    def test_wolfgang_scale_payload_is_classified(self) -> None:
        report = scan.SvgReport(
            path="units/wolfgang.svg",
            size_bytes=1_175_564,
            path_data_bytes=1_173_356,
            largest_path_data_bytes=76_882,
        )

        scan.classify(report)

        self.assertEqual("oversized-path-data", report.classification)
        self.assertEqual("medium", report.severity)

    def test_raster_heavy_asset_is_classified(self) -> None:
        report = scan.SvgReport(
            path="factions/druze.svg",
            size_bytes=189_397,
            embedded_images=6,
            embedded_image_bytes_estimate=134_014,
        )

        scan.classify(report)

        self.assertEqual("embedded-raster-heavy", report.classification)
        self.assertEqual("medium", report.severity)


class DuplicateGroupTests(unittest.TestCase):
    def test_duplicate_groups_are_deterministic_and_annotate_members(self) -> None:
        reports = [
            scan.SvgReport(path="b.svg", size_bytes=10, sha256="abc"),
            scan.SvgReport(path="a.svg", size_bytes=10, sha256="abc"),
            scan.SvgReport(path="c.svg", size_bytes=5, sha256="def"),
        ]

        groups = scan.build_duplicate_groups(reports)

        self.assertEqual(1, len(groups))
        self.assertEqual("abc", groups[0]["sha256"])
        self.assertEqual(["a.svg", "b.svg"], groups[0]["paths"])
        self.assertEqual(2, reports[0].exact_duplicate_group_size)
        self.assertEqual(2, reports[1].exact_duplicate_group_size)
        self.assertEqual(1, reports[2].exact_duplicate_group_size)


if __name__ == "__main__":
    unittest.main()
