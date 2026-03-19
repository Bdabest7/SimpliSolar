"""Height calculation from shadow vector and solar angle.

Core formula (terrain-corrected):
    object_height = horizontal_shadow_length * tan(sun_altitude)
                  + (z_shadow_tip - z_object_base)

The horizontal shadow length is measured in the XY plane.  The Δz term
corrects for ground slope between the object base and shadow tip:
  - Shadow going downhill  (z_tip < z_base): Δz < 0, shadow is longer → subtract
  - Shadow going uphill    (z_tip > z_base): Δz > 0, shadow is shorter → add back

Both endpoints are triangulated in world coordinates (base CRS, metres).
This correction requires marking the actual ground-level base of the object.
"""

from __future__ import annotations

import math

import numpy as np


def compute_height(
    base_3d: np.ndarray,
    tip_3d: np.ndarray,
    sun_altitude_deg: float,
) -> float:
    """Calculate object height from 3D base/tip and sun altitude.

    Parameters
    ----------
    base_3d : ndarray, shape (3,)
        [X, Y, Z] of the object base in world coords.
    tip_3d : ndarray, shape (3,)
        [X, Y, Z] of the shadow tip in world coords.
    sun_altitude_deg : float
        Sun elevation above horizon in degrees.

    Returns
    -------
    height : float
        Calculated height of the object in the same units as the
        input coordinates (typically metres).

    Raises
    ------
    ValueError
        If sun altitude is <= 0 (no shadow possible).
    """
    if sun_altitude_deg <= 0:
        raise ValueError(
            f"Sun altitude must be positive, got {sun_altitude_deg:.2f}°. "
            "Shadows cannot be measured when the sun is below the horizon."
        )

    # Horizontal shadow length (XY plane only)
    dx = tip_3d[0] - base_3d[0]
    dy = tip_3d[1] - base_3d[1]
    shadow_length_h = math.sqrt(dx * dx + dy * dy)

    sun_alt_rad = math.radians(sun_altitude_deg)

    # Terrain slope correction: Δz = z_tip − z_base
    # Positive if tip is on higher ground than base (uphill shadow → add back)
    # Negative if tip is on lower ground (downhill shadow → subtract)
    dz = float(tip_3d[2]) - float(base_3d[2])

    height = shadow_length_h * math.tan(sun_alt_rad) + dz

    return height


def compute_height_dtm(
    top_3d: np.ndarray,
    tip_3d: np.ndarray,
    sun_altitude_deg: float,
    dtm,
) -> tuple[float, float, float]:
    """Calculate object height using shadow-length + DTM terrain correction.

    From aerial drone imagery, triangulated Z is unreliable (rays are nearly
    parallel vertically, so Z converges near camera altitude).  Instead we
    use the well-constrained XY triangulation for shadow length, and the DTM
    for ground elevations at both the object and shadow tip positions.

    Formula:
        h = shadow_length_XY × tan(sun_alt) + (DTM(tip) − DTM(top))

    The DTM term corrects for terrain slope between the object and shadow tip.

    Returns
    -------
    height : float
    ground_z_top : float  (DTM elevation at object top XY)
    ground_z_tip : float  (DTM elevation at shadow tip XY)
    """
    if sun_altitude_deg <= 0:
        raise ValueError(
            f"Sun altitude must be positive, got {sun_altitude_deg:.2f}°."
        )

    ground_z_top = dtm.lookup(top_3d[0], top_3d[1])
    if ground_z_top is None:
        raise ValueError(
            f"Object top position ({top_3d[0]:.1f}, {top_3d[1]:.1f}) "
            "falls outside the DTM extent."
        )

    ground_z_tip = dtm.lookup(tip_3d[0], tip_3d[1])
    if ground_z_tip is None:
        raise ValueError(
            f"Shadow tip position ({tip_3d[0]:.1f}, {tip_3d[1]:.1f}) "
            "falls outside the DTM extent."
        )

    dx = tip_3d[0] - top_3d[0]
    dy = tip_3d[1] - top_3d[1]
    shadow_length_h = math.sqrt(dx * dx + dy * dy)

    sun_alt_rad = math.radians(sun_altitude_deg)
    slope_correction = ground_z_tip - ground_z_top

    height = shadow_length_h * math.tan(sun_alt_rad) + slope_correction
    return height, ground_z_top, ground_z_tip


