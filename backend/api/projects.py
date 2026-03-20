"""Project management API routes."""

from __future__ import annotations

import io
import logging
import shutil
import traceback
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from backend.config import settings
from backend.ingest.target_csv import load_targets
from backend.models.project import Project, ProjectStatus
from backend.services import project_service

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("/")
def list_projects() -> list[Project]:
    return project_service.list_projects()


@router.post("/", status_code=201)
def create_project(name: str = Form(...)) -> Project:
    return project_service.create_project(name)


@router.get("/{project_id}")
def get_project(project_id: str) -> Project:
    try:
        return project_service.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, f"Project {project_id} not found")


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str):
    project_service.delete_project(project_id)


@router.post("/{project_id}/upload-camera-track")
async def upload_camera_track(
    project_id: str,
    format: str = Form(..., description="'pix4d', 'pix4dmatic', or 'metashape'"),
    file: UploadFile = File(...),
    internal_file: UploadFile | None = File(None),
) -> Project:
    """Upload calibrated camera track file(s).

    For Metashape: upload the cameras.xml as ``file``.
    For Pix4DMapper: upload the external params (.txt) as ``file``
        and internal params (.cam) as ``internal_file``.
    For Pix4DMatic: upload the OPF export as a .zip containing the
        opf directory (calibrated_cameras.json, scene_reference_frame.json, etc.).
    """
    log.info("upload-camera-track: project=%s format=%s file=%s", project_id, format, file.filename)
    project = project_service.load_project(project_id)
    proj_dir = settings.data_dir / project_id

    try:
        if format == "metashape":
            dest = proj_dir / file.filename
            dest.write_bytes(await file.read())
            project.camera_track_file = file.filename
            log.info("Saved Metashape cameras file: %s (%d bytes)", dest, dest.stat().st_size)
        elif format == "pix4d":
            ext_dest = proj_dir / "external.txt"
            ext_dest.write_bytes(await file.read())
            if internal_file:
                int_dest = proj_dir / "internal.cam"
                int_dest.write_bytes(await internal_file.read())
                log.info("Saved Pix4DMapper external + internal params")
            else:
                log.info("Saved Pix4DMapper external params only (no internal file)")
            project.camera_track_file = "external.txt"
        elif format == "pix4dmatic":
            # OPF export — uploaded as a .zip of the opf directory
            data = await file.read()
            log.info("Received OPF zip: %d bytes", len(data))
            opf_dir = proj_dir / "opf"
            opf_dir.mkdir(exist_ok=True)
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    names = zf.namelist()
                    log.info("OPF zip contains %d entries: %s", len(names), names[:20])
                    zf.extractall(opf_dir)
            except zipfile.BadZipFile:
                raise HTTPException(400, "Pix4DMatic format requires a .zip of the OPF export directory")
            # Validate required files are present
            required = ["calibrated_cameras.json", "scene_reference_frame.json"]
            missing = [r for r in required if not list(opf_dir.rglob(r))]
            if missing:
                log.error("OPF zip is missing required files: %s", missing)
                raise HTTPException(422, f"OPF zip is missing required files: {missing}. "
                                    "Ensure 'Input cameras' and 'Calibration' are checked when exporting.")
            log.info("OPF extracted to: %s", opf_dir)
            project.camera_track_file = "opf"
        else:
            raise HTTPException(400, f"Unsupported format: {format}")

        project.camera_track_format = format
        project.status = ProjectStatus.INGESTED
        project_service.save_project(project)
        log.info("Camera track upload complete for project %s", project_id)
        return project

    except HTTPException:
        raise
    except Exception as exc:
        log.error("Camera track upload failed for project %s: %s\n%s", project_id, exc, traceback.format_exc())
        raise HTTPException(500, f"Camera track upload failed: {exc}") from exc


@router.post("/{project_id}/upload-targets")
async def upload_targets(
    project_id: str,
    file: UploadFile = File(...),
) -> Project:
    """Upload target coordinates CSV."""
    log.info("upload-targets: project=%s file=%s", project_id, file.filename)
    project = project_service.load_project(project_id)
    proj_dir = settings.data_dir / project_id

    try:
        dest = proj_dir / file.filename
        dest.write_bytes(await file.read())
        log.info("Saved target CSV: %s (%d bytes)", dest, dest.stat().st_size)
        project.target_file = file.filename

        targets = load_targets(dest)
        if not targets:
            raise ValueError("No valid targets found in CSV — check column names and data.")
        project.targets = targets
        project_service.save_project(project)
        log.info("Saved %d targets to project %s", len(targets), project_id)
        return project

    except HTTPException:
        raise
    except Exception as exc:
        log.error("Target CSV upload failed for project %s: %s\n%s", project_id, exc, traceback.format_exc())
        raise HTTPException(500, f"Target CSV upload failed: {exc}") from exc


