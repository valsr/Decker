"""Decodes GIF bytes into RGBA frames downscaled to the largest key size."""

import io
from dataclasses import dataclass

from PIL import Image, ImageSequence

from decker.asset.renderer import MAX_RASTER_PIXELS
from decker.plugin.icons import MAX_ICON_BYTES

MAX_GIF_FRAMES = 300
# Sum over frames of the canvas pixels (a frame bigger than the logical screen grows the canvas for it and every
# later frame), checked from the block headers before any frame is decoded. Roomy enough for 300 frames
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
        walked = _check_descriptors(data)
        with Image.open(io.BytesIO(data)) as image:
            if getattr(image, "n_frames", 1) < 2:
                return False
            _check_budget(image, walked)
            return True
    except Exception:  # pylint: disable=broad-exception-caught
        return False


def _skip_sub_blocks(data: bytes, pos: int) -> int:
    while pos < len(data) and data[pos] != 0:
        pos += data[pos] + 1
    return pos + 1


_BLOCK_STARTS = (b"\x21", b"\x2c", b"\x3b")


def _next_block(data: bytes, pos: int) -> int:
    """Index of the next byte that can start a block at or after pos (len(data) when none does)."""
    found = [index for index in (data.find(start, pos) for start in _BLOCK_STARTS) if index >= 0]
    return min(found) if found else len(data)


def _check_descriptors(data: bytes) -> int | None:
    """Walk the GIF blocks without decoding pixels and enforce the frame and pixel budgets on the canvas as it grows.

    The logical screen in the header is only the starting canvas: Pillow enlarges the canvas whenever a later frame
    reaches past it, so each frame costs the largest extent seen so far. The walk mirrors Pillow's own reader, which
    skips bytes that start no block, so padding cannot hide a frame from it. Returns the frame count when the walk
    reached the trailer, or None for truncated data (Pillow reports that when the frames are decoded).
    """
    if len(data) < 13:
        return None
    width, height = int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    pos = 13 + (3 << ((data[10] & 7) + 1) if data[10] & 0x80 else 0)
    frames = total = 0
    while pos < len(data):
        marker = data[pos]
        if marker == 0x3B:
            return frames
        if marker == 0x21:  # extension: introducer, label, then data sub-blocks
            pos = _skip_sub_blocks(data, pos + 2)
        elif marker == 0x2C:  # image descriptor: left, top, width, height, flags
            if pos + 10 > len(data):
                return None
            left, top, frame_width, frame_height = (
                int.from_bytes(data[pos + i : pos + i + 2], "little") for i in (1, 3, 5, 7)
            )
            flags = data[pos + 9]
            pos += 10 + (3 << ((flags & 7) + 1) if flags & 0x80 else 0)
            pos = _skip_sub_blocks(data, pos + 1)  # LZW minimum code size, then the compressed pixels
            frames += 1
            width, height = max(width, left + frame_width), max(height, top + frame_height)
            total += width * height
            if frames > MAX_GIF_FRAMES:
                raise GifError(f"GIF has more than {MAX_GIF_FRAMES} frames")
            if width * height > MAX_RASTER_PIXELS:
                raise GifError(f"GIF is too large ({width}x{height})")
            if total > MAX_GIF_PIXELS:
                raise GifError(f"GIF has too many pixels ({frames} frames up to {width}x{height})")
        else:
            pos = _next_block(data, pos + 1)
    return None


def _check_budget(image: Image.Image, walked_frames: int | None) -> None:
    frames = getattr(image, "n_frames", 1)
    if walked_frames is not None and walked_frames != frames:
        raise GifError(f"GIF block walk found {walked_frames} frames but the decoder {frames}")
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
        if not is_gif(data):
            raise GifError("not a GIF")
        # The walk runs before Pillow opens anything: Image.open already seeks to frame 0, which grows the canvas.
        walked = _check_descriptors(data)
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "GIF":
                raise GifError("not a GIF")
            _check_budget(image, walked)
            # Pillow applies each frame's disposal method and transparency while iterating; shrinking each frame
            # at once keeps peak memory at about one canvas plus the small frames.
            frames: list[GifFrame] = []
            total = 0
            for frame in ImageSequence.Iterator(image):
                # Defence in depth behind the block walk: re-check the canvas Pillow reports before copying this frame.
                pixels = frame.width * frame.height
                total += pixels
                if pixels > MAX_RASTER_PIXELS:
                    raise GifError(f"GIF is too large ({frame.width}x{frame.height})")
                if total > MAX_GIF_PIXELS:
                    raise GifError(
                        f"GIF has too many pixels ({len(frames) + 1} frames up to {frame.width}x{frame.height})"
                    )
                frames.append(GifFrame(_shrink(frame), _normalize_delay(frame.info.get("duration"))))
            return frames
    except GifError:
        raise
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise GifError(f"cannot decode GIF: {exc}") from exc
