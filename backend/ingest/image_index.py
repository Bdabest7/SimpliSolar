"""Spatial image index: find which images cover a given target XY.

Selection strategy
------------------
1. Rank all cameras by XY distance to the target coordinate.
2. Pick the ``n_closest`` nearest cameras (default 5) — these give the
   best overhead views and strongest multi-view geometry.
3. Fill the remaining slots with sequential neighbours (by filename)
   around the closest camera, up to ``max_images`` total.  Sequential
   frames capture the target from slightly different angles as the
   drone approached and departed.
4. Return all selected images sorted by filename.
"""

from __future__ import annotations

import logging

from backend.models.camera import CameraModel
from backend.models.project import Target

log = logging.getLogger(__name__)


def find_covering_images(
    target: Target,
    cameras: dict[str, CameraModel],
    ground_z: float = 0.0,
    max_images: int = 15,
    n_closest: int = 5,
    margin_px: int = 100,
) -> list[str]:
    """Return images covering a target: closest by distance + sequential neighbours.

    Parameters
    ----------
    target : Target
        Target with approximate X, Y world coordinates.
    cameras : dict
        All camera models keyed by image name.
    max_images : int
        Maximum number of images to return (default 15).
    n_closest : int
        Number of spatially closest cameras to always include (default 5).
    ground_z, margin_px : unused — kept for API compatibility.

    Returns
    -------
    List of image names sorted by filename.
    """
    if not cameras:
        log.warning("No cameras loaded — cannot find covering images for target '%s'", target.id)
        return []

    log.info(
        "Finding covering images for target '%s' at (%.3f, %.3f) across %d cameras",
        target.id, target.x, target.y, len(cameras),
    )

    # ── 1. Rank all cameras by XY distance to target ──────────────────────────
    def sq_dist(name: str) -> float:
        c = cameras[name]
        dx = c.extrinsics.x - target.x
        dy = c.extrinsics.y - target.y
        return dx * dx + dy * dy

    ranked = sorted(cameras.keys(), key=sq_dist)

    # ── 2. Pick n_closest nearest cameras ─────────────────────────────────────
    closest = set(ranked[: min(n_closest, len(ranked))])
    best_name = ranked[0]
    best_dist_m = sq_dist(best_name) ** 0.5

    log.info(
        "Target '%s': closest camera is '%s' (%.1f m away), picked %d closest",
        target.id, best_name, best_dist_m, len(closest),
    )

    # ── 3. Fill remaining slots with sequential neighbours around closest ─────
    sorted_names = sorted(cameras.keys())
    anchor_idx = sorted_names.index(best_name)
    selected = set(closest)

    # Expand outward from anchor, alternating before/after
    lo = anchor_idx - 1
    hi = anchor_idx + 1
    while len(selected) < max_images and (lo >= 0 or hi < len(sorted_names)):
        if lo >= 0:
            selected.add(sorted_names[lo])
            lo -= 1
        if len(selected) >= max_images:
            break
        if hi < len(sorted_names):
            selected.add(sorted_names[hi])
            hi += 1

    # ── 4. Return sorted by filename ──────────────────────────────────────────
    result = sorted(selected)
    log.info(
        "Target '%s': returning %d images (%d closest + %d sequential): %s",
        target.id, len(result), len(closest),
        len(result) - len(closest), result,
    )
    return result