@router.post("/{project_id}/upload-images")
async def upload_images(
    project_id: str,
    files: list[UploadFile] = File(...),
) -> dict:
    """Upload drone images to the project."""
    images_dir = project_service.get_images_dir(project_id)
    count = 0
    for f in files:
        dest = images_dir / f.filename
        dest.write_bytes(await f.read())
        count += 1

    project = project_service.load_project(project_id)
    project.image_dir = "images"
    project_service.save_project(project)

    return {"uploaded": count}


# ── Path-based (link) endpoints ───────────────────────────────────────────────

class LinkCameraRequest(BaseModel):
    path: str
    format: str = "pix4dmatic"


class LinkPathRequest(BaseModel):
    path: str


class LinkTargetsRequest(BaseModel):
    path: str
    layout: str = "auto"   # auto | swap_xy | penz | pnez | xyz | yxz
    epsg: str = ""         # EPSG code of the target CSV CRS (for validation)


@router.post("/{project_id}/link-camera-track")
def link_camera_track(project_id: str, req: LinkCameraRequest) -> Project:
    """Point the project at an existing camera track on disk (no upload)."""
    log.info("link-camera-track: project=%s format=%s path=%s", project_id, req.format, req.path)
    path = Path(req.path)

    try:
        if req.format == "pix4dmatic":
            if not path.is_dir():
                raise HTTPException(422, f"OPF path must be a directory: {req.path}")
            required = ["calibrated_cameras.json"]
            missing = [r for r in required if not list(path.rglob(r))]
            if missing:
                raise HTTPException(
                    422,
                    f"OPF directory is missing required files: {missing}. "
                    "Export from Pix4DMatic with 'Input cameras' and 'Calibration' checked.",
                )
            # Count cameras for logging
            import json as _json
            cal = next(path.rglob("calibrated_cameras.json"))
            n_cams = len(_json.loads(cal.read_text()).get("cameras", []))
            log.info("OPF validated: %d cameras found at %s", n_cams, path)

        elif req.format == "metashape":
            if not path.is_file():
                raise HTTPException(422, f"Metashape path must be a .xml file: {req.path}")

        elif req.format == "pix4d":
            if not path.is_file():
                raise HTTPException(422, f"Pix4DMapper path must be the external params .txt file: {req.path}")

        else:
            raise HTTPException(400, f"Unsupported format: {req.format}")

        project = project_service.load_project(project_id)
        project.camera_track_path = str(path)
        project.camera_track_format = req.format
        project.status = ProjectStatus.INGESTED
        project_service.save_project(project)
        log.info("Camera track linked for project %s", project_id)

        # If targets were imported before the camera track, re-check for X/Y swap
        if project.targets:
            _revalidate_target_swap(project)

        return project

    except HTTPException:
        raise
    except Exception as exc:
        log.error("link-camera-track failed: %s\n%s", exc, traceback.format_exc())
        raise HTTPException(500, f"Failed to link camera track: {exc}") from exc


@router.get("/{project_id}/crs-info")
def get_crs_info(project_id: str) -> dict:
    """Return the CRS name and EPSG extracted from the project's camera track."""
    project = project_service.load_project(project_id)
    if not project.camera_track_path and not project.camera_track_file:
        return {"name": None, "epsg": None, "epsg_vert": None}

    try:
        from backend.ingest.opf_parser import get_crs_info as _opf_crs
        if project.camera_track_format == "pix4dmatic":
            opf_dir = (
                Path(project.camera_track_path)
                if project.camera_track_path
                else (settings.data_dir / project_id / "opf")
            )
            return _opf_crs(opf_dir)
    except Exception as exc:
        log.warning("Could not read CRS info: %s", exc)

    # Metashape / Pix4DMapper — CRS not yet extracted automatically
    return {"name": "CRS info not available for this format", "epsg": None, "epsg_vert": None}


