"""Models for user pixel-coordinate marks on images."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class MarkType(str, Enum):
    BASE = "base"
    TIP = "tip"


class ImageMark(BaseModel):
    """A single user click on an image."""

    image_name: str
    mark_type: MarkType
    pixel_x: float = Field(description="X pixel coordinate (column)")
    pixel_y: float = Field(description="Y pixel coordinate (row)")


class MarkSet(BaseModel):
    """All marks for a single target across multiple images."""

    target_id: str
    marks: list[ImageMark] = []

    @property
    def base_marks(self) -> list[ImageMark]:
        return [m for m in self.marks if m.mark_type == MarkType.BASE]

    @property
    def tip_marks(self) -> list[ImageMark]:
        return [m for m in self.marks if m.mark_type == MarkType.TIP]
