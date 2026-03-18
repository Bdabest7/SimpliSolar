"""Tests for Pix4D parameter file parsing."""

from pathlib import Path
import tempfile

import pytest

from backend.ingest.pix4d_parser import parse_external_params, parse_internal_params


EXTERNAL_SAMPLE = """\
# imageName X Y Z Omega Phi Kappa
DJI_0001.JPG 567890.123 4512345.678 125.456 -0.5 1.2 89.3
DJI_0002.JPG 567895.456 4512340.321 125.789 -0.3 1.1 89.5
DJI_0003.JPG 567900.789 4512335.654 125.234 -0.6 1.3 89.1
"""

INTERNAL_SAMPLE = """\
4032.5 2736.0 1824.0 5472 3648
-0.08952 0.10815 -0.04237
0.00023 -0.00015
"""


class TestExternalParams:
    def test_parse_three_cameras(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(EXTERNAL_SAMPLE)
            f.flush()
            cameras = parse_external_params(Path(f.name))

        assert len(cameras) == 3
        assert "DJI_0001.JPG" in cameras
        cam = cameras["DJI_0001.JPG"]
        assert abs(cam.x - 567890.123) < 0.001
        assert abs(cam.omega - (-0.5)) < 0.001
        assert abs(cam.kappa - 89.3) < 0.001

    def test_skip_empty_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("\n\n# comment\n" + EXTERNAL_SAMPLE + "\n\n")
            f.flush()
            cameras = parse_external_params(Path(f.name))

        assert len(cameras) == 3


class TestInternalParams:
    def test_parse_params(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cam", delete=False) as f:
            f.write(INTERNAL_SAMPLE)
            f.flush()
            intrinsics = parse_internal_params(Path(f.name), 5472, 3648)

        assert abs(intrinsics.focal_length_px - 4032.5) < 0.01
        assert abs(intrinsics.cx - 2736.0) < 0.01
        assert abs(intrinsics.k1 - (-0.08952)) < 0.0001
        assert abs(intrinsics.p2 - (-0.00015)) < 0.0001
        assert intrinsics.image_width == 5472
