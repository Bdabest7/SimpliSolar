"""EXIF/XMP metadata extraction from DJI RTK drone images.

Uses PyExifTool to extract:
- Microsecond-precise timestamps (DateTimeOriginal + SubSecTimeOriginal)
- GPS coordinates and UTC time (GPSDateStamp + GPSTimeStamp)
- DJI RTK quality flags (drone-dji:RtkStdLon, RtkStdLat, RtkStdHgt)
- DJI-specific XMP fields for cross-referencing with camera tracks
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import exiftool


@dataclass
class ImageMetadata:
    """Parsed metadata for one drone image."""

    filename: str
    timestamp_utc: datetime
    latitude: float
    longitude: float
    altitude_msl: float
    rtk_std_lon: float | None = None
    rtk_std_lat: float | None = None
    rtk_std_hgt: float | None = None
    rtk_flag: str | None = None  # e.g. "50" = RTK fixed
    image_width: int = 0
    image_height: int = 0


def _parse_gps_timestamp(date_str: str, time_parts: list) -> datetime:
    """Combine GPSDateStamp + GPSTimeStamp into a UTC datetime."""
    # GPSDateStamp = "2024:06:15", GPSTimeStamp = "14 30 22.123"
    # or GPSTimeStamp may be a list of three values
    date_str = date_str.replace(":", "-")
    if isinstance(time_parts, str):
        parts = time_parts.split()
    else:
        parts = [str(p) for p in time_parts]

    h, m = int(float(parts[0])), int(float(parts[1]))
    s_full = float(parts[2])
    s = int(s_full)
    us = int((s_full - s) * 1_000_000)

    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.replace(hour=h, minute=m, second=s, microsecond=us, tzinfo=timezone.utc)


def _parse_exif_datetime(dt_str: str, subsec: str | None = None) -> datetime:
    """Parse EXIF DateTimeOriginal + SubSecTimeOriginal."""
    # "2024:06:15 14:30:22"
    dt = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
    us = 0
    if subsec:
        # SubSecTimeOriginal is typically microseconds or fractional
        frac = float(f"0.{subsec}")
        us = int(frac * 1_000_000)
    return dt.replace(microsecond=us, tzinfo=timezone.utc)


def parse_single_image(filepath: str | Path, et: exiftool.ExifToolHelper) -> ImageMetadata:
    """Extract metadata from one image using an existing ExifTool session."""
    filepath = str(filepath)
    metadata_list = et.get_metadata(filepath)
    if not metadata_list:
        raise ValueError(f"No EXIF data found for {filepath}")
    m = metadata_list[0]

    # Timestamp priority:
    # 1. XMP:UTCAtExposure — DJI's microsecond-precise UTC field (most accurate)
    # 2. GPS timestamp    — also UTC, from satellite clock
    # 3. DateTimeOriginal — camera local time (least preferred, may be wrong timezone)
    utc_at_exposure = m.get("XMP:UTCAtExposure") or m.get("XMP-drone-dji:UTCAtExposure")
    if utc_at_exposure:
        # Format: "2024:05:21 20:18:09.284698"
        ts = _parse_exif_datetime(
            utc_at_exposure.split(".")[0],       # strip subseconds for strptime
            utc_at_exposure.split(".")[1] if "." in utc_at_exposure else None,
        )
    elif "EXIF:GPSDateStamp" in m and "EXIF:GPSTimeStamp" in m:
        ts = _parse_gps_timestamp(m["EXIF:GPSDateStamp"], m["EXIF:GPSTimeStamp"])
    elif "EXIF:DateTimeOriginal" in m:
        ts = _parse_exif_datetime(
            m["EXIF:DateTimeOriginal"],
            m.get("EXIF:SubSecTimeOriginal"),
        )
    else:
        raise ValueError(f"No timestamp found in {filepath}")

    # GPS position
    lat = float(m.get("EXIF:GPSLatitude", 0.0))
    lon = float(m.get("EXIF:GPSLongitude", 0.0))
    alt = float(m.get("EXIF:GPSAltitude", 0.0))

    # Handle S/W hemispheres
    if m.get("EXIF:GPSLatitudeRef", "N") == "S":
        lat = -lat
    if m.get("EXIF:GPSLongitudeRef", "E") == "W":
        lon = -lon

    # DJI RTK quality from XMP
    rtk_std_lon = _safe_float(m.get("XMP:RtkStdLon"))
    rtk_std_lat = _safe_float(m.get("XMP:RtkStdLat"))
    rtk_std_hgt = _safe_float(m.get("XMP:RtkStdHgt"))
    rtk_flag = m.get("XMP:RtkFlag") or m.get("XMP:GpsStatus")

    return ImageMetadata(
        filename=Path(filepath).name,
        timestamp_utc=ts,
        latitude=lat,
        longitude=lon,
        altitude_msl=alt,
        rtk_std_lon=rtk_std_lon,
        rtk_std_lat=rtk_std_lat,
        rtk_std_hgt=rtk_std_hgt,
        rtk_flag=str(rtk_flag) if rtk_flag else None,
        image_width=int(m.get("EXIF:ImageWidth", m.get("File:ImageWidth", 0))),
        image_height=int(m.get("EXIF:ImageHeight", m.get("File:ImageHeight", 0))),
    )


def parse_image_directory(image_dir: Path) -> list[ImageMetadata]:
    """Parse all JPG images in a directory. Returns sorted by timestamp."""
    images = sorted(image_dir.glob("*.JPG")) + sorted(image_dir.glob("*.jpg"))
    if not images:
        raise FileNotFoundError(f"No JPG images found in {image_dir}")

    results = []
    with exiftool.ExifToolHelper() as et:
        for img_path in images:
            try:
                meta = parse_single_image(img_path, et)
                results.append(meta)
            except (ValueError, KeyError) as e:
                # Log and skip images with bad metadata
                print(f"Warning: skipping {img_path.name}: {e}")

    results.sort(key=lambda m: m.timestamp_utc)
    return results


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
