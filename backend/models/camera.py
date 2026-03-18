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
    """Camera pose in world coordinates."""

    x: float = Field(description="Camera X position (Easting)")
    y: float = Field(description="Camera Y position (Northing)")
    z: float = Field(description="Camera Z position (Altitude)")
    omega: float = Field(description="Rotation Omega in degrees")
    phi: float = Field(description="Rotation Phi in degrees")
    kappa: float = Field(description="Rotation Kappa in degrees")

    def rotation_matrix(self) -> np.ndarray:
        """Build 3x3 rotation matrix from Omega/Phi/Kappa (degrees).

        Uses photogrammetric convention: R = Rz(kappa) @ Ry(phi) @ Rx(omega).
        Returns the rotation from world to camera frame.
        """
        o = np.radians(self.omega)
        p = np.radians(self.phi)
        k = np.radians(self.kappa)

        Rx = np.array([
            [1, 0, 0],
            [0, np.cos(o), -np.sin(o)],
            [0, np.sin(o), np.cos(o)],
        ])
        Ry = np.array([
            [np.cos(p), 0, np.sin(p)],
            [0, 1, 0],
            [-np.sin(p), 0, np.cos(p)],
        ])
        Rz = np.array([
            [np.cos(k), -np.sin(k), 0],
            [np.sin(k), np.cos(k), 0],
            [0, 0, 1],
        ])
        return Rz @ Ry @ Rx

    def position(self) -> np.ndarray:
        """Camera position as [X, Y, Z] array."""
        return np.array([self.x, self.y, self.z])


class CameraModel(BaseModel):
    """Unified camera model combining intrinsics, extrinsics, and image identity."""

    image_name: str
    intrinsics: CameraIntrinsics
    extrinsics: CameraExtrinsics

    model_config = {"arbitrary_types_allowed": True}
