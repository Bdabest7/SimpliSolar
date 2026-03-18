"""Multi-view orchestration: pixel marks → 3D points → height.

This module ties together the camera math, ray intersection, solar
ephemeris, and height calculation into a single measurement pipeline.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from backend.engine.camera_math import pixel_to_ray
from backend.engine.ray_intersection import intersect_rays, intersect_rays_robust
from backend.engine.solar import sun_position
from backend.engine.height_calc import compute_height
from backend.models.camera import CameraModel
from backend.models.marking import MarkSet, MarkType
from backend.models.project import Measurement


def triangulate_marks(
    marks: list[tuple[float, float, CameraModel]],
    robust: bool = True,
) -> tuple[np.ndarray, float]:
    """Triangulate a set of pixel marks into a 3D world point.

    Parameters
    ----------
    marks : list of (pixel_x, pixel_y, CameraModel)
    robust : bool
        Use outlier-rejecting intersection.

    Returns
    -------
    point_3d : ndarray, shape (3,)
    residual : float (metres)
    """
    origins = []
    directions = []
    for px, py, cam in marks:
        o, d = pixel_to_ray(px, py, cam)
        origins.append(o)
        directions.append(d)

    if robust:
        return intersect_rays_robust(origins, directions)
    return intersect_rays(origins, directions)


def compute_measurement(
    mark_set: MarkSet,
    cameras: dict[str, CameraModel],
    capture_time_utc: datetime,
    latitude: float,
    longitude: float,
    elevation_m: float = 0.0,
) -> Measurement:
    """Full pipeline: marks → triangulation → sun angle → height.

    Parameters
    ----------
    mark_set : MarkSet
        User marks for one target.
    cameras : dict
        Mapping of image_name → CameraModel.
    capture_time_utc : datetime
        UTC timestamp for solar calculation (from the best image EXIF).
    latitude, longitude : float
        WGS84 coordinates for solar calculation.
    elevation_m : float
        Observer elevation above ellipsoid.

    Returns
    -------
    Measurement with all computed fields populated.
    """
    # Build mark tuples
    base_marks = [
        (m.pixel_x, m.pixel_y, cameras[m.image_name])
        for m in mark_set.base_marks
    ]
    tip_marks = [
        (m.pixel_x, m.pixel_y, cameras[m.image_name])
        for m in mark_set.tip_marks
    ]

    if len(base_marks) < 2:
        raise ValueError(f"Need >= 2 base marks, got {len(base_marks)}")
    if len(tip_marks) < 2:
        raise ValueError(f"Need >= 2 tip marks, got {len(tip_marks)}")

    # Triangulate base and tip
    base_3d, base_residual = triangulate_marks(base_marks)
    tip_3d, tip_residual = triangulate_marks(tip_marks)

    # Solar position
    sun_alt, sun_az = sun_position(
        capture_time_utc, latitude, longitude, elevation_m
    )

    # Height
    height = compute_height(base_3d, tip_3d, sun_alt)

    # Combined confidence (RMS of both residuals)
    confidence = np.sqrt(base_residual**2 + tip_residual**2)

    return Measurement(
        target_id=mark_set.target_id,
        base_x=float(base_3d[0]),
        base_y=float(base_3d[1]),
        base_z=float(base_3d[2]),
        tip_x=float(tip_3d[0]),
        tip_y=float(tip_3d[1]),
        tip_z=float(tip_3d[2]),
        shadow_length_horizontal=float(np.sqrt(
            (tip_3d[0] - base_3d[0])**2 + (tip_3d[1] - base_3d[1])**2
        )),
        sun_altitude_deg=sun_alt,
        sun_azimuth_deg=sun_az,
        computed_height=height,
        confidence=float(confidence),
        timestamp_utc=capture_time_utc.isoformat(),
    )
