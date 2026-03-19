"""Tests for camera math: projection, undistortion, and ray construction.

Uses a synthetic camera with known parameters to verify round-trip
accuracy (project 3D point → pixel → ray → intersect back to 3D point).
"""

import numpy as np
import pytest

from backend.engine.camera_math import pixel_to_ray, project_point, undistort_pixel
from backend.models.camera import CameraExtrinsics, CameraIntrinsics, CameraModel


def _opk_to_c2w(omega_deg, phi_deg, kappa_deg):
    """Build camera-to-world rotation from OPK (Pix4D convention)."""
    o, p, k = np.radians(omega_deg), np.radians(phi_deg), np.radians(kappa_deg)
    Rx = np.array([[1,0,0],[0,np.cos(o),-np.sin(o)],[0,np.sin(o),np.cos(o)]])
    Ry = np.array([[np.cos(p),0,np.sin(p)],[0,1,0],[-np.sin(p),0,np.cos(p)]])
    Rz = np.array([[np.cos(k),-np.sin(k),0],[np.sin(k),np.cos(k),0],[0,0,1]])
    return (Rz @ Ry @ Rx).T


def _make_camera(
    x=0.0, y=0.0, z=100.0,
    omega=0.0, phi=0.0, kappa=0.0,
    focal=4000.0, width=5472, height=3648,
) -> CameraModel:
    """Create a synthetic camera model (nadir-looking by default)."""
    R_c2w = _opk_to_c2w(omega, phi, kappa)
    return CameraModel(
        image_name="test.jpg",
        intrinsics=CameraIntrinsics(
            focal_length_px=focal,
            cx=width / 2.0,
            cy=height / 2.0,
            k1=0.0, k2=0.0, k3=0.0,
            p1=0.0, p2=0.0,
            image_width=width,
            image_height=height,
        ),
        extrinsics=CameraExtrinsics(
            x=x, y=y, z=z,
            rotation=R_c2w.flatten().tolist(),
        ),
    )


class TestProjection:
    """Test forward projection (3D → pixel)."""

    def test_project_centre(self):
        """A point directly below a nadir camera should project to image centre."""
        cam = _make_camera(x=100.0, y=200.0, z=50.0)
        result = project_point(np.array([100.0, 200.0, 0.0]), cam)
        assert result is not None
        u, v = result
        assert abs(u - cam.intrinsics.cx) < 0.01
        assert abs(v - cam.intrinsics.cy) < 0.01

    def test_project_behind_camera(self):
        """A point behind the camera should return None."""
        cam = _make_camera(z=50.0)
        result = project_point(np.array([0.0, 0.0, 100.0]), cam)
        assert result is None

    def test_project_off_image(self):
        """A point far off to the side should return None (out of bounds)."""
        cam = _make_camera(z=50.0)
        result = project_point(np.array([1000.0, 1000.0, 0.0]), cam)
        assert result is None


class TestRayConstruction:
    """Test pixel → ray and verify ray direction."""

    def test_centre_ray_nadir(self):
        """Ray from image centre of nadir camera should point straight down."""
        cam = _make_camera(z=100.0)
        origin, direction = pixel_to_ray(
            cam.intrinsics.cx, cam.intrinsics.cy, cam
        )
        np.testing.assert_array_almost_equal(origin, [0, 0, 100])
        # Direction should be approximately [0, 0, -1] (into scene = down)
        assert direction[2] < -0.99  # Strongly downward

    def test_round_trip(self):
        """Project a 3D point, then cast a ray back — should recover the 3D point."""
        cam = _make_camera(x=50.0, y=50.0, z=80.0)
        target = np.array([55.0, 53.0, 0.0])

        # Forward project
        result = project_point(target, cam)
        assert result is not None
        u, v = result

        # Back-project to ray
        origin, direction = pixel_to_ray(u, v, cam)

        # The ray should pass through (or very near) the target point.
        # Parametric: P = origin + t * direction
        # Solve for t when z = 0: t = -origin[2] / direction[2]
        t = (target[2] - origin[2]) / direction[2]
        recovered = origin + t * direction

        np.testing.assert_array_almost_equal(recovered, target, decimal=3)


class TestUndistortion:
    """Test that undistortion inverts the distortion model."""

    def test_identity_no_distortion(self):
        """With zero distortion, undistorted = normalised input."""
        intrinsics = CameraIntrinsics(
            focal_length_px=4000, cx=2736, cy=1824,
            image_width=5472, image_height=3648,
        )
        # A pixel offset from centre
        u, v = 3000.0, 2000.0
        x_u, y_u = undistort_pixel(u, v, intrinsics)
        expected_x = (u - intrinsics.cx) / intrinsics.focal_length_px
        expected_y = (v - intrinsics.cy) / intrinsics.focal_length_px
        assert abs(x_u - expected_x) < 1e-10
        assert abs(y_u - expected_y) < 1e-10

    def test_with_distortion_converges(self):
        """With moderate distortion, undistortion should still converge."""
        intrinsics = CameraIntrinsics(
            focal_length_px=4000, cx=2736, cy=1824,
            k1=-0.1, k2=0.01, k3=0.0,
            p1=0.001, p2=-0.001,
            image_width=5472, image_height=3648,
        )
        x_u, y_u = undistort_pixel(3000.0, 2000.0, intrinsics)
        # Just check it returns finite values (convergence check)
        assert np.isfinite(x_u)
        assert np.isfinite(y_u)
