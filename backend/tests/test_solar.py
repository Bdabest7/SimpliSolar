"""Tests for solar ephemeris calculations.

Uses known sun positions to verify Skyfield integration.
"""

from datetime import datetime, timezone

import pytest

from backend.engine.solar import sun_position


class TestSunPosition:
    def test_returns_finite(self):
        """Basic sanity: should return finite altitude and azimuth."""
        dt = datetime(2024, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
        alt, az = sun_position(dt, latitude=40.0, longitude=-74.0)
        assert -90 <= alt <= 90
        assert 0 <= az <= 360

    def test_summer_solstice_noon_high_sun(self):
        """At summer solstice, noon at 40°N, sun should be high."""
        # June 21, ~17:00 UTC is ~noon EDT (40°N, 74°W)
        dt = datetime(2024, 6, 21, 17, 0, 0, tzinfo=timezone.utc)
        alt, az = sun_position(dt, latitude=40.0, longitude=-74.0)
        assert alt > 60  # Sun should be above 60°

    def test_night_negative_altitude(self):
        """At midnight, sun should be below horizon."""
        dt = datetime(2024, 6, 21, 4, 0, 0, tzinfo=timezone.utc)  # ~midnight EDT
        alt, az = sun_position(dt, latitude=40.0, longitude=-74.0)
        assert alt < 0

    def test_naive_datetime_handled(self):
        """Should handle naive datetime by assuming UTC."""
        dt = datetime(2024, 6, 21, 17, 0, 0)
        alt, az = sun_position(dt, latitude=40.0, longitude=-74.0)
        assert -90 <= alt <= 90
