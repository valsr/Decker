"""Renders resolved asset paths or runtime image payloads to PIL Images."""

import io
from pathlib import Path
from xml.etree.ElementTree import ParseError

import cairosvg  # type: ignore[import-untyped]
from PIL import Image, UnidentifiedImageError


MAX_RASTER_PIXELS = 4096 * 4096
_SVG_SNIFF_BYTES = 64 * 1024


class ImageTooLargeError(ValueError):
    """Raised when a raster image exceeds the pixel budget."""


def _open_raster(source: Path | io.BytesIO) -> Image.Image:
    image = Image.open(source)
    if image.width * image.height > MAX_RASTER_PIXELS:
        raise ImageTooLargeError(f"image is too large ({image.width}x{image.height})")
    return image


def _looks_like_svg(data: bytes) -> bool:
    head = data[:_SVG_SNIFF_BYTES].lstrip(b"\xef\xbb\xbf \t\r\n")
    return head.startswith(b"<") and b"<svg" in head


class AssetRenderer:
    """Converts SVG/PNG/JPEG/GIF/WEBP sources to a PIL Image at a target size.

    GIF/WEBP inputs render their first frame only — Pillow's default Image.open()
    behavior; there is no per-frame animation support yet.
    """

    def render_path(self, path: Path, width: int, height: int) -> Image.Image:
        """Render the asset at path to a width x height RGBA image."""
        if path.suffix.lower() == ".svg":
            return self._render_svg(path.read_bytes(), width, height)
        return _open_raster(path).convert("RGBA").resize((width, height))

    def render_bytes(self, data: bytes, width: int, height: int) -> Image.Image | None:
        """Render raw image bytes (SVG or raster) to a width x height RGBA image.

        Returns None if data is not a recognizable image format — callers should treat
        that as already-native hardware bytes and pass them through unchanged.
        """
        if _looks_like_svg(data):
            try:
                return self._render_svg(data, width, height)
            except ParseError:
                return None
        try:
            return _open_raster(io.BytesIO(data)).convert("RGBA").resize((width, height))
        except UnidentifiedImageError:
            return None

    @staticmethod
    def _render_svg(data: bytes, width: int, height: int) -> Image.Image:
        png_bytes = cairosvg.svg2png(bytestring=data, output_width=width, output_height=height)
        return Image.open(io.BytesIO(png_bytes)).convert("RGBA")
