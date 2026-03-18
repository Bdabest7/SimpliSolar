"""GeoTIFF DSM (Digital Surface Model) reader.

Provides a lightweight loader for north-up GeoTIFF rasters without
requiring GDAL or rasterio.  Uses tifffile for raster IO and parses the
standard GeoTIFF ModelPixelScaleTag + ModelTiepointTag for the affine
coordinate transform.

The DSM must be in the same projected CRS as the camera track (e.g.
EPSG:6575 Tennessee State Plane) so that world XY coordinates can be
used to look up ground elevation directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import tifffile

log = logging.getLogger(__name__)

# GeoTIFF TIFF tag IDs
_PIXEL_SCALE_TAG = 33550   # ModelPixelScaleTag  → [sx, sy, sz]
_TIEPOINT_TAG    = 33922   # ModelTiepointTag    → [i, j, k, x, y, z, ...]
_TRANSFORM_TAG   = 34264   # ModelTransformationTag → 16-element 4×4 matrix


@dataclass
class DSMRaster:
    """Loaded DSM raster with coordinate transform."""

    data: np.ndarray   # 2-D array of elevations (rows × cols)
    x0: float          # world X at column 0  (left edge)
    y0: float          # world Y at row 0      (top/north edge)
    sx: float          # world units per column (positive)
    sy: float          # world units per row   (negative for north-up)
    nodata: float | None = None

    def lookup(self, x_world: float, y_world: float) -> float | None:
        """Return interpolated ground elevation at world (x, y), or None if OOB."""
        col_f = (x_world - self.x0) / self.sx
        row_f = (y_world - self.y0) / self.sy   # sy < 0, so this is correct

        r0, c0 = int(row_f), int(col_f)
        r1, c1 = r0 + 1, c0 + 1

        rows, cols = self.data.shape
        if not (0 <= r0 < rows and 0 <= c0 < cols):
            log.debug("DSM lookup (%.1f, %.1f) → pixel (%.1f, %.1f) out of bounds", x_world, y_world, col_f, row_f)
            return None

        # Bilinear interpolation between the four nearest pixels
        dr = row_f - r0
        dc = col_f - c0

        def _safe(r: int, c: int) -> float:
            if 0 <= r < rows and 0 <= c < cols:
                v = float(self.data[r, c])
                if self.nodata is not None and abs(v - self.nodata) < 1.0:
                    return float("nan")
                return v
            return float("nan")

        z00 = _safe(r0, c0)
        z01 = _safe(r0, c1)
        z10 = _safe(r1, c0)
        z11 = _safe(r1, c1)

        vals = [v for v in (z00, z01, z10, z11) if not np.isnan(v)]
        if not vals:
            return None

        # Fall back to nearest if any neighbour is nodata
        if len(vals) < 4:
            return min(vals, key=lambda v: abs(v - np.nanmean([z00, z01, z10, z11])))

        z = (z00 * (1 - dr) * (1 - dc) +
             z01 * (1 - dr) * dc +
             z10 * dr * (1 - dc) +
             z11 * dr * dc)
        return float(z)


def load_dsm(path: Path) -> DSMRaster:
    """Load a GeoTIFF DSM and return a DSMRaster ready for elevation queries.

    Supports the two most common GeoTIFF georeference encodings:
      - ModelPixelScaleTag + ModelTiepointTag  (most common)
      - ModelTransformationTag                 (affine, less common)

    Raises ValueError if the file lacks coordinate information.
    """
    path = Path(path)
    log.info("Loading DSM from: %s", path)

    with tifffile.TiffFile(str(path)) as tif:
        data = tif.asarray()

        # Collapse any extra dimensions (some DSMs are stored as 3D)
        while data.ndim > 2:
            data = data[0]

        page = tif.pages[0]
        tags = page.tags

        # Check for a nodata value in GDAL_METADATA or tifffile extras
        nodata: float | None = None
        if hasattr(tif, "geotiff_metadata"):
            nodata = tif.geotiff_metadata.get("NODATA")  # type: ignore[union-attr]

        # ── Method 1: ModelPixelScaleTag + ModelTiepointTag ──────────────────
        scale_tag = tags.get(_PIXEL_SCALE_TAG)
        tp_tag    = tags.get(_TIEPOINT_TAG)

        if scale_tag is not None and tp_tag is not None:
            sx, sy = float(scale_tag.value[0]), float(scale_tag.value[1])
            tp = tp_tag.value  # i, j, k, x, y, z  (first tiepoint)
            i_tp, j_tp = float(tp[0]), float(tp[1])
            x_tp, y_tp = float(tp[3]), float(tp[4])

            # Compute world coords of pixel (col=0, row=0)
            x0 = x_tp - i_tp * sx
            y0 = y_tp + j_tp * sy   # sy positive magnitude; row 0 is north

            log.info(
                "DSM: %d×%d pixels  origin=(%.2f, %.2f)  pixel=(%.4f, %.4f m)",
                data.shape[1], data.shape[0], x0, y0, sx, sy,
            )
            return DSMRaster(data=data, x0=x0, y0=y0, sx=sx, sy=-sy, nodata=nodata)

        # ── Method 2: ModelTransformationTag (4×4 affine matrix) ─────────────
        tf_tag = tags.get(_TRANSFORM_TAG)
        if tf_tag is not None:
            m = tf_tag.value  # 16 floats, row-major
            sx  =  float(m[0])
            sy  =  float(m[5])   # typically negative
            x0  =  float(m[3])
            y0  =  float(m[7])
            log.info(
                "DSM (transform tag): %d×%d pixels  origin=(%.2f, %.2f)  pixel=(%.4f, %.4f m)",
                data.shape[1], data.shape[0], x0, y0, sx, sy,
            )
            return DSMRaster(data=data, x0=x0, y0=y0, sx=sx, sy=sy, nodata=nodata)

    raise ValueError(
        f"DSM file '{path.name}' does not contain GeoTIFF coordinate tags "
        "(ModelPixelScaleTag/ModelTiepointTag or ModelTransformationTag). "
        "Re-export the DSM from your photogrammetry software with GeoTIFF georeferencing."
    )
