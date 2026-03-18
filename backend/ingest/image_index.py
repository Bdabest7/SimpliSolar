"""Spatial image index: find which images cover a given target XY.

Selection strategy
------------------
1. Find the camera whose XY position is closest to the target coordinate.
   This is the "anchor" — the frame where the drone was nearest overhead.
2. Sort all camera filenames (alphabetical order matches the sequential
   numbering used by DJI and most drone cameras).
3. Return a window of ``max_images`` filenames centred on the anchor
   (1 frame before, then the anchor, then frames after).  Sequential
   neighbours capture the target from slightly different angles as the
   drone approached and departed — ideal for multi-view triangulation.
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
    max_images: int = 4,
    margin_px: int = 100,
) -> list[str]:
    """Return sequential image names centred on the closest camera to the target.

    Parameters
    ----------
    target : Target
        Target with approximate X, Y world coordinates.
    cameras : dict
        All camera models keyed by image name.
    max_images : int
        Number of images to return (default 4 for a 2×2 grid).
    ground_z, margin_px : unused — kept for API compatibility.

    Returns
    -------
    List of image names in filename order, anchor image at index 1.
    """
    if not cameras:
        log.warning("No cameras loaded — cannot find covering images for target '%s'", target.id)
        return []

    log.info(
        "Finding covering images for target '%s' at (%.3f, %.3f) across %d cameras",
        target.id, target.x, target.y, len(cameras),
    )

    # 1. Find the camera whose XY ground position is closest to the target
    def sq_dist(name: str) -> float:
        c = cameras[name]
        dx = c.extrinsics.x - target.x
        dy = c.extrinsics.y - target.y
        return dx * dx + dy * dy

    best_name = min(cameras.keys(), key=sq_dist)
    best_dist_m = sq_dist(best_name) ** 0.5

    log.info(
        "Target '%s': closest camera is '%s' (%.1f m away)",
        target.id, best_name, best_dist_m,
    )

    # 2. Sort filenames — alphabetical == sequential for zero-padded DJI names
    sorted_names = sorted(cameras.keys())
    best_idx = sorted_names.index(best_name)

    # 3. Window: 1 frame before anchor, anchor at position 1, rest after
    start = max(0, best_idx - 1)
    end = start + max_images
    if end > len(sorted_names):
        end = len(sorted_names)
        start = max(0, end - max_images)

    result = sorted_names[start:end]
    log.info(
        "Target '%s': returning %d images (anchor idx %d, window [%d:%d]): %s",
        target.id, len(result), best_idx, start, end, result,
    )
    return result
