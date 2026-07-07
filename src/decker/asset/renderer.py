"""Renders resolved asset paths or runtime image payloads to PIL Images."""

import io
from pathlib import Path
from xml.etree.ElementTree import ParseError

import cairosvg  # type: ignore[import-untyped]
from PIL import Image, UnidentifiedImageError


class AssetRenderer:
    """Converts SVG/PNG/JPEG/GIF/WEBP sources to a PIL Image at a target size.

    GIF/WEBP inputs render their first frame only — Pillow's default Image.open()
    behavior; there is no per-frame animation support yet.
    """

    def render_path(self, path: Path, width: int, height: int) -> Image.Image:
        """Render the asset at path to a width x height RGBA image."""
        if path.suffix.lower() == ".svg":
            return self._render_svg(path.read_bytes(), width, height)
        return Image.open(path).convert("RGBA").resize((width, height))

    def render_bytes(self, data: bytes, width: int, height: int) -> Image.Image | None:
        """Render raw image bytes (SVG or raster) to a width x height RGBA image.

        Returns None if data is not a recognizable image format — callers should treat
        that as already-native hardware bytes and pass them through unchanged.
        """
        stripped = data.lstrip()
        if stripped.startswith(b"<?xml") or stripped.startswith(b"<svg"):
            try:
                return self._render_svg(data, width, height)
            except ParseError:
                return None
        try:
            return Image.open(io.BytesIO(data)).convert("RGBA").resize((width, height))
        except UnidentifiedImageError:
            return None

    @staticmethod
    def _render_svg(data: bytes, width: int, height: int) -> Image.Image:
        png_bytes = cairosvg.svg2png(bytestring=data, output_width=width, output_height=height)
        return Image.open(io.BytesIO(png_bytes)).convert("RGBA")
