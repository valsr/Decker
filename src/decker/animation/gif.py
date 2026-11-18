"""Decodes GIF bytes into full-canvas RGBA frames."""

import io
from dataclasses import dataclass

from PIL import Image, ImageSequence

from decker.asset.renderer import MAX_RASTER_PIXELS

MAX_GIF_FRAMES = 300
MIN_FRAME_DELAY_MS = 20
DEFAULT_FRAME_DELAY_MS = 100
_GIF_MAGICS = (b"GIF87a", b"GIF89a")


class GifError(ValueError):
    """Raised when GIF data is undecodable or exceeds the frame or pixel budget."""


@dataclass(frozen=True)
class GifFrame:
    """One composited canvas-sized RGBA frame and how long to show it."""

    image: Image.Image
    delay_ms: int


def is_gif(data: bytes) -> bool:
    """Return True when data starts with a GIF signature."""
    return data[:6] in _GIF_MAGICS


def is_animated_gif(data: bytes) -> bool:
    """Return True for a decodable GIF with more than one and at most MAX_GIF_FRAMES frames."""
    if not is_gif(data):
        return False
    try:
        with Image.open(io.BytesIO(data)) as image:
            return bool(1 < getattr(image, "n_frames", 1) <= MAX_GIF_FRAMES)
    except Exception:  # pylint: disable=broad-exception-caught
        return False


def _normalize_delay(delay_ms: object) -> int:
    # Browsers treat tiny delays as 100 ms; this also keeps total duration positive.
    if not isinstance(delay_ms, int) or delay_ms < MIN_FRAME_DELAY_MS:
        return DEFAULT_FRAME_DELAY_MS
    return delay_ms


def decode_gif(data: bytes) -> list[GifFrame]:
    """Decode a GIF into composited RGBA frames; raise GifError if invalid or over budget."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "GIF":
                raise GifError("not a GIF")
            if getattr(image, "n_frames", 1) > MAX_GIF_FRAMES:
                raise GifError(f"GIF has more than {MAX_GIF_FRAMES} frames")
            if image.width * image.height > MAX_RASTER_PIXELS:
                raise GifError(f"GIF is too large ({image.width}x{image.height})")
            # Pillow applies each frame's disposal method and transparency while iterating.
            return [
                GifFrame(frame.convert("RGBA"), _normalize_delay(frame.info.get("duration")))
                for frame in ImageSequence.Iterator(image)
            ]
    except GifError:
        raise
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise GifError(f"cannot decode GIF: {exc}") from exc
