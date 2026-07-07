"""Shared asset paths and package metadata for the Decker client."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from decker.common import config

ICON_PATH: Path = Path(__file__).parent.parent / "assets" / "decker.svg"
_STYLESHEET_PATH: Path = Path(__file__).parent / "style.qss"


def load_stylesheet() -> str:
    """Return the application QSS stylesheet."""
    stylesheet_path = config.get_as_or_default("client.style_sheet", str, _STYLESHEET_PATH)
    # TODO Monitor for changes and re-load
    return stylesheet_path.read_text(encoding="utf-8")


try:
    APP_VERSION: str = _pkg_version("decker")
except PackageNotFoundError:
    APP_VERSION = "dev"
