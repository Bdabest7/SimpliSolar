"""SimpliSolar FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.logging_config import configure_logging
from backend.api import projects, images, marking, compute, export, browse

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure the data directory exists on startup."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="SimpliSolar",
    description="Multi-view shadow engine for calculating object heights from DJI RTK drone imagery",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for local development (React dev server on :5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(projects.router)
app.include_router(images.router)
app.include_router(marking.router)
app.include_router(compute.router)
app.include_router(export.router)
app.include_router(browse.router)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "version": "0.1.0"}


# Serve frontend static files in production
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
