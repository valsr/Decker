"""Shared asset paths and package metadata for the Decker client."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

ICON_PATH: Path = Path(__file__).parent.parent / "assets" / "decker.svg"

try:
    APP_VERSION: str = _pkg_version("decker")
except PackageNotFoundError:
    APP_VERSION = "dev"
