"""Loading screensaver images from disk and cycling through a gallery folder."""

import io
import math
import warnings
from pathlib import Path

import cairosvg  # type: ignore[import-untyped]
from cairosvg.helpers import node_format  # type: ignore[import-untyped]
from cairosvg.parser import Tree  # type: ignore[import-untyped]
from PIL import Image

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 24_000_000
_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg"}
_FORMATS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG"}
_OVERSAMPLE = 2  # decode at least this many times the canvas size before the final high-quality resize
_REDUCIBLE_MODES = {"L", "LA", "RGB", "RGBA", "CMYK", "I", "PA"}
_SVG_MAX_SIDE = 4  # a cover-scaled SVG side is capped at this many canvas sides (extreme aspect ratios)


class ScreensaverImageError(Exception):
    """Raised when a screensaver image is missing, too large or cannot be decoded."""


class _SvgProbe:  # pylint: disable=too-few-public-methods
    """The few surface attributes cairosvg needs to resolve a root element's width and height."""

    dpi: float = 96.0
    font_size: float = 16.0
    context_width: float = 0.0
    context_height: float = 0.0


def _check_file(file: Path) -> None:
    try:
        if not file.is_file():
            raise ScreensaverImageError(f"image not found: {file.name}")
        if file.stat().st_size > MAX_FILE_BYTES:
            raise ScreensaverImageError("image file is larger than 20 MiB")
    except OSError as exc:
        raise ScreensaverImageError(f"image is not readable: {file.name}") from exc


def _reduction(size: tuple[int, int], width: int, height: int) -> int:
    """The integer factor an image can shrink by and still be _OVERSAMPLE times the size covering the canvas."""
    return max(1, math.floor(min(size[0] / (_OVERSAMPLE * width), size[1] / (_OVERSAMPLE * height))))


def _load_raster(file: Path, width: int, height: int) -> Image.Image:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(file, formats=[_FORMATS[file.suffix.lower()]]) as opened:
            if opened.width * opened.height > MAX_PIXELS:
                raise ScreensaverImageError("image has more than 24 megapixels")
            factor = _reduction(opened.size, width, height)
            if opened.format == "JPEG" and factor > 1:
                opened.draft("RGB", (opened.width // factor, opened.height // factor))  # decodes at 1/2, 1/4 or 1/8
            image: Image.Image = opened
            image.load()
            factor = _reduction(image.size, width, height)
            if factor > 1 and image.mode in _REDUCIBLE_MODES:
                image = image.reduce(factor)  # shrink before any mode conversion copies the pixels
            if image is opened or image.mode != "RGBA":
                image = image.convert("RGBA")  # closing `opened` discards its pixels, so it is never returned
            return image


def _svg_size(data: bytes, width: int, height: int) -> tuple[int, int]:
    """The size that keeps the SVG's own aspect ratio and covers width x height; the canvas size if it has none."""
    intrinsic_w, intrinsic_h, _ = node_format(_SvgProbe(), Tree(bytestring=data))
    if not intrinsic_w or not intrinsic_h or intrinsic_w <= 0 or intrinsic_h <= 0:
        return width, height
    scale = max(width / intrinsic_w, height / intrinsic_h)
    return (
        min(_SVG_MAX_SIDE * width, max(width, math.ceil(intrinsic_w * scale))),
        min(_SVG_MAX_SIDE * height, max(height, math.ceil(intrinsic_h * scale))),
    )


def _load_svg(file: Path, width: int, height: int) -> Image.Image:
    data = file.read_bytes()
    out_w, out_h = _svg_size(data, width, height)
    png = cairosvg.svg2png(bytestring=data, output_width=out_w, output_height=out_h)
    with Image.open(io.BytesIO(png), formats=["PNG"]) as rendered:
        return rendered.convert("RGBA")


def load_image(path: str, width: int, height: int) -> Image.Image:
    """Load an image as RGBA, never much larger than twice the size needed to cover a width x height canvas.

    SVG is rasterised at its own aspect ratio, scaled to cover the canvas; PNG and JPEG are shrunk while decoding.
    """
    file = Path(path)
    _check_file(file)
    try:
        if file.suffix.lower() == ".svg":
            return _load_svg(file, width, height)
        return _load_raster(file, width, height)
    except ScreensaverImageError:
        raise
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise ScreensaverImageError(f"image cannot be decoded: {file.name}") from exc


def _image_names(folder: str) -> list[str]:
    try:
        return sorted(p.name for p in Path(folder).iterdir() if p.suffix.lower() in _EXTENSIONS and p.is_file())
    except OSError:
        return []


class GalleryCursor:
    """Walks the image files of a folder in name order, wrapping around; the folder is rescanned on every call."""

    def __init__(self) -> None:
        self._last: str | None = None

    def candidates(self, folder: str) -> list[str]:
        """Every image path of the folder, starting after the last one shown and wrapping around (one scan)."""
        names = _image_names(folder)
        later = [n for n in names if self._last is None or n > self._last]
        earlier = [n for n in names if n not in later]
        return [str(Path(folder) / n) for n in later + earlier]

    def mark_shown(self, path: str) -> None:
        """Remember path as the last image tried, so the next call starts after it."""
        self._last = Path(path).name

    def next_path(self, folder: str) -> str | None:
        """Return the image after the previously returned one (first when none or it is gone), or None if empty."""
        paths = self.candidates(folder)
        if not paths:
            return None
        self.mark_shown(paths[0])
        return paths[0]
