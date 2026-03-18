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
def get_covering_images(project_id: str, target_id: str, max_images: int = 4) -> list[str]:
    """Find images that cover a specific target."""
    project = project_service.load_project(project_id)
    target = next((t for t in project.targets if t.id == target_id), None)
    if target is None:
        raise HTTPException(404, f"Target {target_id} not found")

    try:
        cameras = _load_cameras(project)
    except Exception as e:
        raise HTTPException(400, f"Cannot load cameras: {e}")

    return find_covering_images(target, cameras, max_images=max_images)


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
