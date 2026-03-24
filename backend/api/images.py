"""Image serving and EXIF info API routes."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.ingest.image_index import find_covering_images
from backend.services import project_service
from backend.services.measurement_service import _load_cameras

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/images", tags=["images"])


@router.get("/")
def list_images(project_id: str) -> list[str]:
    """List all image filenames in the project."""
    images_dir = project_service.get_images_dir(project_id)
    if not images_dir.exists():
        return []
    return sorted(
        f.name for f in images_dir.iterdir()
        if f.suffix.lower() in (".jpg", ".jpeg", ".tif", ".tiff")
    )


@router.get("/{image_name}/file")
def serve_image(project_id: str, image_name: str):
    """Serve a raw image file."""
    path = project_service.get_images_dir(project_id) / image_name
    if not path.exists():
        raise HTTPException(404, f"Image {image_name} not found")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/covering/{target_id}")
def get_covering_images(project_id: str, target_id: str, max_images: int = 15) -> list[str]:
    """Find images that cover a specific target.

    Uses projection-based visibility checking: the target's 3D position
    is projected through each camera model to verify it actually appears
    in the image.  Falls back to XY distance if projection finds nothing.
    """
    project = project_service.load_project(project_id)
    target = next((t for t in project.targets if t.id == target_id), None)
    if target is None:
        raise HTTPException(404, f"Target {target_id} not found")

    try:
        cameras = _load_cameras(project)
    except Exception as e:
        raise HTTPException(400, f"Cannot load cameras: {e}")

    # Use DTM for accurate ground Z if available
    ground_z: float | None = None
    if project.dtm_path:
        try:
            from pathlib import Path
            from backend.ingest.dtm_loader import load_dtm
            dtm = load_dtm(Path(project.dtm_path))
            z = dtm.lookup(target.x, target.y)
            if z is not None:
                ground_z = z
        except Exception as e:
            log.debug("DTM lookup failed for ground_z: %s", e)

    return find_covering_images(target, cameras, ground_z=ground_z, max_images=max_images)


@router.get("/covering/{target_id}/projections")
def get_target_projections(project_id: str, target_id: str) -> dict:
    """Project the target's CSV coords and computed position into each covering image.

    Returns per-image pixel coordinates for:
    - csv: target XY from the imported CSV (blue crosshair)
    - computed: triangulated Object Top from marks (green crosshair)
    """
    import numpy as np
    from backend.engine.camera_math import project_point
    from backend.services.measurement_service import _load_marks, _triangulate

    project = project_service.load_project(project_id)
    target = next((t for t in project.targets if t.id == target_id), None)
    if target is None:
        raise HTTPException(404, f"Target {target_id} not found")

    try:
        cameras = _load_cameras(project)
    except Exception as e:
        raise HTTPException(400, f"Cannot load cameras: {e}")

    # Determine ground Z for the CSV target position
    target_z = target.z or 0.0
    if project.dtm_path:
        try:
            from backend.ingest.dtm_loader import load_dtm
            dtm = load_dtm(Path(project.dtm_path))
            z = dtm.lookup(target.x, target.y)
            if z is not None:
                target_z = z
        except Exception:
            pass

    # Project CSV target position into each camera
    target_3d = np.array([target.x, target.y, target_z])
    csv_projections: dict[str, list[float]] = {}
    for name, cam in cameras.items():
        proj = project_point(target_3d, cam)
        if proj is not None:
            csv_projections[name] = [proj[0], proj[1]]

    # Project triangulated Object Top into each camera (if marks exist)
    computed_projections: dict[str, list[float]] = {}
    try:
        mark_set = _load_marks(project_id, target_id)
        base_marks = [m for m in mark_set.marks if m.mark_type == "base"]
        if len(base_marks) >= 2:
            point_3d, _ = _triangulate(base_marks, cameras)
            for name, cam in cameras.items():
                proj = project_point(point_3d, cam)
                if proj is not None:
                    computed_projections[name] = [proj[0], proj[1]]
    except Exception:
        pass

    return {"csv": csv_projections, "computed": computed_projections}


@router.get("/{image_name}/exif")
def get_image_exif(project_id: str, image_name: str) -> dict:
    """Read capture timestamp and GPS coordinates from image EXIF.

    Tries pyexiftool first (if exiftool binary is installed), then falls
    back to Pillow for pure-Python parsing.
    """
    path = project_service.get_images_dir(project_id) / image_name
    if not path.exists():
        raise HTTPException(404, f"Image {image_name} not found")

    # Try pyexiftool (higher quality, reads DJI XMP fields including UTCAtExposure)
    try:
        import exiftool
        from backend.config import settings
        from backend.ingest.exif_parser import parse_single_image
        et_kwargs = {"executable": settings.exiftool_path} if settings.exiftool_path else {}
        with exiftool.ExifToolHelper(**et_kwargs) as et:
            meta = parse_single_image(path, et)
        log.info("EXIF read via exiftool: %s  ts=%s", image_name, meta.timestamp_utc)
        return {
            "capture_time_utc": meta.timestamp_utc.isoformat(),
            "latitude": meta.latitude,
            "longitude": meta.longitude,
            "altitude_msl": meta.altitude_msl,
        }
    except Exception as e:
        log.info("exiftool unavailable (%s), trying Pillow", e)

    # Fallback: Pillow (pure Python, no binary required)
    try:
        return _read_exif_pillow(path)
    except Exception as e:
        log.warning("Pillow EXIF read failed for %s: %s", image_name, e)
        raise HTTPException(400, f"Could not read EXIF from {image_name}: {e}")


def _read_exif_pillow(path: Path) -> dict:
    """Read capture timestamp and GPS from JPEG EXIF using Pillow."""
    from datetime import datetime, timezone
    from PIL import Image

    img = Image.open(path)
    exif = img.getexif()

    GPS_INFO_TAG = 34853       # 0x8825
    DATE_TIME_ORIG_TAG = 36867 # 0x9003

    gps_ifd = exif.get_ifd(GPS_INFO_TAG)

    def dms_to_dd(dms, ref: str) -> float:
        d, m, s = float(dms[0]), float(dms[1]), float(dms[2])
        dd = d + m / 60.0 + s / 3600.0
        return -dd if ref in ("S", "W") else dd

    if not gps_ifd or 2 not in gps_ifd or 4 not in gps_ifd:
        raise ValueError("No GPS data found in EXIF")

    lat = dms_to_dd(gps_ifd[2], gps_ifd.get(1, "N"))
    lon = dms_to_dd(gps_ifd[4], gps_ifd.get(3, "E"))
    alt = float(gps_ifd.get(6, 0.0))

    # Prefer GPS UTC timestamp (tags 29=DateStamp, 7=TimeStamp)
    if 29 in gps_ifd and 7 in gps_ifd:
        date_str = str(gps_ifd[29]).replace(":", "-")
        h, m, s = [float(x) for x in gps_ifd[7]]
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=int(h), minute=int(m), second=int(s), tzinfo=timezone.utc
        )
    else:
        dt_str = exif.get(DATE_TIME_ORIG_TAG, "")
        if not dt_str:
            raise ValueError("No DateTimeOriginal found in EXIF")
        dt = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone.utc)

    log.info("EXIF read via Pillow: %s → %s lat=%.5f lon=%.5f", path.name, dt.isoformat(), lat, lon)
    return {
        "capture_time_utc": dt.isoformat(),
        "latitude": lat,
        "longitude": lon,
        "altitude_msl": alt,
    }
