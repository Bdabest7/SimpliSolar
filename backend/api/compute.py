"""Computation API: trigger triangulation and height calculation."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.models.project import Measurement
from backend.services import project_service
from backend.services.measurement_service import run_measurement

router = APIRouter(prefix="/api/projects/{project_id}/targets/{target_id}", tags=["compute"])


class ComputeRequest(BaseModel):
    """Parameters for height computation.

    capture_time_utc / latitude / longitude are optional — the backend reads
    them from the tip-image EXIF automatically.  Supply them only as a fallback
    when EXIF reading fails (e.g. images lack GPS data).
    """
    capture_time_utc: datetime | None = None
    latitude: float | None = None
    longitude: float | None = None


@router.post("/compute")
def compute_height(
    project_id: str,
    target_id: str,
    request: ComputeRequest,
) -> Measurement:
    """Run the full measurement pipeline for a target.

    Requires marks to be placed first. The capture_time_utc, latitude,
    and longitude should come from the EXIF data of the most central
    image for this target.
    """
    try:
        project = project_service.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, f"Project {project_id} not found")

    target = next((t for t in project.targets if t.id == target_id), None)
    if target is None:
        raise HTTPException(404, f"Target {target_id} not found")

    try:
        measurement = run_measurement(
            project=project,
            target_id=target_id,
            capture_time_utc=request.capture_time_utc,
            latitude=request.latitude,
            longitude=request.longitude,
        )
        # Update project with measurement
        existing = [m for m in project.measurements if m.target_id != target_id]
        existing.append(measurement)
        project.measurements = existing
        from backend.services.project_service import save_project
        save_project(project)
    except ValueError as e:
        raise HTTPException(400, str(e))

    return measurement
