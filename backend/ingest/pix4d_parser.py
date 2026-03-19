"""Parser for Pix4D calibrated camera parameters.

Reads two files exported from Pix4D after alignment:

1. External parameters (``*_calibrated_external_camera_parameters.txt``):
   - Space/tab-delimited, one line per image after a header.
   - Columns: imageName  X  Y  Z  Omega  Phi  Kappa

2. Internal parameters (``*_calibrated_internal_camera_parameters.cam``
   or ``*_pmatrix.txt``  — we support the .cam format):
   - Focal length in pixels, principal point, distortion coefficients.

Both are combined into our unified CameraModel.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from backend.models.camera import CameraExtrinsics, CameraIntrinsics, CameraModel


def _opk_to_c2w(omega_deg: float, phi_deg: float, kappa_deg: float) -> np.ndarray:
    """Build camera-to-world rotation from Pix4D OPK angles (degrees).

    Pix4D defines Rz(κ)·Ry(φ)·Rx(ω) as the world-to-camera rotation.
    Transpose gives camera-to-world.
    """
    o = np.radians(omega_deg)
    p = np.radians(phi_deg)
    k = np.radians(kappa_deg)

    Rx = np.array([
        [1, 0, 0],
        [0, np.cos(o), -np.sin(o)],
        [0, np.sin(o), np.cos(o)],
    ])
    Ry = np.array([
        [np.cos(p), 0, np.sin(p)],
        [0, 1, 0],
        [-np.sin(p), 0, np.cos(p)],
    ])
    Rz = np.array([
        [np.cos(k), -np.sin(k), 0],
        [np.sin(k), np.cos(k), 0],
        [0, 0, 1],
    ])

    R_w2c = Rz @ Ry @ Rx
    return R_w2c.T  # camera-to-world


def parse_external_params(filepath: Path) -> dict[str, CameraExtrinsics]:
    """Parse Pix4D calibrated external camera parameters file.

    Returns a dict mapping image filename → CameraExtrinsics.
    """
    cameras: dict[str, CameraExtrinsics] = {}

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments/headers
            if not line or line.startswith("#") or line.startswith("imageN"):
                continue

            parts = line.split()
            if len(parts) < 7:
                continue

            name = parts[0]
            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
            omega, phi, kappa = float(parts[4]), float(parts[5]), float(parts[6])

            R_c2w = _opk_to_c2w(omega, phi, kappa)
            cameras[name] = CameraExtrinsics(
                x=x, y=y, z=z,
                rotation=R_c2w.flatten().tolist(),
            )

    return cameras


def parse_internal_params(filepath: Path, image_width: int, image_height: int) -> CameraIntrinsics:
    """Parse Pix4D calibrated internal camera parameters (.cam) file.

    The .cam file format (Pix4D):
    Line 1: <focal_length_px>  <cx>  <cy>  <image_width>  <image_height>
    Line 2: <K1>  <K2>  <K3>
    Line 3: <P1>  <P2>

    Some variants list the focal length in mm with the sensor size on a
    separate line — we detect the format by checking if image dimensions
    appear on line 1.
    """
    with open(filepath, "r") as f:
        lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]

    if len(lines) < 3:
        raise ValueError(f"Expected >= 3 lines in internal params file, got {len(lines)}")

    # Line 1: focal, cx, cy [, width, height]
    parts1 = lines[0].split()
    focal = float(parts1[0])
    cx = float(parts1[1])
    cy = float(parts1[2])
    if len(parts1) >= 5:
        image_width = int(float(parts1[3]))
        image_height = int(float(parts1[4]))

    # Line 2: radial distortion
    parts2 = lines[1].split()
    k1 = float(parts2[0])
    k2 = float(parts2[1]) if len(parts2) > 1 else 0.0
    k3 = float(parts2[2]) if len(parts2) > 2 else 0.0

    # Line 3: tangential distortion
    parts3 = lines[2].split()
    p1 = float(parts3[0])
    p2 = float(parts3[1]) if len(parts3) > 1 else 0.0

    return CameraIntrinsics(
        focal_length_px=focal,
        cx=cx,
        cy=cy,
        k1=k1, k2=k2, k3=k3,
        p1=p1, p2=p2,
        image_width=image_width,
        image_height=image_height,
    )


def load_pix4d_cameras(
    external_file: Path,
    internal_file: Path,
    default_width: int = 5472,
    default_height: int = 3648,
) -> dict[str, CameraModel]:
    """Load a complete set of camera models from Pix4D exports.

    Returns dict mapping image filename → CameraModel.
    """
    intrinsics = parse_internal_params(internal_file, default_width, default_height)
    extrinsics_map = parse_external_params(external_file)

    cameras = {}
    for name, ext in extrinsics_map.items():
        cameras[name] = CameraModel(
            image_name=name,
            intrinsics=intrinsics,
            extrinsics=ext,
        )

    return cameras
