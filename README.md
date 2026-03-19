# SimpliSolar

**Multi-view shadow engine for calculating object heights from DJI RTK drone imagery.**

SimpliSolar measures the height of objects (poles, trees, buildings) from drone photos by analysing their shadows. Instead of requiring a full 3D reconstruction, it uses the camera positions from a photogrammetry track, the sun's position at the time of capture, and a bare-earth terrain model to compute precise heights from shadow length.

The primary output is **ground control / checkpoint data** (Object Top Z, height above ground, and XY position) exportable in Pix4D and Metashape CSV formats.

---

## How It Works

1. **Import** a camera track (Pix4DMatic OPF, Pix4D params, or Metashape XML) and a DTM GeoTIFF
2. **Mark** the top of the object and the tip of its shadow across multiple drone images
3. **Compute** — the engine triangulates the object top in 3D, projects each shadow tip onto the DTM via ray-to-ground intersection, and calculates the object height from the shadow geometry and solar angle
4. **Export** the results as GCP/checkpoint CSV

### Measurement Pipeline

```
 Multi-view marks  ──►  Triangulate Object Top XY  ──►  Object Top Z
                                                            │
 Per-image tip marks ──►  Ray-to-ground (DTM)  ──►  Shadow length per image
                                                            │
 EXIF timestamp + GPS  ──►  Sun altitude (Skyfield)  ──────┘
                              + atmospheric refraction
                                (Open-Meteo weather)

 Object Top Z  =  shadow_length × tan(sun_altitude)  +  DTM(shadow_tip)
 Object Height =  Object Top Z  −  DTM(object_base)
```

### Key Features

- **Per-image sun altitude** from individual EXIF timestamps — accounts for sun movement between flight lines
- **Atmospheric refraction correction** — automatic weather lookup (Open-Meteo) or ISA standard atmosphere fallback
- **DTM terrain correction** — handles sloped ground between object and shadow tip
- **Multi-view averaging** — median + spread across all marked images for robust estimates
- **Residual diagnostics** — per-mark reprojection error and tip scatter for quality assessment
- **Camera-to-world rotation matrix** stored directly — no ambiguous OPK angle conventions

---

## Prerequisites

