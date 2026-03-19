"""Camera models: intrinsics, extrinsics, and the unified CameraModel."""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field


class CameraIntrinsics(BaseModel):
    """Lens calibration parameters (Brown-Conrady distortion model)."""

    focal_length_px: float = Field(description="Focal length in pixels")
    cx: float = Field(description="Principal point X offset in pixels")
    cy: float = Field(description="Principal point Y offset in pixels")
    k1: float = Field(0.0, description="Radial distortion K1")
    k2: float = Field(0.0, description="Radial distortion K2")
    k3: float = Field(0.0, description="Radial distortion K3")
    p1: float = Field(0.0, description="Tangential distortion P1")
    p2: float = Field(0.0, description="Tangential distortion P2")
    image_width: int = Field(description="Image width in pixels")
    image_height: int = Field(description="Image height in pixels")


class CameraExtrinsics(BaseModel):
    """Camera pose in world coordinates.

    The rotation field stores a 3×3 camera-to-world rotation matrix in
    row-major order (9 floats).  Each parser is responsible for converting
    from its native convention (OPK angles, 4×4 transforms, etc.) into
    this single internal representation at import time.
    """

    x: float = Field(description="Camera X position (Easting)")
    y: float = Field(description="Camera Y position (Northing)")
    z: float = Field(description="Camera Z position (Altitude)")
    rotation: list[float] = Field(
        description="3×3 camera-to-world rotation matrix, row-major (9 floats)"
    )

    def rotation_matrix(self) -> np.ndarray:
        """Return the 3×3 camera-to-world rotation matrix."""
        return np.array(self.rotation).reshape(3, 3)

    def position(self) -> np.ndarray:
        """Camera position as [X, Y, Z] array."""
        return np.array([self.x, self.y, self.z])


class CameraModel(BaseModel):
    """Unified camera model combining intrinsics, extrinsics, and image identity."""

    image_name: str
    intrinsics: CameraIntrinsics
    extrinsics: CameraExtrinsics

    model_config = {"arbitrary_types_allowed": True}