@router.post("/{project_id}/link-targets")
def link_targets(project_id: str, req: LinkTargetsRequest) -> dict:
    """Point the project at an existing target coordinates CSV on disk.

    Returns ``{"project": ..., "warning": str|null}``.
    If targets appear to have X/Y swapped relative to the camera coordinate
    system, they are silently corrected and a warning is returned.
    """
    log.info("link-targets: project=%s path=%s layout=%s epsg=%s",
             project_id, req.path, req.layout, req.epsg or "(none)")
    path = Path(req.path)
    warning: str | None = None

    try:
        if not path.is_file():
            raise HTTPException(422, f"Target CSV path does not exist or is not a file: {req.path}")

        targets = load_targets(path, layout=req.layout)
        if not targets:
            raise ValueError("No valid targets found in CSV — check column names and data.")

        project = project_service.load_project(project_id)

        # ── Coordinate sanity check against camera bounding box ──────────────
        # If cameras are loaded we can detect an X/Y swap in the target CSV.
        # Many surveying packages export Northing as "X" and Easting as "Y",
        # which is the opposite of photogrammetry software convention.
        cam_bbox = _get_camera_bbox(project)
        if cam_bbox:
            cx_min, cx_max, cy_min, cy_max = cam_bbox
            tx_vals = [t.x for t in targets]
            ty_vals = [t.y for t in targets]
            tx_min, tx_max = min(tx_vals), max(tx_vals)
            ty_min, ty_max = min(ty_vals), max(ty_vals)

            def _overlaps(a_min, a_max, b_min, b_max, tol=5000.0) -> bool:
                return a_min - tol <= b_max and b_min - tol <= a_max

            direct_ok = _overlaps(cx_min, cx_max, tx_min, tx_max) and \
                        _overlaps(cy_min, cy_max, ty_min, ty_max)
            swapped_ok = _overlaps(cx_min, cx_max, ty_min, ty_max) and \
                         _overlaps(cy_min, cy_max, tx_min, tx_max)

            if not direct_ok and swapped_ok:
                log.warning(
                    "Target X/Y appear swapped vs camera CRS — auto-correcting "
                    "(target X range %.0f–%.0f, camera X range %.0f–%.0f)",
                    tx_min, tx_max, cx_min, cx_max,
                )
                from backend.models.project import Target as _Target
                targets = [
                    _Target(id=t.id, label=t.label, x=t.y, y=t.x, z=t.z)
                    for t in targets
                ]
                warning = (
                    "Target CSV X/Y axes were swapped relative to the camera "
                    "coordinate system (e.g. Northing exported as X). "
                    "Coordinates have been automatically corrected."
                )
            elif not direct_ok and not swapped_ok:
                log.warning(
                    "Target coordinates do not overlap camera bounding box "
                    "even after swap — possible wrong CRS. "
                    "Camera X: %.0f–%.0f  Y: %.0f–%.0f | "
                    "Target X: %.0f–%.0f  Y: %.0f–%.0f",
                    cx_min, cx_max, cy_min, cy_max,
                    tx_min, tx_max, ty_min, ty_max,
                )
                warning = (
                    f"Warning: target coordinates (X {tx_min:.0f}–{tx_max:.0f}, "
                    f"Y {ty_min:.0f}–{ty_max:.0f}) do not overlap the camera "
                    f"bounding box (X {cx_min:.0f}–{cx_max:.0f}, "
                    f"Y {cy_min:.0f}–{cy_max:.0f}). "
                    "Check that both use the same coordinate reference system."
                )

        # ── EPSG mismatch check ──────────────────────────────────────────────
        # If the user specified an EPSG for the CSV, compare it against the
        # camera track CRS (OPF only for now).
        if req.epsg.strip():
            try:
                from backend.ingest.opf_parser import get_crs_info as _opf_crs
                if project.camera_track_format == "pix4dmatic":
                    opf_dir = (
                        Path(project.camera_track_path)
                        if project.camera_track_path
                        else (settings.data_dir / project_id / "opf")
                    )
                    crs = _opf_crs(opf_dir)
                    cam_epsg = crs.get("epsg") or ""
                    user_epsg = req.epsg.strip().lstrip("EPSG:").lstrip("epsg:")
                    if cam_epsg and cam_epsg != user_epsg:
                        epsg_warn = (
                            f"CRS mismatch: camera track is EPSG:{cam_epsg} "
                            f"but target CSV EPSG:{user_epsg} was specified. "
                            "Heights will be incorrect unless both use the same CRS."
                        )
                        log.warning(epsg_warn)
                        warning = (warning + "\n" + epsg_warn) if warning else epsg_warn
                    elif cam_epsg == user_epsg:
                        log.info("CRS match confirmed: EPSG:%s", cam_epsg)
            except Exception as e:
                log.debug("EPSG comparison skipped: %s", e)

        project.target_csv = str(path)
        project.targets = targets
        project_service.save_project(project)
        log.info("Linked %d targets from %s%s", len(targets), path,
                 " (with XY swap correction)" if warning and "swapped" in warning else "")
        return {"project": project.model_dump(), "warning": warning}

    except HTTPException:
        raise
    except Exception as exc:
        log.error("link-targets failed: %s\n%s", exc, traceback.format_exc())
        raise HTTPException(500, f"Failed to link targets: {exc}") from exc