- **Python 3.11+**
- **Node.js 18+** (for the frontend dev server)
- **ExifTool** — [exiftool.org](https://exiftool.org/) (must be on PATH, or set `EXIFTOOL_PATH` in `.env`)

### Input Data

| Input | Description |
|-------|-------------|
| **Camera track** | Pix4DMatic `.opf` directory, Pix4D `external.txt` + `internal.cam`, or Metashape `.xml` |
| **DTM** | Bare-earth GeoTIFF (`.tif`) in the same CRS as the camera track |
| **Drone images** | Original JPGs with EXIF GPS + timestamp (DJI RTK recommended) |
| **Target CSV** | CSV with columns: `name`, `x`, `y`, `z` (known coordinates, optional) |

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/Bdabest7/SimpliSolar.git
cd SimpliSolar

# Python dependencies
pip install -e ".[dev]"

# Frontend dependencies
cd frontend
npm install
cd ..
```

### 2. Configure (optional)

Copy `.env.example` to `.env` and adjust if needed:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|----------|---------|-------------|
| `DATA_DIR` | `./data` | Where project data is stored |
| `HOST` | `127.0.0.1` | Backend bind address |
| `PORT` | `8001` | Backend port |
| `EXIFTOOL_PATH` | *(empty)* | Absolute path to ExifTool if not on PATH |

### 3. Launch

**Windows (double-click):**
```
start.bat
```

**Any platform:**
```bash
python launcher.py
```

This starts both the backend (FastAPI on `:8001`) and frontend (Vite on `:5173`) and opens the browser automatically. Use `--no-browser` to skip.

### 4. Use

1. Create a new project and link your camera track
2. Import targets (CSV or manual placement)
3. Link a DTM GeoTIFF
4. For each target: mark the **Object Top** and **Shadow Tip** across 2+ images
5. Click **Compute** — results appear in the table
6. Export as Pix4D or Metashape checkpoint CSV

---

## Project Structure

```
SimpliSolar/
├── launcher.py              # Unified launcher (backend + frontend)
├── start.bat                # Windows shortcut to launcher
├── pyproject.toml           # Python project config & dependencies
│
├── backend/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Settings from .env
│   ├── api/                 # REST endpoints
│   │   ├── projects.py      #   Project CRUD, link DTM
│   │   ├── marking.py       #   Submit/retrieve pixel marks
│   │   ├── compute.py       #   Trigger measurement pipeline
│   │   ├── export.py        #   Download GCP/checkpoint CSV
│   │   ├── images.py        #   Serve drone images
│   │   └── browse.py        #   File browser for linking local paths
│   ├── engine/              # Core math
│   │   ├── camera_math.py   #   Undistortion, ray construction, projection
│   │   ├── ray_intersection.py  # Robust multi-ray intersection (RANSAC)
│   │   ├── height_calc.py   #   Shadow → height formulas
│   │   ├── solar.py         #   Sun position via Skyfield + JPL ephemeris
│   │   └── atmosphere.py    #   Weather lookup for refraction correction
│   ├── ingest/              # Data import parsers
│   │   ├── opf_parser.py    #   Pix4DMatic OPF format
│   │   ├── pix4d_parser.py  #   Pix4D external/internal params
│   │   ├── metashape_parser.py  # Agisoft Metashape XML
│   │   ├── dtm_loader.py    #   GeoTIFF DTM reader
│   │   └── exif_parser.py   #   DJI EXIF/XMP extraction
│   ├── models/              # Pydantic data models
│   └── services/            # Business logic orchestration
│       ├── measurement_service.py  # The main pipeline
│       └── project_service.py      # Project persistence
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx           # Main app with routing
│   │   ├── api/client.ts     # API client
│   │   ├── components/       # React UI components
│   │   │   ├── ProjectSetup.tsx   # Project creation wizard
│   │   │   ├── ImageViewer.tsx    # Pannable image viewer with mark overlay
│   │   │   ├── MarkingPanel.tsx   # Mark submission + residual display
│   │   │   ├── ResultsTable.tsx   # Measurement results
│   │   │   └── ExportPanel.tsx    # CSV export
│   │   ├── hooks/            # React hooks (useProject, useMarking)
│   │   └── types/index.ts    # TypeScript interfaces
│   └── vite.config.ts        # Vite config with API proxy
│
└── data/                     # Project data directory (git-ignored)
```

---

## Running Tests

```bash
python -m pytest backend/tests/ -v
```

25 tests covering camera math, height calculations, ray intersection, solar ephemeris, and parser correctness.

---

## Supported Camera Track Formats

| Format | Source | Files |
|--------|--------|-------|
| **OPF** | Pix4DMatic | `.opf/` directory containing `project.opf` |
| **Pix4D** | Pix4Dmapper | `external.txt` + `internal.cam` |
| **Metashape XML** | Agisoft Metashape | Exported camera XML |

---

## Technical Notes

### Camera Convention

All parsers convert their native rotation convention to a **camera-to-world 3x3 rotation matrix** at import time. The internal camera frame is X=right, Y=down, Z=backward (photogrammetric convention). This eliminates ambiguity from omega/phi/kappa angle ordering.

### Sun Position

Solar ephemeris uses [Skyfield](https://rhodesmill.org/skyfield/) with the JPL DE421 ephemeris (auto-downloaded on first run). Each image's EXIF timestamp is used independently to compute the sun altitude at the exact moment of capture. Atmospheric refraction is corrected using historical weather data from [Open-Meteo](https://open-meteo.com/) (free, no API key), with ISA standard atmosphere as a fallback.

### DTM vs DSM

SimpliSolar requires a **DTM (Digital Terrain Model)** — a bare-earth raster with buildings and vegetation removed. A DSM (Digital Surface Model) will produce incorrect heights because the shadow tip would be projected onto rooftops/canopy rather than ground level.

---

## License

[MIT](LICENSE) — Copyright (c) 2026 Brenton Roesner
