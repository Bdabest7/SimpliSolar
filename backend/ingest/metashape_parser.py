"""Parser for Agisoft Metashape camera XML export.

Reads the ``cameras.xml`` file exported via:
  File → Export → Export Cameras…

The XML contains:
- ``<chunk><transform>`` : 4×4 affine from chunk local coords to world CRS
- ``<chunk><sensors><sensor>`` : intrinsic calibration per sensor
- ``<chunk><cameras><camera>`` : 4×4 transform from camera to chunk coords

We compose camera→chunk→world to get extrinsics in the project CRS.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from backend.models.camera import CameraExtrinsics, CameraIntrinsics, CameraModel


def _parse_4x4(text: str) -> np.ndarray:
    """Parse a space-delimited 4×4 matrix string into ndarray."""
    vals = [float(v) for v in text.strip().split()]
    if len(vals) != 16:
        raise ValueError(f"Expected 16 values for 4x4 matrix, got {len(vals)}")
    return np.array(vals).reshape(4, 4)


def _rotation_to_opk(R: np.ndarray) -> tuple[float, float, float]:
    """Extract Omega, Phi, Kappa (degrees) from a 3×3 rotation matrix.

    Uses the convention R = Rz(kappa) @ Ry(phi) @ Rx(omega).
    """
    phi = math.asin(np.clip(R[0, 2], -1.0, 1.0))

    if abs(math.cos(phi)) > 1e-6:
        omega = math.atan2(-R[1, 2], R[2, 2])
        kappa = math.atan2(-R[0, 1], R[0, 0])
    else:
        omega = math.atan2(R[1, 0], R[1, 1])
        kappa = 0.0

    return math.degrees(omega), math.degrees(phi), math.degrees(kappa)


def _parse_sensor(sensor_el: ET.Element) -> CameraIntrinsics:
    """Parse a <sensor> element into CameraIntrinsics."""
    cal = sensor_el.find("calibration")
    if cal is None:
        raise ValueError("Sensor element has no <calibration>")

    resolution = cal.find("resolution")
    width = int(resolution.get("width"))
    height = int(resolution.get("height"))

    def _val(tag: str, default: float = 0.0) -> float:
        el = cal.find(tag)
        return float(el.text) if el is not None else default

    f = _val("f")
    cx = _val("cx")
    cy = _val("cy")

    return CameraIntrinsics(
        focal_length_px=f,
        cx=width / 2.0 + cx,   # Metashape cx is offset from image centre
        cy=height / 2.0 + cy,
        k1=_val("k1"),
        k2=_val("k2"),
        k3=_val("k3"),
        p1=_val("p1"),
        p2=_val("p2"),
        image_width=width,
        image_height=height,
    )


def load_metashape_cameras(xml_path: Path) -> dict[str, CameraModel]:
    """Load camera models from a Metashape cameras.xml export.

    Returns dict mapping image filename → CameraModel.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    chunk = root.find("chunk")
    if chunk is None:
        raise ValueError("No <chunk> found in cameras.xml")

    # Chunk-to-world transform (may be identity if project is in local coords)
    chunk_transform_el = chunk.find("transform")
    if chunk_transform_el is not None and chunk_transform_el.text:
        T_chunk_to_world = _parse_4x4(chunk_transform_el.text)
    else:
        T_chunk_to_world = np.eye(4)

    # Parse sensors (intrinsics)
    sensors: dict[str, CameraIntrinsics] = {}
    sensors_el = chunk.find("sensors")
    if sensors_el is not None:
        for s in sensors_el.findall("sensor"):
            sid = s.get("id")
            sensors[sid] = _parse_sensor(s)

    # Parse cameras
    cameras: dict[str, CameraModel] = {}
    cameras_el = chunk.find("cameras")
    if cameras_el is None:
        return cameras

    for cam_el in cameras_el.findall("camera"):
        label = cam_el.get("label")
        sensor_id = cam_el.get("sensor_id", "0")
        transform_el = cam_el.find("transform")

        if transform_el is None or transform_el.text is None:
            continue  # Camera not aligned

        intrinsics = sensors.get(sensor_id)
        if intrinsics is None:
            continue

        # Camera-to-chunk transform
        T_cam_to_chunk = _parse_4x4(transform_el.text)

        # Full camera-to-world
        T_cam_to_world = T_chunk_to_world @ T_cam_to_chunk

        # Extract rotation and translation
        R = T_cam_to_world[:3, :3]
        t = T_cam_to_world[:3, 3]

        # Metashape camera frame: X-right, Y-down, Z-forward
        # Our convention matches, so R is world-to-camera = inverse of cam-to-world rotation
        # But the transform is cam_to_world, so we need its inverse for our extrinsics
        # Actually, position = t (translation column), R_w2c = R^T
        omega, phi, kappa = _rotation_to_opk(R.T)

        extrinsics = CameraExtrinsics(
            x=float(t[0]), y=float(t[1]), z=float(t[2]),
            omega=omega, phi=phi, kappa=kappa,
        )

        cameras[label] = CameraModel(
            image_name=label,
            intrinsics=intrinsics,
            extrinsics=extrinsics,
        )

    return cameras
