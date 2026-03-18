"""Camera projection math: undistortion, ray construction, and projection.

Coordinate conventions
----------------------
- World frame: right-handed, X=East, Y=North, Z=Up.
- Camera frame: X=right, Y=down, Z=forward (into scene).
- The extrinsics rotation matrix R transforms from *world* to *camera* frame.
  Camera position in world = extrinsics.position().
  direction_world = R^T @ direction_camera.
"""

from __future__ import annotations

import numpy as np

from backend.models.camera import CameraIntrinsics, CameraExtrinsics, CameraModel


def undistort_pixel(
    u: float,
    v: float,
    intrinsics: CameraIntrinsics,
    iterations: int = 10,
) -> tuple[float, float]:
    """Convert a distorted pixel coordinate to undistorted normalised coords.

    Uses iterative Newton-Raphson inversion of the Brown-Conrady model.

    Returns (x_undist, y_undist) in normalised camera coordinates
    (i.e. divided by focal length, centred on principal point).
    """
    # Observed (distorted) normalised coords
    x_d = (u - intrinsics.cx) / intrinsics.focal_length_px
    y_d = (v - intrinsics.cy) / intrinsics.focal_length_px

    # Initial guess: distorted = undistorted
    x_u = x_d
    y_u = y_d

    for _ in range(iterations):
        r2 = x_u * x_u + y_u * y_u
        r4 = r2 * r2
        r6 = r2 * r4
        k = intrinsics
        radial = 1.0 + k.k1 * r2 + k.k2 * r4 + k.k3 * r6
        dx = 2.0 * k.p1 * x_u * y_u + k.p2 * (r2 + 2.0 * x_u * x_u)
        dy = k.p1 * (r2 + 2.0 * y_u * y_u) + 2.0 * k.p2 * x_u * y_u
        x_u = (x_d - dx) / radial
        y_u = (y_d - dy) / radial

    return x_u, y_u


def pixel_to_ray(
    u: float,
    v: float,
    camera: CameraModel,
) -> tuple[np.ndarray, np.ndarray]:
    """Construct a 3D ray from a pixel coordinate through the camera.

    Returns
    -------
    origin : ndarray, shape (3,)
        Camera position in world coordinates.
    direction : ndarray, shape (3,)
        Unit direction vector in world coordinates.
    """
    x_u, y_u = undistort_pixel(u, v, camera.intrinsics)

    # Direction in camera frame: [x, y, -1] (photogrammetric convention: -Z = into scene)
    dir_cam = np.array([x_u, y_u, -1.0])
    dir_cam /= np.linalg.norm(dir_cam)

    # Rotation matrix: world-to-camera.  Transpose = camera-to-world.
    R = camera.extrinsics.rotation_matrix()
    dir_world = R.T @ dir_cam
    dir_world /= np.linalg.norm(dir_world)

    origin = camera.extrinsics.position()
    return origin, dir_world


def project_point(
    point_3d: np.ndarray,
    camera: CameraModel,
) -> tuple[float, float] | None:
    """Project a 3D world point into pixel coordinates.

    Returns None if the point is behind the camera.
    """
    R = camera.extrinsics.rotation_matrix()
    t = camera.extrinsics.position()

    # Transform to camera frame
    p_cam = R @ (point_3d - t)

    # Photogrammetric convention: camera Z points backward (away from scene).
    # Points IN FRONT of the camera (in the scene) have p_cam[2] < 0.
    if p_cam[2] >= 0:
        return None

    # Normalised coords: divide by positive depth (-p_cam[2])
    x_n = p_cam[0] / (-p_cam[2])
    y_n = p_cam[1] / (-p_cam[2])

    # Apply distortion (forward model)
    r2 = x_n * x_n + y_n * y_n
    r4 = r2 * r2
    r6 = r2 * r4
    k = camera.intrinsics
    radial = 1.0 + k.k1 * r2 + k.k2 * r4 + k.k3 * r6
    x_dist = x_n * radial + 2.0 * k.p1 * x_n * y_n + k.p2 * (r2 + 2.0 * x_n * x_n)
    y_dist = y_n * radial + k.p1 * (r2 + 2.0 * y_n * y_n) + 2.0 * k.p2 * x_n * y_n

    u = x_dist * k.focal_length_px + k.cx
    v = y_dist * k.focal_length_px + k.cy

    # Bounds check
    if 0 <= u < k.image_width and 0 <= v < k.image_height:
        return u, v
    return None
