"""Shared asset paths, stylesheet loading and package metadata for the Decker client."""

import logging
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from decker.client import config as client_config
from decker.client.themes import BUNDLED, DARK, ThemeColors, render_stylesheet

_logger = logging.getLogger(__name__)

ICON_PATH: Path = Path(__file__).parent.parent / "assets" / "decker.svg"


def resolve_theme(theme: str | None = None, custom_path: str | None = None) -> tuple[str, ThemeColors | None]:
    """Return (stylesheet, palette colours) for theme, defaulting to the configured theme.

    Colours are None for a custom stylesheet. If a custom stylesheet is missing or unreadable,
    the dark theme is used instead and a warning is logged.
    """
    theme = theme or client_config.get_theme()
    if theme == client_config.THEME_CUSTOM:
        path = custom_path if custom_path is not None else client_config.get_custom_style_sheet()
        stylesheet = read_custom_stylesheet(path)
        if stylesheet is not None:
            return stylesheet, None
        _logger.warning("Cannot read custom stylesheet %r; using the dark theme", path)
    colors = BUNDLED.get(theme, DARK)
    return render_stylesheet(colors), colors


def load_stylesheet(theme: str | None = None, custom_path: str | None = None) -> str:
    """Return the QSS stylesheet for theme; see resolve_theme."""
    return resolve_theme(theme, custom_path)[0]


def read_custom_stylesheet(path: str) -> str | None:
    """Return the contents of a user-supplied stylesheet, or None if it is unset or unreadable."""
    if not path:
        return None
    try:
        return Path(path).expanduser().read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


try:
    APP_VERSION: str = _pkg_version("decker")
except PackageNotFoundError:
    APP_VERSION = "dev"