def _get_camera_bbox(project) -> tuple[float, float, float, float] | None:
    """Return (x_min, x_max, y_min, y_max) of all camera positions, or None."""
    try:
        from backend.services.measurement_service import _load_cameras
        cameras = _load_cameras(project)
        if not cameras:
            return None
        xs = [c.extrinsics.x for c in cameras.values()]
        ys = [c.extrinsics.y for c in cameras.values()]
        return min(xs), max(xs), min(ys), max(ys)
    except Exception as e:
        log.debug("Could not load cameras for bbox check: %s", e)
        return None


def _revalidate_target_swap(project: Project) -> None:
    """Re-check existing targets for X/Y swap against the camera bounding box.

    Called when the camera track is linked AFTER targets were already imported
    (so the original link-targets check ran without cameras).
    """
    cam_bbox = _get_camera_bbox(project)
    if cam_bbox is None:
        return

    cx_min, cx_max, cy_min, cy_max = cam_bbox
    tx_vals = [t.x for t in project.targets]
    ty_vals = [t.y for t in project.targets]
    tx_min, tx_max = min(tx_vals), max(tx_vals)
    ty_min, ty_max = min(ty_vals), max(ty_vals)

    def _overlaps(a_min, a_max, b_min, b_max, tol=5000.0) -> bool:
        return a_min - tol <= b_max and b_min - tol <= a_max

    direct_ok = (_overlaps(cx_min, cx_max, tx_min, tx_max) and
                 _overlaps(cy_min, cy_max, ty_min, ty_max))

    if direct_ok:
        return  # Coordinates match, nothing to do

    swapped_ok = (_overlaps(cx_min, cx_max, ty_min, ty_max) and
                  _overlaps(cy_min, cy_max, tx_min, tx_max))

    if swapped_ok:
        log.warning(
            "Post-camera-track check: target X/Y appear swapped vs cameras. "
            "Auto-correcting %d targets. "
            "(Target X: %.0f–%.0f, Camera X: %.0f–%.0f)",
            len(project.targets), tx_min, tx_max, cx_min, cx_max,
        )
        from backend.models.project import Target as _Target
        project.targets = [
            _Target(id=t.id, label=t.label, x=t.y, y=t.x, z=t.z)
            for t in project.targets
        ]
        project_service.save_project(project)
    else:
        log.warning(
            "Post-camera-track check: targets do not overlap cameras even after swap. "
            "Camera X: %.0f–%.0f  Y: %.0f–%.0f | "
            "Target X: %.0f–%.0f  Y: %.0f–%.0f",
            cx_min, cx_max, cy_min, cy_max,
            tx_min, tx_max, ty_min, ty_max,
        )


@router.post("/{project_id}/link-images")
def link_images(project_id: str, req: LinkPathRequest) -> dict:
    """Point the project at an existing images folder on disk."""
    log.info("link-images: project=%s path=%s", project_id, req.path)
    path = Path(req.path)

    try:
        if not path.is_dir():
            raise HTTPException(422, f"Images path does not exist or is not a directory: {req.path}")

        img_exts = {".jpg", ".jpeg", ".tif", ".tiff", ".png"}
        image_files = [f for f in path.iterdir() if f.suffix.lower() in img_exts]
        count = len(image_files)
        log.info("Images directory contains %d image files", count)

        project = project_service.load_project(project_id)
        project.image_dir = str(path)
        project_service.save_project(project)
        return {"count": count, "project": project.model_dump()}

    except HTTPException:
        raise
    except Exception as exc:
        log.error("link-images failed: %s\n%s", exc, traceback.format_exc())
        raise HTTPException(500, f"Failed to link images: {exc}") from exc


@router.post("/{project_id}/link-dtm")
def link_dtm(project_id: str, req: LinkPathRequest) -> Project:
    """Point the project at a GeoTIFF DTM (bare earth) for ground elevation lookup."""
    log.info("link-dtm: project=%s path=%s", project_id, req.path)
    path = Path(req.path)

    try:
        if not path.exists():
            raise HTTPException(422, f"DTM file not found: {req.path}")
        if path.suffix.lower() not in (".tif", ".tiff"):
            raise HTTPException(422, "DTM must be a GeoTIFF (.tif / .tiff)")

        # Validate the file is a readable GeoTIFF with coordinate info
        from backend.ingest.dtm_loader import load_dtm
        dtm = load_dtm(path)
        log.info(
            "DTM validated: %d×%d pixels  origin=(%.2f, %.2f)",
            dtm.data.shape[1], dtm.data.shape[0], dtm.x0, dtm.y0,
        )

        project = project_service.load_project(project_id)
        project.dtm_path = str(path)
        project_service.save_project(project)
        return project

    except HTTPException:
        raise
    except Exception as exc:
        log.error("link-dtm failed: %s\n%s", exc, traceback.format_exc())
        raise HTTPException(500, f"Failed to link DTM: {exc}") from exc
