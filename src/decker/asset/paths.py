"""Filesystem locations used by the asset system."""

from pathlib import Path

ASSETS_DIR = Path.home() / ".decker" / "assets"
USER_ICONS_DIR = ASSETS_DIR / "user-icons"
ICONPACKS_DIR = ASSETS_DIR / "iconpacks"
DEFAULT_KEY_SVG = Path(__file__).parent / "default-key.svg"


def ensure_asset_dirs() -> None:
    """Create the asset directory structure on first run. Idempotent."""
    USER_ICONS_DIR.mkdir(parents=True, exist_ok=True)
    ICONPACKS_DIR.mkdir(parents=True, exist_ok=True)
