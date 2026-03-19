"""Atmospheric parameters for solar refraction correction.

Provides temperature and pressure at the observer location for Skyfield's
atmospheric refraction model.  Tries Open-Meteo historical weather API
first (free, no key required), falls back to ISA (International Standard
Atmosphere) when offline or the API fails.

Refraction effect: ~34 arcminutes at the horizon, <1 arcminute above 45°.
For shadow-length photogrammetry the correction is typically millimetres
to low centimetres — small but systematic, so worth correcting.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache

log = logging.getLogger(__name__)


def isa_standard(elevation_m: float) -> tuple[float, float]:
    """ISA troposphere temperature (°C) and pressure (mbar) at elevation.

    International Standard Atmosphere below 11 km:
        T = 15.0 − 6.5 × (h / 1000)           [°C]
        P = 1013.25 × (1 − 0.0065h / 288.15)^5.2559  [mbar]
    """
    temp = 15.0 - 6.5 * (elevation_m / 1000.0)
    pres = 1013.25 * (1.0 - 0.0065 * elevation_m / 288.15) ** 5.2559
    return temp, pres


# ── Open-Meteo weather lookup ────────────────────────────────────────────────


@lru_cache(maxsize=32)
def _fetch_hourly_weather(
    lat_rounded: float,
    lon_rounded: float,
    date_str: str,
) -> dict | None:
    """Fetch hourly T/P from Open-Meteo for a single date.  Cached.

    Tries the archive endpoint first (historical data back to 1940),
    then the forecast endpoint (last ~7 days + forecast).
    """
    params = (
        f"latitude={lat_rounded}&longitude={lon_rounded}"
        f"&start_date={date_str}&end_date={date_str}"
        f"&hourly=temperature_2m,surface_pressure"
    )
    endpoints = [
        "https://archive-api.open-meteo.com/v1/archive",
        "https://api.open-meteo.com/v1/forecast",
    ]
    for base_url in endpoints:
        try:
            url = f"{base_url}?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "SimpliSolar/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            hourly = data.get("hourly")
            if hourly and hourly.get("temperature_2m"):
                return hourly
        except Exception as e:
            log.debug("Open-Meteo %s failed: %s", base_url, e)

    return None


def lookup_weather(
    latitude: float,
    longitude: float,
    utc_time: datetime,
) -> tuple[float, float] | None:
    """Look up historical temperature and pressure from Open-Meteo.

    Returns (temperature_C, pressure_mbar) interpolated to the exact
    time, or None if the API is unavailable.
    """
    date_str = utc_time.strftime("%Y-%m-%d")
    hourly = _fetch_hourly_weather(round(latitude, 2), round(longitude, 2), date_str)
    if hourly is None:
        return None

    temps = hourly.get("temperature_2m", [])
    pressures = hourly.get("surface_pressure", [])
    if not temps or not pressures:
        return None

    # Linear interpolation between bracketing hours
    hour_frac = utc_time.hour + utc_time.minute / 60.0 + utc_time.second / 3600.0
    idx = max(0, min(int(hour_frac), len(temps) - 2))
    frac = max(0.0, min(1.0, hour_frac - idx))

    t0 = temps[idx]
    t1 = temps[min(idx + 1, len(temps) - 1)]
    p0 = pressures[idx]
    p1 = pressures[min(idx + 1, len(pressures) - 1)]

    if any(v is None for v in (t0, t1, p0, p1)):
        return None

    temp = t0 + frac * (t1 - t0)
    pres = p0 + frac * (p1 - p0)
    return temp, pres


def get_refraction_params(
    latitude: float,
    longitude: float,
    elevation_m: float,
    utc_time: datetime,
) -> tuple[float, float]:
    """Get temperature and pressure for atmospheric refraction correction.

    Tries Open-Meteo historical weather API first (automatic, free).
    Falls back to ISA standard atmosphere on failure.

    Returns (temperature_C, pressure_mbar).
    """
    result = lookup_weather(latitude, longitude, utc_time)
    if result is not None:
        temp, pres = result
        log.info(
            "Refraction: Open-Meteo weather → %.1f°C, %.1f mbar "
            "(%.2f°N, %.2f°E, %s)",
            temp, pres, latitude, longitude,
            utc_time.strftime("%Y-%m-%d %H:%M UTC"),
        )
        return temp, pres

    temp, pres = isa_standard(elevation_m)
    log.info(
        "Refraction: ISA standard atmosphere at %.0f m → %.1f°C, %.1f mbar",
        elevation_m, temp, pres,
    )
    return temp, pres
