"""Filesystem locations used by the asset system."""

from pathlib import Path

from decker.common import paths as decker_paths

DEFAULT_KEY_SVG = Path(__file__).parent / "default-key.svg"


def assets_dir() -> Path:
    """Return the root assets directory."""
    return decker_paths.assets()


def user_icons_dir() -> Path:
    """Return the user-uploaded icons directory."""
    return decker_paths.user_icons()


def ensure_asset_dirs() -> None:
    """Create the asset directory structure on first run. Idempotent."""
    user_icons_dir().mkdir(parents=True, exist_ok=True)
