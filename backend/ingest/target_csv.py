"""Parser for the target coordinates CSV.

Supported layouts (``layout`` parameter)
-----------------------------------------
``auto``      Detect columns by name (case-insensitive).
              Recognises: id/point_id/point/name, x/easting/x_coord,
              y/northing/y_coord, z/elevation/z_coord, label/description.

``swap_xy``   Same name-based detection as ``auto``, then swap X ↔ Y.
              Use when column names look correct but axes are transposed.

``penz``      Positional — columns in order: ID, Easting(X), Northing(Y), Z.
              Standard photogrammetry export (e.g. Pix4D, most GIS tools).

``pnez``      Positional — columns in order: ID, Northing(Y), Easting(X), Z.
              Common surveying export (N before E).

``xyz``       Positional — columns in order: ID, X, Y, Z.
              Identical to ``penz``; included for recognition.

``yxz``       Positional — columns in order: ID, Y(Easting), X(Northing), Z.
              Some total-station exports swap X/Y labels.

All positional layouts require a header row (any column names are accepted;
only column *order* matters).  A Z column is always optional.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from backend.models.project import Target

log = logging.getLogger(__name__)

# Maps layout name → (easting_position, northing_position, z_position)
# Positions are 0-based *after* the ID column (position 0).
# None means "not present / optional".
_POSITIONAL_LAYOUTS: dict[str, tuple[int, int, int | None]] = {
    "penz": (1, 2, 3),   # ID, E(X), N(Y), Z
    "pnez": (2, 1, 3),   # ID, N(Y), E(X), Z   — swap E and N
    "xyz":  (1, 2, 3),   # ID, X, Y, Z          — same as penz
    "yxz":  (2, 1, 3),   # ID, Y, X, Z          — same as pnez
}


def load_targets(csv_path: Path, layout: str = "auto") -> list[Target]:
    """Load target coordinates from a CSV file.

    Parameters
    ----------
    csv_path : Path
    layout   : str
        One of ``auto``, ``swap_xy``, ``penz``, ``pnez``, ``xyz``, ``yxz``.
    """
    layout = layout.lower().strip()
    log.info("Loading targets from: %s  (layout=%s)", csv_path, layout)

    targets: list[Target] = []
    skipped = 0

    with open(csv_path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        raw_rows = list(reader)

    if not raw_rows:
        raise ValueError("Target CSV is empty")

    header = [h.strip() for h in raw_rows[0]]
    data_rows = raw_rows[1:]

    if layout in _POSITIONAL_LAYOUTS:
        targets, skipped = _parse_positional(header, data_rows, layout)
    else:
        # auto or swap_xy — name-based detection
        targets, skipped = _parse_by_name(header, data_rows)
        if layout == "swap_xy":
            log.info("Applying X↔Y swap as requested by layout=swap_xy")
            targets = [Target(id=t.id, label=t.label, x=t.y, y=t.x, z=t.z)
                       for t in targets]

    log.info(
        "Loaded %d target(s) (%d skipped) from %s  layout=%s",
        len(targets), skipped, csv_path.name, layout,
    )
    return targets


# ── Internal parsers ──────────────────────────────────────────────────────────

def _parse_by_name(
    header: list[str],
    data_rows: list[list[str]],
) -> tuple[list[Target], int]:
    """Detect columns by their header names."""
    field_map = {h.lower(): i for i, h in enumerate(header)}
    log.debug("CSV columns (auto-detect): %s", header)

    id_idx   = (_idx(field_map, "id", "point_id", "point", "name", "point name"))
    x_idx    = (_idx(field_map, "x", "easting", "x_coord", "e"))
    y_idx    = (_idx(field_map, "y", "northing", "y_coord", "n"))
    z_idx    = (_idx(field_map, "z", "elevation", "z_coord", "elev", "h", "height"))
    label_idx= (_idx(field_map, "label", "description", "desc"))

    log.debug(
        "Column indices → id=%s  x=%s  y=%s  z=%s  label=%s",
        id_idx, x_idx, y_idx, z_idx, label_idx,
    )

    if id_idx is None or x_idx is None or y_idx is None:
        raise ValueError(
            f"Cannot find required columns (id, x/easting, y/northing) in CSV. "
            f"Headers found: {header}. "
            f"Try selecting a specific layout format."
        )

    return _build_targets(data_rows, id_idx, x_idx, y_idx, z_idx, label_idx)


def _parse_positional(
    header: list[str],
    data_rows: list[list[str]],
    layout: str,
) -> tuple[list[Target], int]:
    """Parse using fixed column positions (header names are ignored)."""
    e_pos, n_pos, z_pos = _POSITIONAL_LAYOUTS[layout]
    log.info(
        "Positional layout '%s': ID=col0, Easting(X)=col%d, Northing(Y)=col%d, Z=col%s",
        layout, e_pos, n_pos, str(z_pos) if z_pos is not None else "none",
    )
    return _build_targets(
        data_rows,
        id_idx=0,
        x_idx=e_pos,
        y_idx=n_pos,
        z_idx=z_pos,
        label_idx=None,
    )


def _build_targets(
    data_rows: list[list[str]],
    id_idx: int,
    x_idx: int,
    y_idx: int,
    z_idx: int | None,
    label_idx: int | None,
) -> tuple[list[Target], int]:
    targets: list[Target] = []
    skipped = 0
    for row_num, row in enumerate(data_rows, start=2):
        if not any(c.strip() for c in row):
            continue  # skip blank rows
        try:
            z_val: float | None = None
            if z_idx is not None and z_idx < len(row) and row[z_idx].strip():
                z_val = float(row[z_idx])

            label = ""
            if label_idx is not None and label_idx < len(row):
                label = row[label_idx].strip()

            targets.append(Target(
                id=row[id_idx].strip(),
                label=label,
                x=float(row[x_idx]),
                y=float(row[y_idx]),
                z=z_val,
            ))
        except (ValueError, IndexError) as exc:
            log.warning(
                "Skipping row %d — %s | row: %s", row_num, exc,
                row[:6],  # limit log noise for wide rows
            )
            skipped += 1
    return targets, skipped


def _idx(field_map: dict[str, int], *names: str) -> int | None:
    """Return the column index for the first matching name, or None."""
    for name in names:
        if name in field_map:
            return field_map[name]
    return None
