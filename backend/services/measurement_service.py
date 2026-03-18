"""Measurement orchestration: marks → 3D triangulation → height.

Ties together ingestion (camera loading), the multi-view engine, and
project persistence.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from backend.engine.camera_math import pixel_to_ray
from backend.engine.ray_intersection import intersect_rays_robust
from backend.engine.height_calc import compute_height, compute_height_dsm
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
    max_images: int = 4,
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
) -> list[tuple[float, float]]:
    """Read EXIF from each image and compute (sun_alt, sun_az) per image.

    Returns a list of (altitude_deg, azimuth_deg) tuples, one per image
    that successfully produced EXIF + sun position.  Empty if all fail.
    """
    results = []
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
            alt, az = sun_position(
                meta["timestamp_utc"],
                meta["latitude"],
                meta["longitude"],
                meta["altitude_msl"],
            )
            log.info(
                "Sun angle for %s at %s → alt=%.3f° az=%.3f°",
                name, meta["timestamp_utc"].isoformat(), alt, az,
            )
            results.append((alt, az))
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

    Height calculation strategy (auto-selected):
      DSM available  →  top_3d.z  minus  DSM ground elevation at top XY
      Base marks     →  shadow_length_horizontal × tan(sun_alt) + Δz terrain correction
      (DSM takes priority if configured)

    Sun angle strategy:
      Reads EXIF timestamp from each tip-image individually and computes
      the sun angle at that exact moment.  Uses the median sun altitude
      across tip images, so battery changes between images are handled
      gracefully.  Falls back to the provided capture_time_utc if EXIF
      reading fails for all images.
    """
    cameras = _load_cameras(project)
    mark_set = _load_marks(project.id, target_id)

    if len(mark_set.base_marks) < 2:
        raise ValueError(f"Need ≥ 2 Object Top marks, got {len(mark_set.base_marks)}")
    if len(mark_set.tip_marks) < 2:
        raise ValueError(f"Need ≥ 2 Shadow Tip marks, got {len(mark_set.tip_marks)}")

    # ── Triangulate 3D positions ───────────────────────────────────────────────
    top_3d, top_residual = _triangulate(mark_set.base_marks, cameras)
    tip_3d, tip_residual = _triangulate(mark_set.tip_marks, cameras)
    log.info(
        "Triangulation → top=(%.3f, %.3f, %.3f) residual=%.4f m  "
        "tip=(%.3f, %.3f, %.3f) residual=%.4f m",
        *top_3d, top_residual, *tip_3d, tip_residual,
    )

    # ── Per-image sun angles from tip images ───────────────────────────────────
    tip_image_names = list({m.image_name for m in mark_set.tip_marks})
    images_dir = get_images_dir(project.id)
    sun_angles = _compute_per_image_sun_angles(tip_image_names, images_dir)

    if sun_angles:
        altitudes = [a for a, _ in sun_angles]
        azimuths  = [z for _, z in sun_angles]
        sun_alt = float(np.median(altitudes))
        sun_az  = float(np.median(azimuths))
        log.info(
            "Sun angles from %d tip image(s): alt=[%s] → median=%.4f°",
            len(sun_angles),
            ", ".join(f"{a:.3f}" for a in altitudes),
            sun_alt,
        )
    elif capture_time_utc is not None and latitude is not None and longitude is not None:
        log.warning("EXIF unavailable for all tip images — falling back to provided timestamp")
        sun_alt, sun_az = sun_position(capture_time_utc, latitude, longitude)
    else:
        raise ValueError(
            "Could not read EXIF from any tip image and no fallback timestamp was provided. "
            "Ensure the images directory is correct and images contain GPS/timestamp data."
        )

    # ── Height calculation ─────────────────────────────────────────────────────
    # Always use shadow-length formula.  Triangulated Z from aerial imagery is
    # unreliable (rays nearly parallel vertically → Z drifts to camera altitude).
    # DSM provides terrain slope correction; without DSM, triangulated Δz is used.
    if project.dsm_path:
        from backend.ingest.dsm_loader import load_dsm
        log.info("Using shadow-length + DSM slope correction: %s", project.dsm_path)
        dsm = load_dsm(Path(project.dsm_path))
        computed_height, ground_z_top, ground_z_tip = compute_height_dsm(
            top_3d, tip_3d, sun_alt, dsm,
        )
        log.info(
            "DSM-corrected height: shadow=%.3f m  DSM(top)=%.3f  DSM(tip)=%.3f  "
            "slope=%.3f m  height=%.4f m",
            float(np.sqrt((tip_3d[0]-top_3d[0])**2 + (tip_3d[1]-top_3d[1])**2)),
            ground_z_top, ground_z_tip,
            ground_z_tip - ground_z_top,
            computed_height,
        )
    else:
        log.info("Using shadow-length height method (no DSM, triangulated Δz)")
        computed_height = compute_height(top_3d, tip_3d, sun_alt)
        ground_z_top = float(top_3d[2])
        ground_z_tip = float(tip_3d[2])
        log.info("Shadow height: %.4f m", computed_height)

    confidence = float(np.sqrt(top_residual**2 + tip_residual**2))

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
        timestamp_utc=(
            sun_angles and
            f"per-image median of {len(sun_angles)} images"
            or (capture_time_utc.isoformat() if capture_time_utc else "unknown")
        ),
    )
