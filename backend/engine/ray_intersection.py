"""Multi-ray forward intersection: find the 3D point closest to N rays.

Given N rays (origin_i, direction_i), finds the point P that minimises the
sum of squared perpendicular distances to all rays.  This is the standard
least-squares midpoint method used in photogrammetric forward intersection.
"""

from __future__ import annotations

import numpy as np


def intersect_rays(
    origins: list[np.ndarray],
    directions: list[np.ndarray],
) -> tuple[np.ndarray, float]:
    """Find the 3D point closest to all rays via least-squares.

    Parameters
    ----------
    origins : list of ndarray, each shape (3,)
        Ray origin points (camera positions).
    directions : list of ndarray, each shape (3,)
        Unit direction vectors.

    Returns
    -------
    point : ndarray, shape (3,)
        The triangulated 3D point.
    residual : float
        RMS perpendicular distance from the point to each ray (metres).
        Smaller = better convergence.  Sub-centimetre is the goal.

    Raises
    ------
    ValueError
        If fewer than 2 rays are provided.
    """
    n = len(origins)
    if n < 2:
        raise ValueError(f"Need at least 2 rays for intersection, got {n}")

    # Build the normal equation system:
    #   A = sum_i (I - d_i @ d_i^T)
    #   b = sum_i (I - d_i @ d_i^T) @ o_i
    # Solution: P = A^{-1} b  (or lstsq for numerical stability)
    I3 = np.eye(3)
    A = np.zeros((3, 3))
    b = np.zeros(3)

    for o, d in zip(origins, directions):
        d = d / np.linalg.norm(d)  # ensure unit
        proj = I3 - np.outer(d, d)
        A += proj
        b += proj @ o

    point, residuals, rank, sv = np.linalg.lstsq(A, b, rcond=None)

    # Compute RMS perpendicular distance
    sum_sq = 0.0
    for o, d in zip(origins, directions):
        d = d / np.linalg.norm(d)
        v = point - o
        perp = v - np.dot(v, d) * d
        sum_sq += np.dot(perp, perp)
    rms = np.sqrt(sum_sq / n)

    return point, rms


def intersect_rays_robust(
    origins: list[np.ndarray],
    directions: list[np.ndarray],
    max_residual: float = 0.5,
) -> tuple[np.ndarray, float]:
    """Robust intersection with single-ray outlier rejection.

    Performs an initial intersection, then removes the ray with the
    largest residual if it exceeds *max_residual* metres.  Repeats
    until all residuals are acceptable or only 2 rays remain.
    """
    origins = list(origins)
    directions = list(directions)

    while len(origins) > 2:
        point, rms = intersect_rays(origins, directions)

        # Per-ray residuals
        dists = []
        for o, d in zip(origins, directions):
            d = d / np.linalg.norm(d)
            v = point - o
            perp = v - np.dot(v, d) * d
            dists.append(np.linalg.norm(perp))

        worst = int(np.argmax(dists))
        if dists[worst] <= max_residual:
            return point, rms

        origins.pop(worst)
        directions.pop(worst)

    return intersect_rays(origins, directions)
