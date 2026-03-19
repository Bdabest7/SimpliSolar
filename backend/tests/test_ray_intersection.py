"""Tests for multi-ray intersection.

Creates synthetic camera configurations and verifies that rays from
multiple cameras correctly triangulate to a known 3D point.
"""

import numpy as np
import pytest

from backend.engine.camera_math import pixel_to_ray, project_point
from backend.engine.ray_intersection import intersect_rays, intersect_rays_robust
from backend.models.camera import CameraExtrinsics, CameraIntrinsics, CameraModel


def _opk_to_c2w(omega_deg, phi_deg, kappa_deg):
    """Build camera-to-world rotation from OPK (Pix4D convention)."""
    o, p, k = np.radians(omega_deg), np.radians(phi_deg), np.radians(kappa_deg)
    Rx = np.array([[1,0,0],[0,np.cos(o),-np.sin(o)],[0,np.sin(o),np.cos(o)]])
    Ry = np.array([[np.cos(p),0,np.sin(p)],[0,1,0],[-np.sin(p),0,np.cos(p)]])
    Rz = np.array([[np.cos(k),-np.sin(k),0],[np.sin(k),np.cos(k),0],[0,0,1]])
    return (Rz @ Ry @ Rx).T


def _make_camera(x, y, z, omega=0.0, phi=0.0, kappa=0.0) -> CameraModel:
    R_c2w = _opk_to_c2w(omega, phi, kappa)
    return CameraModel(
        image_name=f"cam_{x}_{y}.jpg",
        intrinsics=CameraIntrinsics(
            focal_length_px=4000,
            cx=2736, cy=1824,
            image_width=5472, image_height=3648,
        ),
        extrinsics=CameraExtrinsics(
            x=x, y=y, z=z,
            rotation=R_c2w.flatten().tolist(),
        ),
    )


class TestIntersectRays:
    def test_two_cameras_nadir(self):
        """Two nadir cameras should triangulate a ground point accurately."""
        target = np.array([10.0, 15.0, 0.0])

        cam1 = _make_camera(5.0, 10.0, 80.0)
        cam2 = _make_camera(15.0, 20.0, 80.0)

        # Project target into both cameras
        uv1 = project_point(target, cam1)
        uv2 = project_point(target, cam2)
        assert uv1 is not None and uv2 is not None

        # Cast rays back
        o1, d1 = pixel_to_ray(uv1[0], uv1[1], cam1)
        o2, d2 = pixel_to_ray(uv2[0], uv2[1], cam2)

        # Intersect
        point, rms = intersect_rays([o1, o2], [d1, d2])

        np.testing.assert_array_almost_equal(point, target, decimal=2)
        assert rms < 0.01  # Sub-centimetre

    def test_three_cameras(self):
        """Three cameras should produce a better intersection."""
        target = np.array([20.0, 30.0, 5.0])

        cameras = [
            _make_camera(15.0, 25.0, 100.0),
            _make_camera(25.0, 25.0, 100.0),
            _make_camera(20.0, 35.0, 100.0),
        ]

        origins = []
        directions = []
        for cam in cameras:
            uv = project_point(target, cam)
            assert uv is not None
            o, d = pixel_to_ray(uv[0], uv[1], cam)
            origins.append(o)
            directions.append(d)

        point, rms = intersect_rays(origins, directions)
        np.testing.assert_array_almost_equal(point, target, decimal=2)
        assert rms < 0.005

    def test_raises_with_single_ray(self):
        """Should raise ValueError with fewer than 2 rays."""
        with pytest.raises(ValueError, match="at least 2"):
            intersect_rays(
                [np.array([0, 0, 100])],
                [np.array([0, 0, -1])],
            )


class TestRobustIntersection:
    def test_outlier_rejection(self):
        """Should reject one bad ray and still converge."""
        target = np.array([10.0, 10.0, 0.0])

        cameras = [
            _make_camera(5.0, 5.0, 80.0),
            _make_camera(15.0, 5.0, 80.0),
            _make_camera(10.0, 15.0, 80.0),
        ]

        origins = []
        directions = []
        for cam in cameras:
            uv = project_point(target, cam)
            assert uv is not None
            o, d = pixel_to_ray(uv[0], uv[1], cam)
            origins.append(o)
            directions.append(d)

        # Corrupt the third ray direction (point it sideways instead of down)
        directions[2] = np.array([0.9, 0.1, -0.1])
        directions[2] /= np.linalg.norm(directions[2])

        point, rms = intersect_rays_robust(origins, directions, max_residual=0.1)
        # Should still be close to target (the outlier was rejected)
        assert np.linalg.norm(point - target) < 0.5
