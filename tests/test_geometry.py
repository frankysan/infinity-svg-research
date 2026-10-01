from __future__ import annotations

import math
import unittest

import numpy as np

from infinity_svg_research.geometry import Circle
from infinity_svg_research.geometry import circle_intersections
from infinity_svg_research.geometry import fit_circle
from infinity_svg_research.geometry import fit_concentric_band
from infinity_svg_research.geometry import fit_fixed_width_band
from infinity_svg_research.geometry import project_point_to_circle
from infinity_svg_research.geometry import radial_residuals


class GeometryTests(unittest.TestCase):
    def test_fit_circle_recovers_sampled_arc(self) -> None:
        angles = np.linspace(math.radians(15), math.radians(125), 40)
        points = np.column_stack((12.5 + 8.75 * np.cos(angles), -3.0 + 8.75 * np.sin(angles)))

        result = fit_circle(points)

        self.assertAlmostEqual(result.circle.cx, 12.5, places=10)
        self.assertAlmostEqual(result.circle.cy, -3.0, places=10)
        self.assertAlmostEqual(result.circle.radius, 8.75, places=10)
        self.assertLess(result.rmse, 1e-10)

    def test_concentric_band_recovers_width_without_constraint(self) -> None:
        center = (-4.0, 9.5)
        outer_radius = 17.25
        inner_radius = 11.5
        angles = np.linspace(math.radians(205), math.radians(335), 70)
        outer = np.column_stack(
            (center[0] + outer_radius * np.cos(angles), center[1] + outer_radius * np.sin(angles))
        )
        inner = np.column_stack(
            (center[0] + inner_radius * np.cos(angles), center[1] + inner_radius * np.sin(angles))
        )

        result = fit_concentric_band(outer, inner)

        self.assertAlmostEqual(result.outer.cx, center[0], places=9)
        self.assertAlmostEqual(result.outer.cy, center[1], places=9)
        self.assertAlmostEqual(result.outer.radius, outer_radius, places=9)
        self.assertAlmostEqual(result.inner.radius, inner_radius, places=9)
        self.assertAlmostEqual(result.width, outer_radius - inner_radius, places=9)
        self.assertLess(result.rmse, 1e-9)

    def test_fixed_width_band_recovers_shared_center_and_width(self) -> None:
        center = (25.6, 107.4)
        width = 5.67
        outer_radius = 82.2
        angles = np.linspace(math.radians(205), math.radians(320), 50)
        outer = np.column_stack(
            (center[0] + outer_radius * np.cos(angles), center[1] + outer_radius * np.sin(angles))
        )
        inner_radius = outer_radius - width
        inner = np.column_stack(
            (center[0] + inner_radius * np.cos(angles), center[1] + inner_radius * np.sin(angles))
        )

        result = fit_fixed_width_band(outer, inner, width=width)

        self.assertAlmostEqual(result.circle.cx, center[0], places=9)
        self.assertAlmostEqual(result.circle.cy, center[1], places=9)
        self.assertAlmostEqual(result.circle.radius, outer_radius, places=9)
        self.assertLess(result.rmse, 1e-9)

    def test_circle_intersections_recover_expected_points(self) -> None:
        intersections = circle_intersections(Circle(0.0, 0.0, 5.0), Circle(6.0, 0.0, 5.0))

        self.assertEqual(len(intersections), 2)
        self.assertAlmostEqual(intersections[0][0], 3.0)
        self.assertAlmostEqual(abs(intersections[0][1]), 4.0)
        self.assertAlmostEqual(intersections[1][0], 3.0)
        self.assertAlmostEqual(abs(intersections[1][1]), 4.0)

    def test_project_point_to_circle_preserves_radial_direction(self) -> None:
        projected = project_point_to_circle(Circle(2.0, 3.0, 10.0), (5.0, 7.0))

        self.assertAlmostEqual(projected[0], 8.0)
        self.assertAlmostEqual(projected[1], 11.0)

    def test_radial_residuals_preserve_signed_error(self) -> None:
        residuals = radial_residuals(Circle(0.0, 0.0, 2.0), [(2.5, 0.0), (1.5, 0.0)])

        np.testing.assert_allclose(residuals, [0.5, -0.5])


if __name__ == "__main__":
    unittest.main()
