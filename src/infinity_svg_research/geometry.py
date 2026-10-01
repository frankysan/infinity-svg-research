"""Small geometry helpers for evidence-driven SVG reconstruction research.

The helpers in this module measure hypotheses. They intentionally do not rewrite SVG geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot, sqrt
from typing import Iterable

import numpy as np


@dataclass(frozen=True, slots=True)
class Circle:
    """A circle in SVG user-space coordinates."""

    cx: float
    cy: float
    radius: float


@dataclass(frozen=True, slots=True)
class CircleFit:
    """Least-squares circle fit and radial-error summary."""

    circle: Circle
    rmse: float
    max_abs_residual: float


@dataclass(frozen=True, slots=True)
class ConcentricBandFit:
    """Joint fit for two concentric boundaries with an unconstrained width."""

    outer: Circle
    inner: Circle
    width: float
    rmse: float
    max_abs_residual: float


def _point_array(points: Iterable[tuple[float, float]] | np.ndarray) -> np.ndarray:
    result = np.asarray(list(points) if not isinstance(points, np.ndarray) else points, dtype=float)
    if result.ndim != 2 or result.shape[1] != 2:
        raise ValueError("points must be an N x 2 coordinate array")
    if not np.all(np.isfinite(result)):
        raise ValueError("points must contain only finite coordinates")
    return result


def radial_residuals(
    circle: Circle, points: Iterable[tuple[float, float]] | np.ndarray
) -> np.ndarray:
    """Return signed point-to-circle radial residuals."""

    coordinates = _point_array(points)
    return np.hypot(coordinates[:, 0] - circle.cx, coordinates[:, 1] - circle.cy) - circle.radius


def fit_circle(points: Iterable[tuple[float, float]] | np.ndarray) -> CircleFit:
    """Fit a circle with an algebraic least-squares seed and report radial error.

    This is intended for advisory reconstruction work, where the residual is evidence for or
    against a circular construction. It is not an automatic rewrite rule.
    """

    coordinates = _point_array(points)
    if len(coordinates) < 3:
        raise ValueError("at least three points are required to fit a circle")

    x = coordinates[:, 0]
    y = coordinates[:, 1]
    design = np.column_stack((2.0 * x, 2.0 * y, np.ones(len(coordinates))))
    target = x * x + y * y
    solution, _residuals, rank, _singular = np.linalg.lstsq(design, target, rcond=None)
    if rank < 3:
        raise ValueError("circle fit is degenerate; points are collinear or coincident")

    cx, cy, constant = (float(value) for value in solution)
    radius_squared = cx * cx + cy * cy + constant
    if radius_squared <= 0.0:
        raise ValueError("circle fit produced a non-positive radius")

    circle = Circle(cx=cx, cy=cy, radius=sqrt(radius_squared))
    residual = radial_residuals(circle, coordinates)
    return CircleFit(
        circle=circle,
        rmse=float(np.sqrt(np.mean(residual * residual))),
        max_abs_residual=float(np.max(np.abs(residual))),
    )



def fit_concentric_band(
    outer_points: Iterable[tuple[float, float]] | np.ndarray,
    inner_points: Iterable[tuple[float, float]] | np.ndarray,
    *,
    max_iterations: int = 50,
    tolerance: float = 1e-12,
) -> ConcentricBandFit:
    """Fit two point sets to concentric circles without constraining their width."""

    outer = _point_array(outer_points)
    inner = _point_array(inner_points)
    if len(outer) < 3 or len(inner) < 3:
        raise ValueError("at least three points are required for each band boundary")

    outer_fit = fit_circle(outer).circle
    inner_fit = fit_circle(inner).circle
    cx = (outer_fit.cx + inner_fit.cx) / 2.0
    cy = (outer_fit.cy + inner_fit.cy) / 2.0
    outer_radius = outer_fit.radius
    inner_radius = inner_fit.radius

    for _ in range(max_iterations):
        outer_dx = cx - outer[:, 0]
        outer_dy = cy - outer[:, 1]
        inner_dx = cx - inner[:, 0]
        inner_dy = cy - inner[:, 1]
        outer_distances = np.hypot(outer_dx, outer_dy)
        inner_distances = np.hypot(inner_dx, inner_dy)
        if np.any(outer_distances <= 1e-15) or np.any(inner_distances <= 1e-15):
            raise ValueError("band fit is degenerate at the current center estimate")

        residual = np.concatenate(
            (outer_distances - outer_radius, inner_distances - inner_radius)
        )
        outer_jacobian = np.column_stack(
            (
                outer_dx / outer_distances,
                outer_dy / outer_distances,
                -np.ones(len(outer)),
                np.zeros(len(outer)),
            )
        )
        inner_jacobian = np.column_stack(
            (
                inner_dx / inner_distances,
                inner_dy / inner_distances,
                np.zeros(len(inner)),
                -np.ones(len(inner)),
            )
        )
        jacobian = np.vstack((outer_jacobian, inner_jacobian))
        delta, _residuals, rank, _singular = np.linalg.lstsq(
            jacobian, -residual, rcond=None
        )
        if rank < 4:
            raise ValueError("band fit is degenerate")

        cx += float(delta[0])
        cy += float(delta[1])
        outer_radius += float(delta[2])
        inner_radius += float(delta[3])
        if float(np.linalg.norm(delta)) <= tolerance:
            break

    if inner_radius <= 0.0 or outer_radius <= inner_radius:
        raise ValueError("fitted band requires positive radii with outer > inner")

    fitted_outer = Circle(cx=cx, cy=cy, radius=outer_radius)
    fitted_inner = Circle(cx=cx, cy=cy, radius=inner_radius)
    residual = np.concatenate(
        (radial_residuals(fitted_outer, outer), radial_residuals(fitted_inner, inner))
    )
    return ConcentricBandFit(
        outer=fitted_outer,
        inner=fitted_inner,
        width=outer_radius - inner_radius,
        rmse=float(np.sqrt(np.mean(residual * residual))),
        max_abs_residual=float(np.max(np.abs(residual))),
    )

def fit_fixed_width_band(
    outer_points: Iterable[tuple[float, float]] | np.ndarray,
    inner_points: Iterable[tuple[float, float]] | np.ndarray,
    *,
    width: float,
    max_iterations: int = 50,
    tolerance: float = 1e-12,
) -> CircleFit:
    """Fit two concentric point sets constrained to a known radial band width.

    The returned circle is the outer boundary. The inner boundary is therefore
    ``Circle(cx, cy, radius - width)``. A small Gauss-Newton solve keeps this helper dependency-free
    beyond NumPy and makes the common-center/constant-width hypothesis directly measurable.
    """

    if not np.isfinite(width) or width <= 0.0:
        raise ValueError("width must be a positive finite number")

    outer = _point_array(outer_points)
    inner = _point_array(inner_points)
    if len(outer) < 3 or len(inner) < 3:
        raise ValueError("at least three points are required for each band boundary")

    outer_fit = fit_circle(outer).circle
    inner_fit = fit_circle(inner).circle
    cx = (outer_fit.cx + inner_fit.cx) / 2.0
    cy = (outer_fit.cy + inner_fit.cy) / 2.0
    radius = (outer_fit.radius + inner_fit.radius + width) / 2.0

    all_points = np.vstack((outer, inner))
    target_offsets = np.concatenate((np.zeros(len(outer)), np.full(len(inner), width)))

    for _ in range(max_iterations):
        dx = cx - all_points[:, 0]
        dy = cy - all_points[:, 1]
        distances = np.hypot(dx, dy)
        if np.any(distances <= 1e-15):
            raise ValueError("band fit is degenerate at the current center estimate")

        residual = distances - radius + target_offsets
        jacobian = np.column_stack((dx / distances, dy / distances, -np.ones(len(all_points))))
        delta, _residuals, rank, _singular = np.linalg.lstsq(jacobian, -residual, rcond=None)
        if rank < 3:
            raise ValueError("band fit is degenerate")

        cx += float(delta[0])
        cy += float(delta[1])
        radius += float(delta[2])
        if float(np.linalg.norm(delta)) <= tolerance:
            break

    if radius <= width:
        raise ValueError("fitted outer radius must be larger than the band width")

    fitted_outer = Circle(cx=cx, cy=cy, radius=radius)
    fitted_inner = Circle(cx=cx, cy=cy, radius=radius - width)
    residual = np.concatenate(
        (radial_residuals(fitted_outer, outer), radial_residuals(fitted_inner, inner))
    )
    return CircleFit(
        circle=fitted_outer,
        rmse=float(np.sqrt(np.mean(residual * residual))),
        max_abs_residual=float(np.max(np.abs(residual))),
    )


def circle_intersections(
    first: Circle, second: Circle, *, tolerance: float = 1e-9
) -> tuple[tuple[float, float], ...]:
    """Return zero, one, or two intersections between two non-coincident circles."""

    if first.radius <= 0.0 or second.radius <= 0.0:
        raise ValueError("circle radii must be positive")

    dx = second.cx - first.cx
    dy = second.cy - first.cy
    distance = hypot(dx, dy)
    if distance <= tolerance and abs(first.radius - second.radius) <= tolerance:
        raise ValueError("coincident circles have infinitely many intersections")
    if distance <= tolerance:
        return ()
    if distance > first.radius + second.radius + tolerance:
        return ()
    if distance < abs(first.radius - second.radius) - tolerance:
        return ()

    along = (first.radius**2 - second.radius**2 + distance**2) / (2.0 * distance)
    height_squared = first.radius**2 - along**2
    if height_squared < -tolerance:
        return ()
    height = sqrt(max(0.0, height_squared))

    midpoint_x = first.cx + along * dx / distance
    midpoint_y = first.cy + along * dy / distance
    offset_x = -dy * height / distance
    offset_y = dx * height / distance

    first_point = (midpoint_x + offset_x, midpoint_y + offset_y)
    if height <= tolerance:
        return (first_point,)
    second_point = (midpoint_x - offset_x, midpoint_y - offset_y)
    return (first_point, second_point)


def project_point_to_circle(circle: Circle, point: tuple[float, float]) -> tuple[float, float]:
    """Project a point radially onto ``circle`` while preserving its center angle."""

    dx = float(point[0]) - circle.cx
    dy = float(point[1]) - circle.cy
    distance = hypot(dx, dy)
    if distance <= 1e-15:
        raise ValueError("cannot radially project the circle center")
    scale = circle.radius / distance
    return (circle.cx + dx * scale, circle.cy + dy * scale)
