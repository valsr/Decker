"""Loading screensaver images from disk and cycling through a gallery folder."""

import warnings
from pathlib import Path

from PIL import Image

from decker.asset.renderer import AssetRenderer

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 64_000_000
_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg"}


class ScreensaverImageError(Exception):
    """Raised when a screensaver image is missing, too large or cannot be decoded."""


def _check_file(file: Path) -> None:
    try:
        if not file.is_file():
            raise ScreensaverImageError(f"image not found: {file.name}")
        if file.stat().st_size > MAX_FILE_BYTES:
            raise ScreensaverImageError("image file is larger than 20 MiB")
    except OSError as exc:
        raise ScreensaverImageError(f"image is not readable: {exc}") from exc


def _load_raster(file: Path) -> Image.Image:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(file) as opened:
            if opened.width * opened.height > MAX_PIXELS:
                raise ScreensaverImageError("image has more than 64 megapixels")
            return opened.convert("RGBA")


def load_image(path: str, width: int, height: int) -> Image.Image:
    """Load an image as RGBA; SVG is rasterised at width x height, raster keeps its native size."""
    file = Path(path)
    _check_file(file)
    try:
        if file.suffix.lower() == ".svg":
            return AssetRenderer().render_path(file, width, height)
        return _load_raster(file)
    except ScreensaverImageError:
        raise
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise ScreensaverImageError(f"image cannot be decoded: {file.name}") from exc


class GalleryCursor:  # pylint: disable=too-few-public-methods
    """Walks the image files of a folder in name order, wrapping around and rescanning on every call."""

    def __init__(self) -> None:
        self._last: str | None = None

    def next_path(self, folder: str) -> str | None:
        """Return the image after the previously returned one (first when none or it is gone), or None if empty."""
        try:
            names = sorted(p.name for p in Path(folder).iterdir() if p.suffix.lower() in _EXTENSIONS and p.is_file())
        except OSError:
            return None
        if not names:
            return None
        later = [n for n in names if self._last is None or n > self._last]
        chosen = later[0] if later else names[0]
        self._last = chosen
        return str(Path(folder) / chosen)
