"""Measurement orchestration: marks → 3D triangulation → height.

Ties together ingestion (camera loading), the multi-view engine, and
project persistence.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from backend.engine.camera_math import pixel_to_ray, ray_to_ground
from backend.engine.ray_intersection import intersect_rays_robust
from backend.engine.height_calc import (
    compute_height, compute_height_dtm, compute_object_top_z_per_image,
)
from backend.engine.solar import sun_position
from backend.ingest.pix4d_parser import load_pix4d_cameras
from backend.ingest.metashape_parser import load_metashape_cameras
from backend.ingest.opf_parser import load_opf_cameras
from backend.models.camera import CameraModel
from backend.models.marking import MarkSet
from backend.models.project import Measurement, Project, Target
from backend.services.project_service import _project_dir, save_project, get_images_dir

log = logging.getLogger(__name__)


def _load_cameras(project: Project) -> dict[str, CameraModel]:
    """Load camera models based on the project's track format."""
    proj_dir = _project_dir(project.id)
    log.info("Loading cameras for project %s (format=%s)", project.id, project.camera_track_format)

    if project.camera_track_format == "metashape":
        path = (
            Path(project.camera_track_path)
            if project.camera_track_path
            else proj_dir / project.camera_track_file
        )
        return load_metashape_cameras(path)

    elif project.camera_track_format == "pix4d":
        if project.camera_track_path:
            ext = Path(project.camera_track_path)
            return load_pix4d_cameras(ext, ext.parent / "internal.cam")
        return load_pix4d_cameras(proj_dir / "external.txt", proj_dir / "internal.cam")

    elif project.camera_track_format == "pix4dmatic":
        opf_dir = (
            Path(project.camera_track_path)
            if project.camera_track_path
            else proj_dir / "opf"
        )
        cameras = load_opf_cameras(opf_dir)
        log.info("Loaded %d cameras from OPF", len(cameras))
        return cameras

    else:
        raise ValueError(f"Unknown camera track format: {project.camera_track_format}")


def _load_marks(project_id: str, target_id: str) -> MarkSet:
    marks_file = _project_dir(project_id) / "marks" / f"{target_id}.json"
    if not marks_file.exists():
        return MarkSet(target_id=target_id)
    return MarkSet.model_validate_json(marks_file.read_text())


def save_marks(project_id: str, mark_set: MarkSet) -> None:
    marks_dir = _project_dir(project_id) / "marks"
    marks_dir.mkdir(exist_ok=True)
    path = marks_dir / f"{mark_set.target_id}.json"
    path.write_text(mark_set.model_dump_json(indent=2))


def get_covering_images(
    project: Project,
    target: Target,
    max_images: int = 15,
) -> list[str]:
    cameras = _load_cameras(project)
    from backend.ingest.image_index import find_covering_images
    return find_covering_images(target, cameras, max_images=max_images)


# ── Per-image EXIF reading ─────────────────────────────────────────────────────

def _read_image_exif(image_path: Path) -> dict | None:
    """Read EXIF from a single image. Returns dict or None on failure."""
    # Try pyexiftool first (reads DJI XMP:UTCAtExposure)
    try:
        import exiftool
        from backend.config import settings
        from backend.ingest.exif_parser import parse_single_image
        et_kwargs = {"executable": settings.exiftool_path} if settings.exiftool_path else {}
        with exiftool.ExifToolHelper(**et_kwargs) as et:
            meta = parse_single_image(image_path, et)
        return {
            "timestamp_utc": meta.timestamp_utc,
            "latitude": meta.latitude,
            "longitude": meta.longitude,
            "altitude_msl": meta.altitude_msl,
        }
    except Exception as e:
        log.debug("exiftool failed for %s: %s — trying Pillow", image_path.name, e)

    # Fallback: Pillow (pure Python, reads GPS timestamp)
    try:
        from datetime import datetime, timezone
        from PIL import Image

        img = Image.open(image_path)
        exif = img.getexif()
        gps_ifd = exif.get_ifd(34853)

        def dms_to_dd(dms, ref: str) -> float:
            d, m, s = float(dms[0]), float(dms[1]), float(dms[2])
            dd = d + m / 60.0 + s / 3600.0
            return -dd if ref in ("S", "W") else dd

        lat = dms_to_dd(gps_ifd[2], gps_ifd.get(1, "N"))
        lon = dms_to_dd(gps_ifd[4], gps_ifd.get(3, "E"))
        alt = float(gps_ifd.get(6, 0.0))

        if 29 in gps_ifd and 7 in gps_ifd:
            date_str = str(gps_ifd[29]).replace(":", "-")
            h, m, s = [float(x) for x in gps_ifd[7]]
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
                hour=int(h), minute=int(m), second=int(s), tzinfo=timezone.utc
            )
        else:
            dt_str = exif.get(36867, "")
            dt = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone.utc)

        return {"timestamp_utc": dt, "latitude": lat, "longitude": lon, "altitude_msl": alt}
    except Exception as e:
        log.warning("Pillow EXIF failed for %s: %s", image_path.name, e)
        return None


