"""Geometry and scaling that turn one image into per-key faces, optionally skipping bezel gaps."""

import math
from dataclasses import dataclass

from PIL import Image

_GAP_COLOR = (16, 16, 16, 255)


@dataclass(frozen=True)
class CanvasLayout:
    """Canvas size in pixels and each key's (left, top, right, bottom) box, row-major."""

    width: int
    height: int
    boxes: list[tuple[int, int, int, int]]


def canvas_layout(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    rows: int, cols: int, key_px: int, bezel: bool, key_mm: float, gap_mm: float
) -> CanvasLayout:
    """Lay out the keys on a canvas; with bezel the physical gap between keys is reproduced in pixels."""
    gap_px = round(key_px * gap_mm / key_mm) if bezel else 0
    pitch = key_px + gap_px
    boxes = [(c * pitch, r * pitch, c * pitch + key_px, r * pitch + key_px) for r in range(rows) for c in range(cols)]
    return CanvasLayout(cols * key_px + (cols - 1) * gap_px, rows * key_px + (rows - 1) * gap_px, boxes)


def _fit(image: Image.Image, layout: CanvasLayout, scaling: str) -> Image.Image:
    rgba = image.convert("RGBA")
    size = (layout.width, layout.height)
    if scaling == "stretch":
        return rgba.resize(size, Image.Resampling.LANCZOS)
    scale = max(layout.width / rgba.width, layout.height / rgba.height)
    new_w = max(layout.width, math.ceil(rgba.width * scale))
    new_h = max(layout.height, math.ceil(rgba.height * scale))
    scaled = rgba.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - layout.width) // 2
    top = (new_h - layout.height) // 2
    return scaled.crop((left, top, left + layout.width, top + layout.height))


def compose(image: Image.Image, layout: CanvasLayout, scaling: str) -> list[Image.Image]:
    """Return one image per key, cut from the scaled canvas so gap pixels are skipped."""
    canvas = _fit(image, layout, scaling)
    return [canvas.crop(box) for box in layout.boxes]


def preview_image(image: Image.Image, layout: CanvasLayout, scaling: str) -> Image.Image:
    """Return the scaled canvas with everything outside the key boxes painted dark."""
    canvas = _fit(image, layout, scaling)
    masked = Image.new("RGBA", canvas.size, _GAP_COLOR)
    for box in layout.boxes:
        masked.paste(canvas.crop(box), box[:2])
    return masked
