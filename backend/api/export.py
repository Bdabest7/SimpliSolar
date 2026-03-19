"""Export API: download GCP/checkpoint CSV files."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.models.export import GCPRecord
from backend.services import project_service

router = APIRouter(prefix="/api/projects/{project_id}", tags=["export"])


@router.get("/export")
def export_csv(project_id: str, format: str = "pix4d"):
    """Export measurements as a GCP/checkpoint CSV.

    Parameters
    ----------
    format : str
        'pix4d' or 'metashape'
    """
    try:
        project = project_service.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, f"Project {project_id} not found")

    if not project.measurements:
        raise HTTPException(400, "No measurements to export")

    records = []
    for m in project.measurements:
        # Use the explicit object_top_z when available (ray-to-ground pipeline),
        # fall back to base_z + computed_height for legacy measurements.
        top_z = m.object_top_z if m.object_top_z != 0.0 else (m.base_z + m.computed_height)
        # Horizontal accuracy: object top XY triangulation residual
        horz_acc = m.top_residual if m.top_residual > 0 else m.confidence
        # Vertical accuracy: per-image Object Top Z spread (ray_to_ground),
        # or legacy confidence for triangulation-mode measurements
        vert_acc = m.object_top_z_spread if m.object_top_z_spread > 0 else m.confidence
        records.append(GCPRecord(
            label=m.target_id,
            x=m.base_x,
            y=m.base_y,
            z=top_z,
            horz_accuracy=horz_acc,
            vert_accuracy=vert_acc,
        ))

    output = io.StringIO()
    writer = csv.writer(output)

    if format == "pix4d":
        # Pix4D: label, y (northing), x (easting), z, horz_acc, vert_acc
        writer.writerow(["label", "y", "x", "z", "horz_accuracy", "vert_accuracy"])
        for r in records:
            writer.writerow([r.label, r.y, r.x, r.z, r.horz_accuracy, r.vert_accuracy])
    elif format == "metashape":
        # Metashape: label, x, y, z, x_acc, y_acc, z_acc
        writer.writerow(["label", "x", "y", "z", "x_accuracy", "y_accuracy", "z_accuracy"])
        for r in records:
            writer.writerow([r.label, r.x, r.y, r.z, r.horz_accuracy, r.horz_accuracy, r.vert_accuracy])
    else:
        raise HTTPException(400, f"Unsupported export format: {format}")

    output.seek(0)
    filename = f"{project.name}_checkpoints_{format}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
