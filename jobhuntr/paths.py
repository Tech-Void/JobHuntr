"""Where JobHuntr keeps its bundled resources and the user's data."""
import os
import sys
from pathlib import Path


def resource_dir() -> Path:
    """Folder holding static/ and default_sources.json (works inside a PyInstaller exe too)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "jobhuntr"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    """Per-user data folder: %APPDATA%\\JobHuntr unless JOBHUNTR_DATA is set."""
    base = os.environ.get("JOBHUNTR_DATA") or Path(os.environ.get("APPDATA", Path.home())) / "JobHuntr"
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path
