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

        # Metashape camera frame: X-right, Y-down, Z-forward (matches ours).
        # R is already camera-to-world — store directly.
        extrinsics = CameraExtrinsics(
            x=float(t[0]), y=float(t[1]), z=float(t[2]),
            rotation=R.flatten().tolist(),
        )

        cameras[label] = CameraModel(
            image_name=label,
            intrinsics=intrinsics,
            extrinsics=extrinsics,
        )

    return cameras
