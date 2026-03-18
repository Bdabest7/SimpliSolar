"""Export record models for GCP/Checkpoint CSV output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GCPRecord(BaseModel):
    """A single ground control / checkpoint record."""

    label: str
    x: float = Field(description="Easting")
    y: float = Field(description="Northing")
    z: float = Field(description="Computed top-of-object elevation")
    horz_accuracy: float = Field(description="Horizontal accuracy estimate (m)")
    vert_accuracy: float = Field(description="Vertical accuracy estimate (m)")
