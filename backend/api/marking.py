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


class ResidualsResponse(BaseModel):
    marks: list[MarkResidual]

router = APIRouter(prefix="/api/projects/{project_id}/targets/{target_id}/marks", tags=["marking"])


@router.get("/")
def get_marks(project_id: str, target_id: str) -> MarkSet:
    """Get all marks for a target."""
    return _load_marks(project_id, target_id)


@router.post("/")
def add_mark(project_id: str, target_id: str, mark: ImageMark) -> MarkSet:
    """Add a single mark (base or tip) to a target."""
    mark_set = _load_marks(project_id, target_id)
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
    from backend.engine.camera_math import project_point

    mark_set = _load_marks(project_id, target_id)
    cameras = _load_cameras(project)

    result: list[MarkResidual] = []
    for mark_type_key, marks in [("base", mark_set.base_marks), ("tip", mark_set.tip_marks)]:
        point_3d = None
        if len(marks) >= 2:
            try:
                point_3d, _ = _triangulate(marks, cameras)
            except ValueError:
                pass

        for m in marks:
            reprojection_px: float | None = None
            if point_3d is not None:
                cam = cameras.get(m.image_name)
                projected_x: float | None = None
            projected_y: float | None = None
            if cam is not None:
                    proj = project_point(point_3d, cam)
                    if proj is not None:
                        projected_x = proj[0]
                        projected_y = proj[1]
                        dx = proj[0] - m.pixel_x
                        dy = proj[1] - m.pixel_y
                        reprojection_px = math.sqrt(dx * dx + dy * dy)
            result.append(MarkResidual(
                image_name=m.image_name,
                mark_type=mark_type_key,
                pixel_x=m.pixel_x,
                pixel_y=m.pixel_y,
                reprojection_px=reprojection_px,
                projected_x=projected_x,
                projected_y=projected_y,
            ))

    return ResidualsResponse(marks=result)
