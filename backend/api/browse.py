"""Native file/directory picker endpoints.

Opens a Windows system dialog via tkinter so the user can browse
to a file or folder instead of typing a path manually.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/browse", tags=["browse"])

IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".tif", ".tiff", ".png"]


def _tk_dialog(func, **kwargs) -> str:
    """Run a tkinter dialog in a hidden root window and return the result."""
    import tkinter as tk
    from tkinter import filedialog  # noqa: F401 — imported for side effects

    root = tk.Tk()
    root.withdraw()               # hide the blank Tk window
    root.wm_attributes("-topmost", True)  # ensure dialog appears on top
    root.lift()
    result = func(parent=root, **kwargs)
    root.destroy()
    # tkinter returns "" when the user cancels
    return str(result) if result else ""


@router.get("/file")
def browse_file(title: str = "Select File", filter: str = "all"):
    """Open a native file-picker dialog and return the selected path."""
    try:
        type_map = {
            "csv":  [("CSV files", "*.csv"), ("All files", "*.*")],
            "xml":  [("XML files", "*.xml"), ("All files", "*.*")],
            "txt":  [("Text files", "*.txt"), ("All files", "*.*")],
        }
        filetypes = type_map.get(filter.lower(), [("All files", "*.*")])

        from tkinter import filedialog
        path = _tk_dialog(filedialog.askopenfilename, title=title, filetypes=filetypes)
        log.info("browse_file result: %r", path)
        return {"path": path}
    except Exception as exc:
        log.error("browse_file failed: %s", exc)
        raise HTTPException(500, f"Could not open file picker: {exc}")


@router.get("/directory")
def browse_directory(title: str = "Select Folder"):
    """Open a native directory-picker dialog and return the selected path."""
    try:
        from tkinter import filedialog
        path = _tk_dialog(filedialog.askdirectory, title=title, mustexist=True)
        log.info("browse_directory result: %r", path)
        return {"path": path}
    except Exception as exc:
        log.error("browse_directory failed: %s", exc)
        raise HTTPException(500, f"Could not open directory picker: {exc}")
