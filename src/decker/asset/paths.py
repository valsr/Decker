"""Filesystem locations used by the asset system."""

from pathlib import Path

from decker.common import paths as decker_paths

DEFAULT_KEY_SVG = Path(__file__).parent / "default-key.svg"


def assets_dir() -> Path:
    """Return the root assets directory."""
    return decker_paths.assets()
