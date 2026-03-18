"""Solar ephemeris calculations using Skyfield.

Computes precise sun altitude and azimuth for a given UTC time and
geographic position.  This drives the final height calculation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from skyfield.api import load, wgs84
from skyfield.timelib import Time


@lru_cache(maxsize=1)
def _load_ephemeris():
    """Load the JPL ephemeris (cached across calls)."""
    ts = load.timescale()
    eph = load("de421.bsp")
    return ts, eph


def sun_position(
    utc_time: datetime,
    latitude: float,
    longitude: float,
    elevation_m: float = 0.0,
) -> tuple[float, float]:
    """Return sun (altitude_deg, azimuth_deg) for a location and time.

    Parameters
    ----------
    utc_time : datetime
        Must be timezone-aware (UTC).
    latitude : float
        WGS84 latitude in decimal degrees.
    longitude : float
        WGS84 longitude in decimal degrees.
    elevation_m : float
        Observer elevation above WGS84 ellipsoid in metres.

    Returns
    -------
    altitude_deg : float
        Sun elevation above horizon in degrees (0 = horizon, 90 = zenith).
    azimuth_deg : float
        Sun azimuth in degrees clockwise from north.
    """
    if utc_time.tzinfo is None:
        utc_time = utc_time.replace(tzinfo=timezone.utc)

    ts, eph = _load_ephemeris()
    earth = eph["earth"]
    sun = eph["sun"]

    observer = earth + wgs84.latlon(latitude, longitude, elevation_m)
    t = ts.from_datetime(utc_time)
    apparent = observer.at(t).observe(sun).apparent()
    alt, az, _ = apparent.altaz()

    return alt.degrees, az.degrees
