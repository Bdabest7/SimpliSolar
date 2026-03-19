"""Tests for height calculation from shadow vectors and sun angles."""

import math

import numpy as np
import pytest

from backend.engine.height_calc import compute_height, compute_height_multi_view


class TestComputeHeight:
    def test_45_degree_sun(self):
        """At 45° sun altitude, height should equal horizontal shadow length."""
        base = np.array([100.0, 200.0, 50.0])
        # Shadow 10m to the east
        tip = np.array([110.0, 200.0, 50.0])
        height = compute_height(base, tip, sun_altitude_deg=45.0)
        assert abs(height - 10.0) < 0.001

    def test_30_degree_sun(self):
        """At 30° sun altitude, height = shadow_length * tan(30°)."""
        base = np.array([0.0, 0.0, 0.0])
        tip = np.array([5.0, 0.0, 0.0])  # 5m shadow
        expected = 5.0 * math.tan(math.radians(30.0))
        height = compute_height(base, tip, sun_altitude_deg=30.0)
        assert abs(height - expected) < 0.001

    def test_terrain_slope_correction(self):
        """Height calc applies terrain slope correction from Z difference."""
        base = np.array([0.0, 0.0, 10.0])
        tip = np.array([5.0, 0.0, 8.0])  # 2m lower (sloping ground)
        # height = shadow_h * tan(45) + (z_tip - z_base) = 5 + (8-10) = 3
        height = compute_height(base, tip, sun_altitude_deg=45.0)
        assert abs(height - 3.0) < 0.001

    def test_negative_sun_raises(self):
        """Sun below horizon should raise ValueError."""
        with pytest.raises(ValueError, match="positive"):
            compute_height(
                np.array([0, 0, 0]),
                np.array([1, 0, 0]),
                sun_altitude_deg=-5.0,
            )

    def test_diagonal_shadow(self):
        """Shadow at an angle — horizontal length is sqrt(3² + 4²) = 5."""
        base = np.array([0.0, 0.0, 0.0])
        tip = np.array([3.0, 4.0, 0.0])
        height = compute_height(base, tip, sun_altitude_deg=45.0)
        assert abs(height - 5.0) < 0.001


class TestMultiViewHeight:
    def test_median_averaging(self):
        """Multiple estimates should produce a median result."""
        bases = [np.array([0, 0, 0])] * 5
        tips = [np.array([10, 0, 0])] * 5  # All the same
        median_h, spread = compute_height_multi_view(bases, tips, 45.0)
        assert abs(median_h - 10.0) < 0.001
        assert spread < 0.001

    def test_with_outlier(self):
        """Median should be robust to one outlier."""
        bases = [np.array([0, 0, 0])] * 5
        tips = [
            np.array([10, 0, 0]),
            np.array([10.01, 0, 0]),
            np.array([9.99, 0, 0]),
            np.array([10.005, 0, 0]),
            np.array([20, 0, 0]),  # outlier
        ]
        median_h, spread = compute_height_multi_view(bases, tips, 45.0)
        assert abs(median_h - 10.005) < 0.02  # Median ignores outlier