def _compute_per_image_sun_angles(
    image_names: list[str],
    images_dir: Path,
) -> dict[str, tuple[float, float]]:
    """Read EXIF from each image and compute (sun_alt, sun_az) per image.

    Includes atmospheric refraction correction: looks up historical weather
    (temperature + pressure) from Open-Meteo, falling back to ISA standard
    atmosphere.  The refraction shifts apparent sun altitude by ~34′ at the
    horizon and <1′ above 45°.

    Returns a dict mapping image_name → (altitude_deg, azimuth_deg) for
    each image that successfully produced EXIF + sun position.
    """
    from backend.engine.atmosphere import get_refraction_params

    results: dict[str, tuple[float, float]] = {}
    for name in image_names:
        path = images_dir / name
        if not path.exists():
            log.warning("Image not found for EXIF: %s", path)
            continue
        meta = _read_image_exif(path)
        if meta is None:
            log.warning("Could not read EXIF from %s", name)
            continue
        try:
            temp_c, pres_mbar = get_refraction_params(
                meta["latitude"],
                meta["longitude"],
                meta["altitude_msl"],
                meta["timestamp_utc"],
            )
            alt, az = sun_position(
                meta["timestamp_utc"],
                meta["latitude"],
                meta["longitude"],
                meta["altitude_msl"],
                temperature_C=temp_c,
                pressure_mbar=pres_mbar,
            )
            log.info(
                "Sun angle for %s at %s → alt=%.3f° az=%.3f° (%.1f°C, %.0f mbar)",
                name, meta["timestamp_utc"].isoformat(), alt, az, temp_c, pres_mbar,
            )
            results[name] = (alt, az)
        except Exception as e:
            log.warning("Sun position failed for %s: %s", name, e)

    return results


# ── Triangulation helper ───────────────────────────────────────────────────────

def _triangulate(
    marks: list,
    cameras: dict[str, CameraModel],
) -> tuple[np.ndarray, float]:
    """Triangulate a list of ImageMark objects into a 3D world point."""
    origins, directions = [], []
    for m in marks:
        cam = cameras.get(m.image_name)
        if cam is None:
            log.warning("Camera not found for image %s — skipping mark", m.image_name)
            continue
        o, d = pixel_to_ray(m.pixel_x, m.pixel_y, cam)
        origins.append(o)
        directions.append(d)

    if len(origins) < 2:
        raise ValueError(
            f"Need at least 2 valid camera references for triangulation, "
            f"got {len(origins)}. Check that camera track is loaded."
        )
    return intersect_rays_robust(origins, directions)


# ── Main computation ───────────────────────────────────────────────────────────

