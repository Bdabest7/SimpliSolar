"""Marking API: submit and retrieve pixel-coordinate marks for targets."""

from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.models.marking import ImageMark, MarkSet
from backend.services.measurement_service import _load_marks, save_marks
from backend.services import project_service


class MarkResidual(BaseModel):
    image_name: str
    mark_type: str
    pixel_x: float
    pixel_y: float
    reprojection_px: float | None
    projected_x: float | None = None
    projected_y: float | None = None
    ground_deviation_m: float | None = None
    pixels_per_meter: float | None = None


class ResidualsResponse(BaseModel):
    marks: list[MarkResidual]

router = APIRouter(prefix="/api/projects/{project_id}/targets/{target_id}/marks", tags=["marking"])


@router.get("/")
def get_marks(project_id: str, target_id: str) -> MarkSet:
    """Get all marks for a target."""
    return _load_marks(project_id, target_id)


@router.post("/")
def add_mark(project_id: str, target_id: str, mark: ImageMark) -> MarkSet:
    """Add a single mark (base or tip) to a target.

    Enforces one mark per type per image: if a mark of the same type
    already exists for the same image, it is replaced.
    """
    mark_set = _load_marks(project_id, target_id)
    # Remove any existing mark of the same type on the same image
    mark_set.marks = [
        m for m in mark_set.marks
        if not (m.image_name == mark.image_name and m.mark_type == mark.mark_type)
    ]
    mark_set.marks.append(mark)
    save_marks(project_id, mark_set)

    # Update project status to marking
    project = project_service.load_project(project_id)
    from backend.models.project import ProjectStatus
    if project.status != ProjectStatus.MARKING:
        project.status = ProjectStatus.MARKING
        project_service.save_project(project)

    return mark_set


@router.put("/")
def replace_marks(project_id: str, target_id: str, mark_set: MarkSet) -> MarkSet:
    """Replace all marks for a target."""
    mark_set.target_id = target_id
    save_marks(project_id, mark_set)
    return mark_set


@router.delete("/last")
def undo_last_mark(project_id: str, target_id: str) -> MarkSet:
    """Remove the most recently added mark."""
    mark_set = _load_marks(project_id, target_id)
    if mark_set.marks:
        mark_set.marks.pop()
        save_marks(project_id, mark_set)
    return mark_set


@router.delete("/")
def clear_marks(project_id: str, target_id: str) -> MarkSet:
    """Clear all marks for a target."""
    mark_set = MarkSet(target_id=target_id)
    save_marks(project_id, mark_set)
    return mark_set


