"""Spatial image index: find which images cover a given target XY.

Selection strategy
------------------
1. **Projection check** (primary): project the target's 3D position into
   each camera using the full camera model (intrinsics + extrinsics).
   Cameras where the target lands inside the image frame are *confirmed*
   visible.  Rank by proximity to image centre (closer = more reliable
   marks).

2. **X/Y swap recovery**: if no cameras see the target, try with swapped
   X and Y.  Surveying CSVs often export Northing as "X" and Easting as
   "Y", the opposite of photogrammetry convention.  If swapping fixes
   visibility, auto-correct and warn.

3. **XY-distance fallback**: last resort if projection still finds nothing.
"""

from __future__ import annotations

import logging

import numpy as np

from backend.engine.camera_math import project_point
from backend.models.camera import CameraModel
from backend.models.project import Target

log = logging.getLogger(__name__)


def _estimate_ground_z(cameras: dict[str, CameraModel]) -> float:
    """Estimate ground Z from camera altitudes (assumes ~100 m AGL flight)."""
    zs = [c.extrinsics.z for c in cameras.values()]
    return float(np.median(zs)) - 100.0 if zs else 0.0


def _find_visible(
    target_3d: np.ndarray,
    cameras: dict[str, CameraModel],
    margin_px: int,
) -> list[tuple[str, float]]:
    """Return cameras where target_3d projects inside the image frame.

    Returns list of (image_name, xy_distance_m), unsorted.
    Ranked by physical XY distance from camera to target — closer cameras
    give better GSD and more reliable marks.
    """
    visible: list[tuple[str, float]] = []
    for name, cam in cameras.items():
        proj = project_point(target_3d, cam)
        if proj is None:
            continue

        u, v = proj
        if (u < margin_px or u > cam.intrinsics.image_width - margin_px
                or v < margin_px or v > cam.intrinsics.image_height - margin_px):
            continue

        dx = cam.extrinsics.x - target_3d[0]
        dy = cam.extrinsics.y - target_3d[1]
        xy_dist = (dx * dx + dy * dy) ** 0.5
        visible.append((name, xy_dist))

    return visible


def find_covering_images(
    target: Target,
    cameras: dict[str, CameraModel],
    ground_z: float | None = None,
    max_images: int = 15,
    n_closest: int = 5,
    margin_px: int = 100,
) -> list[str]:
    """Return images that cover a target, ranked by view quality.

    Parameters
    ----------
    target : Target
        Target with approximate X, Y world coordinates (and optional Z).
    cameras : dict
        All camera models keyed by image name.
    ground_z : float | None
        Override ground elevation for the target.  If None, uses target.z
        or estimates from camera altitudes.
    max_images : int
        Maximum number of images to return (default 15).
    n_closest : int
        Number of spatially closest cameras to always include in fallback
        mode (default 5).
    margin_px : int
        Pixel margin inside image edges — target must be at least this far
        from the border to count as "visible" (avoids edge marks).

    Returns
    -------
    List of image names sorted by filename.
    """
    if not cameras:
        log.warning("No cameras loaded — cannot find covering images for target '%s'", target.id)
        return []

    # ── Estimate target 3D position ─────────────────────────────────────────
    if ground_z is not None:
        target_z = ground_z
    elif target.z is not None:
        target_z = target.z
    else:
        target_z = _estimate_ground_z(cameras)

    target_3d = np.array([target.x, target.y, target_z])

    log.info(
        "Finding covering images for target '%s' at (%.3f, %.3f, %.3f) across %d cameras",
        target.id, target.x, target.y, target_z, len(cameras),
    )

    # ── Phase 1: Projection-based visibility check ──────────────────────────
    visible = _find_visible(target_3d, cameras, margin_px)

    if visible:
        visible.sort(key=lambda x: x[1])
        result = [name for name, _ in visible[:max_images]]
        log.info(
            "Target '%s': %d/%d cameras can see the target (returning %d). "
            "Closest: '%s' (%.1f m away)",
            target.id, len(visible), len(cameras), len(result),
            visible[0][0], visible[0][1],
        )
        return result

    # ── Phase 2: Try with X/Y swapped ──────────────────────────────────────
    # Surveying CSVs often export Northing as X and Easting as Y,
    # opposite of the photogrammetry convention.  If the target is not
    # visible with original coords but IS visible with swapped coords,
    # auto-correct.
    target_3d_swapped = np.array([target.y, target.x, target_z])
    visible_swapped = _find_visible(target_3d_swapped, cameras, margin_px)

    if visible_swapped:
        log.warning(
            "Target '%s' X/Y SWAPPED: original (%.3f, %.3f) not visible in any camera, "
            "but swapped (%.3f, %.3f) is visible in %d cameras. "
            "The target CSV likely has Northing/Easting reversed vs the camera track. "
            "Using swapped coordinates.",
            target.id, target.x, target.y, target.y, target.x,
            len(visible_swapped),
        )
        visible_swapped.sort(key=lambda x: x[1])
        result = [name for name, _ in visible_swapped[:max_images]]
        log.info(
            "Target '%s' (swapped): returning %d images. Closest: '%s' (%.1f m away)",
            target.id, len(result), visible_swapped[0][0], visible_swapped[0][1],
        )
        return result

    # ── Phase 3: Fallback — XY distance ─────────────────────────────────────
    cam_xs = [c.extrinsics.x for c in cameras.values()]
    cam_ys = [c.extrinsics.y for c in cameras.values()]
    log.warning(
        "Target '%s' at (%.3f, %.3f) is NOT visible in any camera via projection "
        "(even with X/Y swapped). "
        "Camera X range: %.1f–%.1f  Y range: %.1f–%.1f. "
        "Possible CRS mismatch. Falling back to XY distance.",
        target.id, target.x, target.y,
        min(cam_xs), max(cam_xs), min(cam_ys), max(cam_ys),
    )

    def sq_dist(name: str) -> float:
        c = cameras[name]
        dx = c.extrinsics.x - target.x
        dy = c.extrinsics.y - target.y
        return dx * dx + dy * dy

    ranked = sorted(cameras.keys(), key=sq_dist)

    closest = set(ranked[: min(n_closest, len(ranked))])
    best_name = ranked[0]
    best_dist_m = sq_dist(best_name) ** 0.5

    log.warning(
        "XY fallback: closest camera '%s' is %.1f m away (if > 1000 m, coordinates are likely wrong)",
        best_name, best_dist_m,
    )

    sorted_names = sorted(cameras.keys())
    anchor_idx = sorted_names.index(best_name)
    selected = set(closest)

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

    result = sorted(selected, key=sq_dist)
    log.info(
        "Target '%s': returning %d images via XY fallback: %s",
        target.id, len(result), result,
    )
    return result
