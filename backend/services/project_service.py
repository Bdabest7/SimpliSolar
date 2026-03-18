"""Project lifecycle management: create, load, save, list.

Projects are persisted as JSON files in the data directory.
Each project gets its own subdirectory: data/{project_id}/
"""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from backend.config import settings
from backend.models.project import Project, ProjectStatus


def _slugify(name: str) -> str:
    """Convert a project name to a filesystem-safe folder name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)          # strip non-alphanumeric (keep - _)
    slug = re.sub(r"[\s]+", "_", slug)             # spaces → underscores
    slug = re.sub(r"[_-]{2,}", "_", slug)          # collapse repeated separators
    slug = slug.strip("_-")
    return slug[:48] or "project"                  # cap length, fallback if empty


def _project_dir(project_id: str) -> Path:
    return settings.data_dir / project_id


def _project_file(project_id: str) -> Path:
    return _project_dir(project_id) / "project.json"


def create_project(name: str) -> Project:
    """Create a new project, using the name as the folder name."""
    base = _slugify(name)

    # Avoid collisions: append a short suffix if the folder already exists
    project_id = base
    if _project_dir(project_id).exists():
        suffix = uuid.uuid4().hex[:6]
        project_id = f"{base}_{suffix}"

    project = Project(id=project_id, name=name)

    d = _project_dir(project_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "images").mkdir(exist_ok=True)

    save_project(project)
    return project


def save_project(project: Project) -> None:
    """Persist project state to disk."""
    path = _project_file(project.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(project.model_dump_json(indent=2))


def load_project(project_id: str) -> Project:
    """Load a project from disk."""
    path = _project_file(project_id)
    if not path.exists():
        raise FileNotFoundError(f"Project {project_id} not found")
    return Project.model_validate_json(path.read_text())


def list_projects() -> list[Project]:
    """List all projects in the data directory."""
    projects = []
    if not settings.data_dir.exists():
        return projects
    for d in settings.data_dir.iterdir():
        pf = d / "project.json"
        if pf.exists():
            try:
                projects.append(Project.model_validate_json(pf.read_text()))
            except Exception:
                pass
    return projects


def delete_project(project_id: str) -> None:
    """Delete a project and all its data."""
    d = _project_dir(project_id)
    if d.exists():
        shutil.rmtree(d)


def get_images_dir(project_id: str) -> Path:
    """Return the images directory for a project.

    Prefers an external absolute path if one is configured
    (path-based workflow); falls back to the internal images/
    subfolder (legacy upload workflow).
    """
    try:
        project = load_project(project_id)
        if project.image_dir and Path(project.image_dir).is_absolute():
            return Path(project.image_dir)
    except Exception:
        pass
    return _project_dir(project_id) / "images"