@router.get("/residuals")
def get_residuals(project_id: str, target_id: str) -> ResidualsResponse:
    """Triangulate current marks and return per-mark reprojection error in pixels.

    Uses project_point() to back-project the triangulated 3D point into each
    camera.  The distance between the re-projected pixel and the original mark
    is the reprojection error: small = well-constrained, large = uncertain.
    Returns reprojection_px=null for marks whose type has < 2 marks (cannot
    triangulate yet) or whose camera was not found in the track.
    """
    try:
        project = project_service.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")

    from backend.services.measurement_service import _load_cameras, _triangulate
    from backend.engine.camera_math import project_point, ray_to_ground

    mark_set = _load_marks(project_id, target_id)
    cameras = _load_cameras(project)

    # Load DTM if available (for per-image tip ground projection)
    dtm = None
    if project.dtm_path:
        try:
            from pathlib import Path
            from backend.ingest.dtm_loader import load_dtm
            dtm = load_dtm(Path(project.dtm_path))
        except Exception:
            pass

    result: list[MarkResidual] = []

    # ── Base marks: standard reprojection from triangulation ──────────────
    base_marks = mark_set.base_marks
    base_point_3d = None
    if len(base_marks) >= 2:
        try:
            base_point_3d, _ = _triangulate(base_marks, cameras)
        except ValueError:
            pass

    for m in base_marks:
        reprojection_px: float | None = None
        projected_x: float | None = None
        projected_y: float | None = None
        if base_point_3d is not None:
            cam = cameras.get(m.image_name)
            if cam is not None:
                proj = project_point(base_point_3d, cam)
                if proj is not None:
                    projected_x = proj[0]
                    projected_y = proj[1]
                    dx = proj[0] - m.pixel_x
                    dy = proj[1] - m.pixel_y
                    reprojection_px = math.sqrt(dx * dx + dy * dy)
        result.append(MarkResidual(
            image_name=m.image_name,
            mark_type="base",
            pixel_x=m.pixel_x,
            pixel_y=m.pixel_y,
            reprojection_px=reprojection_px,
            projected_x=projected_x,
            projected_y=projected_y,
        ))

    # ── Tip marks: per-image ray-to-ground (DTM) or triangulation ────────
    tip_marks = mark_set.tip_marks

    if dtm is not None and len(tip_marks) >= 1:
        # Project each tip to DTM ground, compute deviation from median
        import numpy as np
        ground_points: list[tuple[str, float, float, np.ndarray]] = []
        for m in tip_marks:
            cam = cameras.get(m.image_name)
            if cam is not None:
                pt = ray_to_ground(m.pixel_x, m.pixel_y, cam, dtm)
                if pt is not None:
                    ground_points.append((m.image_name, m.pixel_x, m.pixel_y, pt))

        # Compute median ground XY
        if ground_points:
            pts = np.array([gp[3] for gp in ground_points])
            median_xy = np.median(pts[:, :2], axis=0)

        for m in tip_marks:
            ground_dev: float | None = None
            ppm: float | None = None

            # Compute pixels_per_meter from camera geometry:
            # ppm = focal_length_px / altitude_above_ground
            cam = cameras.get(m.image_name)
            if cam is not None:
                ground_z_at_cam = dtm.lookup(cam.extrinsics.x, cam.extrinsics.y)
                if ground_z_at_cam is not None:
                    alt_above_ground = cam.extrinsics.z - ground_z_at_cam
                    if alt_above_ground > 1.0:
                        ppm = cam.intrinsics.focal_length_px / alt_above_ground

            # Find this mark's ground point
            for gp_name, gp_px, gp_py, gp_pt in ground_points:
                if (gp_name == m.image_name
                        and abs(gp_px - m.pixel_x) < 0.5
                        and abs(gp_py - m.pixel_y) < 0.5):
                    dx = gp_pt[0] - median_xy[0]
                    dy = gp_pt[1] - median_xy[1]
                    ground_dev = float(math.sqrt(dx * dx + dy * dy))
                    break
            result.append(MarkResidual(
                image_name=m.image_name,
                mark_type="tip",
                pixel_x=m.pixel_x,
                pixel_y=m.pixel_y,
                reprojection_px=None,
                ground_deviation_m=ground_dev,
                pixels_per_meter=ppm,
            ))
    else:
        # Fallback: triangulation-based reprojection for tips
        tip_point_3d = None
        if len(tip_marks) >= 2:
            try:
                tip_point_3d, _ = _triangulate(tip_marks, cameras)
            except ValueError:
                pass

        for m in tip_marks:
            reprojection_px = None
            projected_x = None
            projected_y = None
            if tip_point_3d is not None:
                cam = cameras.get(m.image_name)
                if cam is not None:
                    proj = project_point(tip_point_3d, cam)
                    if proj is not None:
                        projected_x = proj[0]
                        projected_y = proj[1]
                        dx = proj[0] - m.pixel_x
                        dy = proj[1] - m.pixel_y
                        reprojection_px = math.sqrt(dx * dx + dy * dy)
            result.append(MarkResidual(
                image_name=m.image_name,
                mark_type="tip",
                pixel_x=m.pixel_x,
                pixel_y=m.pixel_y,
                reprojection_px=reprojection_px,
                projected_x=projected_x,
                projected_y=projected_y,
            ))

    return ResidualsResponse(marks=result)
