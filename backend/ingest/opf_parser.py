"""Parser for Pix4DMatic OPF (Open Photogrammetry Format) exports.

Pix4DMatic exports calibrated cameras via: File > Export > Project as OPF.
This creates an ``opf/`` directory containing:

- ``project.opf``                  : index file referencing all items
- ``calibrated_cameras.json``      : calibrated extrinsics + sensor intrinsics
- ``scene_reference_frame.json``   : CRS definition + base-to-canonical transform
- ``input_cameras.json``           : maps camera IDs to filenames + image dims
- (optional) ``projected_input_cameras.json``, control points, point cloud, etc.

Required OPF export checkboxes in Pix4DMatic (v2.0.2)
------------------------------------------------------
When exporting via File > Export > Project as OPF, Pix4DMatic 2.0.2
presents these checkboxes:

1. **Input cameras** (+ Paths: Relative/Absolute)  — REQUIRED for us
2. **Images**                                       — not needed (we have originals)
3. **Tie points**                                   — not needed
4. **Calibration**                                  — REQUIRED for us
5. **Dense point cloud**                            — not needed

At minimum the user must check **Input cameras** and **Calibration**.
Use **Relative** paths for Input cameras.  The zip must contain:
- ``calibrated_cameras.json`` — calibrated extrinsics + sensor intrinsics
- ``scene_reference_frame.json`` — CRS and coordinate transform
- ``input_cameras.json`` — maps numeric camera IDs → image filenames

Coordinate system handling
--------------------------
Camera positions in ``calibrated_cameras.json`` are in the **canonical
(processing) CRS** — a right-handed, isometric frame shifted near the
origin for numerical stability.

The ``scene_reference_frame.json`` defines the **base CRS** (the
project's real-world CRS, e.g. EPSG:32618 / UTM 18N + EGM96 geoid)
and the transform between base and canonical:

    Forward  (base → canonical):  scale → swap_xy → + shift
    Inverse  (canonical → base):  - shift → unswap → / scale

We convert all positions back to the **base CRS** so they match the
user's target CSV coordinates, which MUST be in the same base CRS.

Orientation is Omega-Phi-Kappa in degrees.  The OPF spec defines the
rotation as Rx(ω)·Ry(φ)·Rz(κ) mapping from image frame to the
processing (canonical) CRS.  When ``swap_xy`` is True the canonical
X/Y axes are swapped relative to the base CRS, so we must also
transform the OPK angles when converting back to the base frame.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import numpy as np

from backend.models.camera import CameraExtrinsics, CameraIntrinsics, CameraModel

log = logging.getLogger(__name__)


def get_crs_info(opf_dir: Path) -> dict:
    """Return CRS name and EPSG codes extracted from scene_reference_frame.json.

    Returns a dict with:
      ``name``       — human-readable CRS name (e.g. "NAD83(2011) / Tennessee")
      ``epsg``       — primary projected/geographic EPSG code as a string, or None
      ``epsg_vert``  — vertical EPSG code as a string, or None
      ``wkt``        — raw WKT definition string
    """
    try:
        srf_path = _find_file(opf_dir, "scene_reference_frame.json")
        data = json.loads(srf_path.read_text())
        crs_obj = data.get("crs", {})
        wkt = crs_obj.get("definition", "") if isinstance(crs_obj, dict) else str(crs_obj)
    except FileNotFoundError:
        return {"name": "Unknown", "epsg": None, "epsg_vert": None, "wkt": ""}

    # Extract all ID["EPSG", NNNNN] occurrences
    all_ids = re.findall(r'ID\["EPSG",\s*(\d+)\]', wkt, re.IGNORECASE)

    # Primary CRS name — first quoted string after COMPOUNDCRS[, PROJCRS[, or GEOGCRS[
    name_match = re.search(r'(?:COMPOUND|PROJ|GEOG|ENGCRS)CRS\["([^"]+)"', wkt)
    name = name_match.group(1) if name_match else "Unknown"

    # Projected CRS EPSG — find ID immediately inside a PROJCRS block
    epsg: str | None = None
    projcrs_match = re.search(
        r'PROJCRS\[(?:[^[\]]|\[(?:[^[\]]|\[[^\[\]]*\])*\])*?ID\["EPSG",\s*(\d+)\]\s*\]',
        wkt, re.DOTALL
    )
    if projcrs_match:
        epsg = projcrs_match.group(1)
    elif all_ids:
        # Fallback: pick the last 4-5 digit ID (CRS-level codes vs parameter IDs)
        candidates = [i for i in all_ids if 1024 <= int(i) <= 99999]
        epsg = candidates[-1] if candidates else all_ids[-1]

    # Vertical CRS EPSG
    epsg_vert: str | None = None
    vertcrs_match = re.search(
        r'VERTCRS\[(?:[^[\]]|\[(?:[^[\]]|\[[^\[\]]*\])*\])*?ID\["EPSG",\s*(\d+)\]\s*\]',
        wkt, re.DOTALL
    )
    if vertcrs_match:
        epsg_vert = vertcrs_match.group(1)

    log.debug("CRS info: name=%r  epsg=%s  epsg_vert=%s", name, epsg, epsg_vert)
    return {"name": name, "epsg": epsg, "epsg_vert": epsg_vert, "wkt": wkt}


def _find_file(opf_dir: Path, name: str) -> Path:
    """Locate a file in the OPF directory tree (may be nested)."""
    candidates = list(opf_dir.rglob(name))
    if not candidates:
        raise FileNotFoundError(f"Cannot find '{name}' in {opf_dir}")
    log.debug("Found %s at: %s", name, candidates[0])
    return candidates[0]


def _load_scene_reference_frame(opf_dir: Path) -> dict:
    """Load and parse the scene reference frame transform.

    Returns a dict with keys:
    - shift  : ndarray (3,) — translation from canonical origin
    - scale  : ndarray (3,) — per-axis scaling
    - swap_xy: bool — True if base CRS is left-handed (X/Y swapped)
    - crs    : str — the base CRS definition (WKT or authority:code)
    """
    path = _find_file(opf_dir, "scene_reference_frame.json")
    data = json.loads(path.read_text())

    b2c = data.get("base_to_canonical", {})
    shift = np.array(b2c.get("shift", [0.0, 0.0, 0.0]))
    scale = np.array(b2c.get("scale", [1.0, 1.0, 1.0]))
    swap_xy = b2c.get("swap_xy", False)

    crs_def = ""
    crs_obj = data.get("crs", {})
    if isinstance(crs_obj, dict):
        crs_def = crs_obj.get("definition", "")
    elif isinstance(crs_obj, str):
        crs_def = crs_obj

    log.info(
        "Scene reference frame — CRS: %s | shift: %s | scale: %s | swap_xy: %s",
        crs_def or "(none)", shift.tolist(), scale.tolist(), swap_xy,
    )
    return {"shift": shift, "scale": scale, "swap_xy": swap_xy, "crs": crs_def}


def _canonical_to_base(
    pos_canonical: np.ndarray,
    shift: np.ndarray,
    scale: np.ndarray,
    swap_xy: bool,
) -> np.ndarray:
    """Convert a position from canonical (processing) CRS back to base CRS.

    The forward transform (base → canonical) is:
        1. Scale axes           →  pos_scaled  = base * scale
        2. Optionally swap X/Y  →  pos_swapped = [Y, X, Z] if swap_xy
        3. Add shift            →  canonical   = pos_swapped + shift

    So the inverse (canonical → base) is:
        1. Subtract shift       →  pos_unshifted = canonical - shift
        2. Optionally un-swap   →  pos_unswapped = [Y, X, Z] if swap_xy
        3. Divide by scale      →  base          = pos_unswapped / scale
    """
    pos = pos_canonical - shift

    if swap_xy:
        pos = np.array([pos[1], pos[0], pos[2]])

    pos = pos / scale
    return pos


def _canonical_opk_to_base(
    omega: float, phi: float, kappa: float,
    swap_xy: bool,
) -> tuple[float, float, float]:
    """Convert OPK angles from canonical frame back to base CRS frame.

    When swap_xy is False, canonical axes = base axes (just shifted),
    so OPK values are unchanged.

    When swap_xy is True, the canonical X came from base Y and vice versa.
    The rotation that was Rx(ω)·Ry(φ)·Rz(κ) in canonical frame becomes
    a rotation about swapped axes in the base frame.  For a pure XY swap
    (90° rotation about Z), the transformed angles are:
        ω_base = φ_canonical
        φ_base = ω_canonical
        κ_base = -κ_canonical
    """
    if not swap_xy:
        return omega, phi, kappa
    return phi, omega, -kappa


def _parse_sensor(sensor_data: dict, image_width: int = 0, image_height: int = 0) -> CameraIntrinsics:
    """Parse a sensor entry from calibrated_cameras.json into CameraIntrinsics."""
    internals = sensor_data.get("internals", {})

    # The OPF perspective model
    focal = internals.get("focal_length_px", 0.0)
    pp = internals.get("principal_point_px", [0.0, 0.0])
    radial = internals.get("radial_distortion", [0.0, 0.0, 0.0])
    tangential = internals.get("tangential_distortion", [0.0, 0.0])

    # Pad arrays if shorter than expected
    while len(radial) < 3:
        radial.append(0.0)
    while len(tangential) < 2:
        tangential.append(0.0)

    # OPF principal point is in pixels from the top-left corner
    return CameraIntrinsics(
        focal_length_px=focal,
        cx=pp[0],
        cy=pp[1],
        k1=radial[0],
        k2=radial[1],
        k3=radial[2],
        p1=tangential[0],
        p2=tangential[1],
        image_width=image_width,
        image_height=image_height,
    )


def load_opf_cameras(opf_dir: Path) -> dict[str, CameraModel]:
    """Load camera models from a Pix4DMatic OPF export directory.

    Parameters
    ----------
    opf_dir : Path
        Path to the OPF directory (the folder containing ``project.opf``
        or the files directly).

    Returns
    -------
    dict mapping image filename → CameraModel, with positions in the
    base CRS (the project's real-world coordinate system).
    """
    log.info("Loading OPF cameras from: %s", opf_dir)

    # List files present to help diagnose missing-file errors
    found_files = [p.name for p in opf_dir.rglob("*.json")]
    log.debug("OPF directory contains: %s", found_files)

    # Load scene reference frame for coordinate transform
    try:
        srf = _load_scene_reference_frame(opf_dir)
    except FileNotFoundError:
        log.warning("scene_reference_frame.json not found — assuming positions are already in world CRS")
        srf = {"shift": np.zeros(3), "scale": np.ones(3), "swap_xy": False, "crs": ""}

    # Load calibrated cameras
    cal_path = _find_file(opf_dir, "calibrated_cameras.json")
    cal_data = json.loads(cal_path.read_text())

    # Build sensor lookup from calibrated data
    sensors: dict[str, CameraIntrinsics] = {}
    for sensor in cal_data.get("sensors", []):
        sid = str(sensor.get("id", ""))
        sensors[sid] = _parse_sensor(sensor)
    log.info("Parsed %d sensor(s) from calibrated_cameras.json", len(sensors))

    # Load input cameras for image filenames and dimensions
    # (calibrated_cameras use numeric IDs; input_cameras have filenames)
    id_to_filename: dict[str, str] = {}
    image_dimensions: dict[str, tuple[int, int]] = {}
    try:
        input_path = _find_file(opf_dir, "input_cameras.json")
        input_data = json.loads(input_path.read_text())
        for cam in input_data.get("cameras", []):
            cid = str(cam.get("id", ""))
            uri = cam.get("uri", "")
            # URI is typically relative path like "images/DJI_0001.JPG"
            filename = Path(uri).name if uri else cid
            id_to_filename[cid] = filename

        # Sensor dimensions from input sensors
        for sensor in input_data.get("sensors", []):
            sid = str(sensor.get("id", ""))
            w = sensor.get("image_size_px", [0, 0])
            if isinstance(w, list) and len(w) >= 2:
                image_dimensions[sid] = (int(w[0]), int(w[1]))

        log.info(
            "Loaded %d filename mappings and %d image dimension entries from input_cameras.json",
            len(id_to_filename), len(image_dimensions),
        )
    except FileNotFoundError:
        log.warning("input_cameras.json not found — camera IDs will be used as filenames")

    # Also try projected_input_cameras.json for filenames as fallback
    if not id_to_filename:
        try:
            proj_path = _find_file(opf_dir, "projected_input_cameras.json")
            proj_data = json.loads(proj_path.read_text())
            for cam in proj_data.get("cameras", []):
                cid = str(cam.get("id", ""))
                uri = cam.get("uri", "")
                filename = Path(uri).name if uri else cid
                id_to_filename[cid] = filename
            log.info("Loaded %d filename mappings from projected_input_cameras.json (fallback)", len(id_to_filename))
        except FileNotFoundError:
            log.warning("projected_input_cameras.json not found — trying camera_list.json")

    # camera_list.json is Pix4DMatic's primary ID→filename index (always present)
    if not id_to_filename:
        try:
            cl_path = _find_file(opf_dir, "camera_list.json")
            cl_data = json.loads(cl_path.read_text())
            for cam in cl_data.get("cameras", []):
                cid = str(cam.get("id", ""))
                uri = cam.get("uri", "")
                filename = Path(uri).name if uri else cid
                id_to_filename[cid] = filename
            log.info("Loaded %d filename mappings from camera_list.json (fallback)", len(id_to_filename))
        except FileNotFoundError:
            log.warning("camera_list.json also not found — camera IDs will be used as filenames")

    # Parse cameras
    cameras: dict[str, CameraModel] = {}
    skipped_no_pos = 0
    skipped_no_sensor = 0
    calibrated_cam_list = cal_data.get("cameras", [])
    log.info("Processing %d camera entries from calibrated_cameras.json", len(calibrated_cam_list))

    for cam in calibrated_cam_list:
        cid = str(cam.get("id", ""))
        sensor_id = str(cam.get("sensor_id", ""))

        pos = cam.get("position")
        orient = cam.get("orientation_deg")
        if pos is None or orient is None:
            skipped_no_pos += 1
            continue  # Camera not calibrated

        # Convert canonical position → base CRS
        pos_canonical = np.array(pos)
        pos_base = _canonical_to_base(
            pos_canonical, srf["shift"], srf["scale"], srf["swap_xy"]
        )

        # Convert OPK from canonical frame → base CRS frame
        omega, phi, kappa = _canonical_opk_to_base(
            orient[0], orient[1], orient[2], srf["swap_xy"]
        )

        extrinsics = CameraExtrinsics(
            x=float(pos_base[0]),
            y=float(pos_base[1]),
            z=float(pos_base[2]),
            omega=omega,
            phi=phi,
            kappa=kappa,
        )

        # Get intrinsics (clone with correct image dimensions)
        intrinsics = sensors.get(sensor_id)
        if intrinsics is None:
            log.warning("Camera %s references unknown sensor_id=%s — skipping", cid, sensor_id)
            skipped_no_sensor += 1
            continue

        # Apply image dimensions if available
        dims = image_dimensions.get(sensor_id)
        if dims:
            intrinsics = intrinsics.model_copy(update={
                "image_width": dims[0],
                "image_height": dims[1],
            })

        # Resolve filename
        filename = id_to_filename.get(cid, cid)

        cameras[filename] = CameraModel(
            image_name=filename,
            intrinsics=intrinsics,
            extrinsics=extrinsics,
        )

    if skipped_no_pos:
        log.warning("Skipped %d uncalibrated cameras (no position/orientation)", skipped_no_pos)
    if skipped_no_sensor:
        log.warning("Skipped %d cameras with missing sensor reference", skipped_no_sensor)

    log.info("Successfully loaded %d camera models", len(cameras))

    if cameras:
        # Log a sample position for sanity-checking coordinates
        sample_name, sample_cam = next(iter(cameras.items()))
        e = sample_cam.extrinsics
        log.info(
            "Sample camera '%s' — position: (%.3f, %.3f, %.3f)  OPK: (%.4f, %.4f, %.4f)",
            sample_name, e.x, e.y, e.z, e.omega, e.phi, e.kappa,
        )

    return cameras