def run_measurement(
    project: Project,
    target_id: str,
    capture_time_utc: datetime | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> Measurement:
    """Execute the full measurement pipeline for a target.

    Pipeline (auto-selected):
      DTM available  →  per-image ray-to-ground for shadow tips (preferred)
      No DTM         →  multi-view triangulation fallback

    Object Top Z is the critical measurement:
      Object Top Z = shadow_length_XY × tan(sun_alt) + DTM(shadow_tip)

    Sun angle strategy:
      Reads EXIF timestamp from each tip-image individually and computes
      the sun angle at that exact moment.  Uses the median sun altitude
      across tip images.  Falls back to the provided capture_time_utc if
      EXIF reading fails for all images.
    """
    import math

    cameras = _load_cameras(project)
    mark_set = _load_marks(project.id, target_id)

    if len(mark_set.base_marks) < 2:
        raise ValueError(f"Need ≥ 2 Object Top marks, got {len(mark_set.base_marks)}")

    # ── Triangulate Object Top (XY from multi-view) ────────────────────────────
    top_3d, top_residual = _triangulate(mark_set.base_marks, cameras)
    log.info(
        "Object top triangulation → (%.3f, %.3f, %.3f) residual=%.4f m",
        *top_3d, top_residual,
    )

    # ── Per-image sun angles from tip images ───────────────────────────────────
    tip_image_names = list({m.image_name for m in mark_set.tip_marks})
    images_dir = get_images_dir(project.id)
    sun_angle_map = _compute_per_image_sun_angles(tip_image_names, images_dir)

    if sun_angle_map:
        altitudes = [a for a, _ in sun_angle_map.values()]
        azimuths  = [z for _, z in sun_angle_map.values()]
        sun_alt = float(np.median(altitudes))  # median for reporting / fallback
        sun_az  = float(np.median(azimuths))
        log.info(
            "Per-image sun altitudes from %d tip image(s):",
            len(sun_angle_map),
        )
        for img_name, (a, az) in sun_angle_map.items():
            log.info("  %s → alt=%.4f° az=%.4f°", img_name, a, az)
        log.info("  median → alt=%.4f° az=%.4f°", sun_alt, sun_az)
    elif capture_time_utc is not None and latitude is not None and longitude is not None:
        log.warning("EXIF unavailable for all tip images — falling back to provided timestamp")
        from backend.engine.atmosphere import get_refraction_params
        temp_c, pres_mbar = get_refraction_params(latitude, longitude, 0.0, capture_time_utc)
        sun_alt, sun_az = sun_position(
            capture_time_utc, latitude, longitude,
            temperature_C=temp_c, pressure_mbar=pres_mbar,
        )
    else:
        raise ValueError(
            "Could not read EXIF from any tip image and no fallback timestamp was provided. "
            "Ensure the images directory is correct and images contain GPS/timestamp data."
        )

    # ── Shadow tip: per-image ray-to-ground (preferred) or triangulation ──────
    use_ray_to_ground = bool(project.dtm_path)
    dtm = None
    dtm_cell_size = 0.0

    if use_ray_to_ground:
        from backend.ingest.dtm_loader import load_dtm
        dtm = load_dtm(Path(project.dtm_path))
        dtm_cell_size = abs(dtm.sx)  # metres per pixel

        if len(mark_set.tip_marks) < 1:
            raise ValueError(f"Need ≥ 1 Shadow Tip mark, got {len(mark_set.tip_marks)}")

        # Project each tip mark independently to DTM ground surface
        tip_ground_points: list[np.ndarray] = []
        tip_sun_alts: list[float] = []
        tip_image_labels: list[str] = []
        for m in mark_set.tip_marks:
            cam = cameras.get(m.image_name)
            if cam is None:
                log.warning("Camera not found for image %s — skipping tip mark", m.image_name)
                continue
            pt = ray_to_ground(m.pixel_x, m.pixel_y, cam, dtm)
            if pt is not None:
                tip_ground_points.append(pt)
                tip_image_labels.append(m.image_name)
                # Use this image's own sun altitude, fall back to median
                if m.image_name in sun_angle_map:
                    tip_sun_alts.append(sun_angle_map[m.image_name][0])
                else:
                    log.warning(
                        "No per-image sun angle for %s — using median %.4f°",
                        m.image_name, sun_alt,
                    )
                    tip_sun_alts.append(sun_alt)
            else:
                log.warning("ray_to_ground failed for tip mark on %s", m.image_name)

        if not tip_ground_points:
            raise ValueError("All tip ray-to-ground projections failed. Check DTM coverage.")

        n_tip_images = len(tip_ground_points)

        # Compute per-image Object Top Z (the critical measurement)
        # Each image uses its own sun altitude from EXIF timestamp
        top_xy = np.array([top_3d[0], top_3d[1]])
        object_top_z, object_top_z_spread, per_image_z = \
            compute_object_top_z_per_image(top_xy, tip_ground_points, tip_sun_alts)

        # Median tip ground point for reporting
        tip_pts = np.array(tip_ground_points)
        median_tip = np.median(tip_pts, axis=0)

        # Tip spread: std of XY distance from median
        if len(tip_ground_points) >= 2:
            tip_dists = [float(np.sqrt(
                (p[0] - median_tip[0])**2 + (p[1] - median_tip[1])**2
            )) for p in tip_ground_points]
            tip_spread = float(np.std(tip_dists))
        else:
            tip_spread = 0.0

        # DTM ground elevation at object top XY
        ground_z_top = dtm.lookup(top_3d[0], top_3d[1])
        if ground_z_top is None:
            raise ValueError(
                f"Object top XY ({top_3d[0]:.1f}, {top_3d[1]:.1f}) "
                "falls outside DTM extent."
            )

        # Relative height = Object Top Z - ground elevation at base
        computed_height = object_top_z - ground_z_top

        # Shadow length from triangulated top XY to median tip XY
        shadow_length_h = float(np.sqrt(
            (median_tip[0] - top_3d[0])**2 + (median_tip[1] - top_3d[1])**2
        ))

        # Legacy confidence fields (for backward compat)
        tip_residual = tip_spread
        confidence = float(np.sqrt(top_residual**2 + tip_spread**2))

        log.info(
            "Per-image ray-to-ground → %d tips  Object Top Z=%.4f  spread=%.4f m  "
            "tip_spread=%.4f m  height=%.4f m  ground_z=%.3f",
            n_tip_images, object_top_z, object_top_z_spread,
            tip_spread, computed_height, ground_z_top,
        )
        for label, z_i, s_alt in zip(tip_image_labels, per_image_z, tip_sun_alts):
            log.info("  image %s → Object Top Z = %.4f m  (sun_alt=%.4f°)", label, z_i, s_alt)

        return Measurement(
            target_id=target_id,
            base_x=float(top_3d[0]),
            base_y=float(top_3d[1]),
            base_z=float(ground_z_top),
            tip_x=float(median_tip[0]),
            tip_y=float(median_tip[1]),
            tip_z=float(median_tip[2]),
            shadow_length_horizontal=shadow_length_h,
            sun_altitude_deg=sun_alt,
            sun_azimuth_deg=sun_az,
            computed_height=computed_height,
            confidence=confidence,
            top_residual=float(top_residual),
            tip_residual=float(tip_residual),
            shadow_length_confidence=confidence,
            height_confidence=object_top_z_spread,
            object_top_z=object_top_z,
            object_top_z_spread=object_top_z_spread,
            tip_spread=tip_spread,
            per_image_object_top_z=per_image_z,
            n_tip_images=n_tip_images,
            method="ray_to_ground",
            dtm_cell_size=dtm_cell_size,
            timestamp_utc=(
                sun_angle_map and
                f"per-image median of {len(sun_angle_map)} images"
                or (capture_time_utc.isoformat() if capture_time_utc else "unknown")
            ),
        )

    # ── Fallback: full triangulation (no DTM) ─────────────────────────────────
    if len(mark_set.tip_marks) < 2:
        raise ValueError(f"Need ≥ 2 Shadow Tip marks (no DTM), got {len(mark_set.tip_marks)}")

    tip_3d, tip_residual = _triangulate(mark_set.tip_marks, cameras)
    log.info(
        "Shadow tip triangulation → (%.3f, %.3f, %.3f) residual=%.4f m",
        *tip_3d, tip_residual,
    )

    computed_height = compute_height(top_3d, tip_3d, sun_alt)
    ground_z_top = float(top_3d[2])
    ground_z_tip = float(tip_3d[2])
    object_top_z = ground_z_top + computed_height

    confidence = float(np.sqrt(top_residual**2 + tip_residual**2))
    tan_sun = math.tan(math.radians(sun_alt))
    shadow_length_confidence = confidence
    height_confidence = float(np.sqrt(
        (tan_sun * shadow_length_confidence) ** 2 + confidence ** 2
    ))

    log.info("Triangulation fallback → height=%.4f m  confidence=%.4f m", computed_height, confidence)

    return Measurement(
        target_id=target_id,
        base_x=float(top_3d[0]),
        base_y=float(top_3d[1]),
        base_z=float(ground_z_top),
        tip_x=float(tip_3d[0]),
        tip_y=float(tip_3d[1]),
        tip_z=float(ground_z_tip),
        shadow_length_horizontal=float(np.sqrt(
            (tip_3d[0] - top_3d[0])**2 + (tip_3d[1] - top_3d[1])**2
        )),
        sun_altitude_deg=sun_alt,
        sun_azimuth_deg=sun_az,
        computed_height=computed_height,
        confidence=confidence,
        top_residual=float(top_residual),
        tip_residual=float(tip_residual),
        shadow_length_confidence=shadow_length_confidence,
        height_confidence=height_confidence,
        object_top_z=object_top_z,
        object_top_z_spread=0.0,
        method="triangulation",
        timestamp_utc=(
            sun_angle_map and
            f"per-image median of {len(sun_angle_map)} images"
            or (capture_time_utc.isoformat() if capture_time_utc else "unknown")
        ),
    )