def compute_height_multi_view(
    base_estimates: list[np.ndarray],
    tip_estimates: list[np.ndarray],
    sun_altitude_deg: float,
) -> tuple[float, float]:
    """Compute height from multiple base/tip triangulation estimates.

    Takes the median height across all estimate pairs for robustness.

    Returns
    -------
    median_height : float
    spread : float
        Half the interquartile range — a measure of measurement consistency.
    """
    heights = []
    for base, tip in zip(base_estimates, tip_estimates):
        h = compute_height(base, tip, sun_altitude_deg)
        heights.append(h)

    heights_arr = np.array(heights)
    median_h = float(np.median(heights_arr))

    if len(heights_arr) >= 4:
        q75, q25 = np.percentile(heights_arr, [75, 25])
        spread = (q75 - q25) / 2.0
    else:
        spread = float(np.std(heights_arr))

    return median_h, spread


def compute_object_top_z_per_image(
    top_xy: np.ndarray,
    tip_ground_points: list[np.ndarray],
    sun_altitudes_deg: list[float] | float,
) -> tuple[float, float, list[float]]:
    """Compute Object Top Z independently from each shadow-tip ground point.

    For each tip ground point (from ray-to-ground projection):
        shadow_len = XY distance from top_xy to tip_i
        object_top_z_i = shadow_len × tan(sun_alt_i) + tip_z_i

    Each image uses its own sun altitude computed from that image's EXIF
    timestamp, accounting for sun movement between flight lines.

    Parameters
    ----------
    top_xy : ndarray, shape (2,) or (3,) — [X, Y] of object top from triangulation.
    tip_ground_points : list of ndarray, each shape (3,) — [X, Y, Z] per-image.
    sun_altitudes_deg : list[float] | float — per-image sun elevation(s) above
        horizon in degrees.  If a single float, used for all images.

    Returns
    -------
    median_z : float — median Object Top Z across images.
    z_spread : float — std (or IQR/2 for N≥4) of per-image Z values.
    per_image_z : list[float] — individual Z estimates for diagnostics.
    """
    # Normalise to per-image list
    if isinstance(sun_altitudes_deg, (int, float)):
        sun_altitudes_deg = [float(sun_altitudes_deg)] * len(tip_ground_points)

    if len(sun_altitudes_deg) != len(tip_ground_points):
        raise ValueError(
            f"sun_altitudes_deg length ({len(sun_altitudes_deg)}) != "
            f"tip_ground_points length ({len(tip_ground_points)})"
        )

    per_image_z: list[float] = []

    for tip, sun_alt in zip(tip_ground_points, sun_altitudes_deg):
        if sun_alt <= 0:
            raise ValueError(
                f"Sun altitude must be positive, got {sun_alt:.2f}°."
            )
        tan_sun = math.tan(math.radians(sun_alt))
        dx = tip[0] - top_xy[0]
        dy = tip[1] - top_xy[1]
        shadow_len = math.sqrt(dx * dx + dy * dy)
        object_top_z = shadow_len * tan_sun + float(tip[2])
        per_image_z.append(object_top_z)

    z_arr = np.array(per_image_z)
    median_z = float(np.median(z_arr))

    if len(z_arr) >= 4:
        q75, q25 = np.percentile(z_arr, [75, 25])
        z_spread = (q75 - q25) / 2.0
    elif len(z_arr) >= 2:
        z_spread = float(np.std(z_arr))
    else:
        z_spread = 0.0  # single image — no cross-check possible

    return median_z, float(z_spread), per_image_z
