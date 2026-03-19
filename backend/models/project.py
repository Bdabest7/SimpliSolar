"""Project, target, and measurement data models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class ProjectStatus(str, Enum):
    CREATED = "created"
    INGESTED = "ingested"
    MARKING = "marking"
    COMPUTED = "computed"


class Target(BaseModel):
    """A target object to measure."""

    id: str
    label: str = ""
    x: float = Field(description="Approximate Easting")
    y: float = Field(description="Approximate Northing")
    z: float | None = Field(None, description="Known ground elevation (optional)")


class Measurement(BaseModel):
    """Computed height measurement for a target."""

    target_id: str
    base_x: float
    base_y: float
    base_z: float
    tip_x: float
    tip_y: float
    tip_z: float
    shadow_length_horizontal: float
    sun_altitude_deg: float
    sun_azimuth_deg: float
    computed_height: float
    confidence: float = Field(description="Combined triangulation residual in metres (legacy)")
    top_residual: float = Field(0.0, description="Object-top triangulation RMS residual in metres")
    tip_residual: float = Field(0.0, description="Shadow-tip triangulation RMS residual in metres (legacy, triangulation mode)")
    shadow_length_confidence: float = Field(
        0.0,
        description="Propagated XY uncertainty on shadow length in metres",
    )
    height_confidence: float = Field(
        0.0,
        description="Propagated height uncertainty in metres (legacy)",
    )
    # ── Per-image ray-to-ground fields ──────────────────────────────────────
    object_top_z: float = Field(0.0, description="Absolute Z of object top (the critical measurement)")
    object_top_z_spread: float = Field(0.0, description="Spread of per-image Object Top Z estimates (m)")
    tip_spread: float = Field(0.0, description="Scatter of per-image tip ground XY positions (m)")
    per_image_object_top_z: list[float] = Field(default_factory=list, description="Per-image Z estimates")
    n_tip_images: int = Field(0, description="Number of tip images contributing")
    method: str = Field("triangulation", description="Pipeline: 'triangulation' or 'ray_to_ground'")
    dtm_cell_size: float = Field(0.0, description="DTM pixel resolution in metres")
    timestamp_utc: str = Field(description="UTC timestamp used for sun calc")


class Project(BaseModel):
    """Top-level project state persisted as project.json."""

    id: str
    name: str
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    status: ProjectStatus = ProjectStatus.CREATED
    camera_track_format: str = "pix4dmatic"

    # Path-based configuration (preferred — files stay in place on disk)
    camera_track_path: str = ""  # abs path to OPF dir / cameras.xml / external.txt
    image_dir: str = ""          # abs path to images folder
    target_csv: str = ""         # abs path to target coordinates CSV
    dtm_path: str = ""           # abs path to GeoTIFF DTM (bare earth) for ground elevation lookup

    # Legacy upload-based fields (kept for backward compatibility)
    camera_track_file: str = ""
    target_file: str = ""

    targets: list[Target] = []
    measurements: list[Measurement] = []

    def project_dir(self, data_root: Path) -> Path:
        return data_root / self.id
