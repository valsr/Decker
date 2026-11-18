"""Decodes GIF bytes into RGBA frames downscaled to the largest key size."""

import io
from dataclasses import dataclass

from PIL import Image, ImageSequence

from decker.asset.renderer import MAX_RASTER_PIXELS
from decker.plugin.icons import MAX_ICON_BYTES

MAX_GIF_FRAMES = 300
# Frames x canvas width x height, checked from the header before any frame is decoded. Roomy enough for 300 frames
# of 480x480 (69 Mpx) and well below the 105 Mpx of a 100-frame 1024x1024 GIF or the 5 Gpx of a 300-frame 4096x4096.
MAX_GIF_PIXELS = 96_000_000
MAX_FRAME_SIZE = 144  # the largest key face; frames are composed into at most this square
MIN_FRAME_DELAY_MS = 20
DEFAULT_FRAME_DELAY_MS = 100
_GIF_MAGICS = (b"GIF87a", b"GIF89a")


class GifError(ValueError):
    """Raised when GIF data is undecodable or exceeds the frame or pixel budget."""


@dataclass(frozen=True)
class GifFrame:
    """One composited RGBA frame (at most MAX_FRAME_SIZE on its long side) and how long to show it."""

    image: Image.Image
    delay_ms: int


def is_gif(data: bytes) -> bool:
    """Return True when data starts with a GIF signature."""
    return data[:6] in _GIF_MAGICS


def is_animated_gif(data: bytes) -> bool:
    """Return True for a decodable GIF of at most MAX_ICON_BYTES with 2 to MAX_GIF_FRAMES frames within the pixel budget."""
    if not is_gif(data) or len(data) > MAX_ICON_BYTES:
        return False
    try:
        with Image.open(io.BytesIO(data)) as image:
            if getattr(image, "n_frames", 1) < 2:
                return False
            _check_budget(image)
            return True
    except Exception:  # pylint: disable=broad-exception-caught
        return False


def _check_budget(image: Image.Image) -> None:
    frames = getattr(image, "n_frames", 1)
    if frames > MAX_GIF_FRAMES:
        raise GifError(f"GIF has more than {MAX_GIF_FRAMES} frames")
    if image.width * image.height > MAX_RASTER_PIXELS:
        raise GifError(f"GIF is too large ({image.width}x{image.height})")
    if frames * image.width * image.height > MAX_GIF_PIXELS:
        raise GifError(f"GIF has too many pixels ({frames} frames of {image.width}x{image.height})")


def _shrink(frame: Image.Image) -> Image.Image:
    rgba = frame.convert("RGBA")
    longest = max(rgba.size)
    if longest <= MAX_FRAME_SIZE:
        return rgba
    ratio = MAX_FRAME_SIZE / longest
    size = (max(1, round(rgba.width * ratio)), max(1, round(rgba.height * ratio)))
    return rgba.resize(size, Image.Resampling.LANCZOS)


def _normalize_delay(delay_ms: object) -> int:
    # Browsers treat tiny delays as 100 ms; this also keeps total duration positive.
    if not isinstance(delay_ms, int) or delay_ms < MIN_FRAME_DELAY_MS:
        return DEFAULT_FRAME_DELAY_MS
    return delay_ms


def decode_gif(data: bytes) -> list[GifFrame]:
    """Decode a GIF into composited RGBA frames shrunk to MAX_FRAME_SIZE; raise GifError if invalid or over budget."""
    try:
        if len(data) > MAX_ICON_BYTES:
            raise GifError(f"GIF is larger than {MAX_ICON_BYTES} bytes")
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "GIF":
                raise GifError("not a GIF")
            _check_budget(image)
            # Pillow applies each frame's disposal method and transparency while iterating; shrinking each frame
            # at once keeps peak memory at about one canvas plus the small frames.
            return [
                GifFrame(_shrink(frame), _normalize_delay(frame.info.get("duration")))
                for frame in ImageSequence.Iterator(image)
            ]
    except GifError:
        raise
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise GifError(f"cannot decode GIF: {exc}") from exc
