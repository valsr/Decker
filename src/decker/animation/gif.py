"""Decodes GIF bytes into RGBA frames downscaled to the largest key size."""

import io
import re
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
        offsets = _check_descriptors(data)
        with Image.open(io.BytesIO(data)) as image:
            if getattr(image, "n_frames", 1) < 2:
                return False
            _check_budget(image, offsets)
            return True
    except Exception:  # pylint: disable=broad-exception-caught
        return False


def _skip_sub_blocks(data: bytes, pos: int) -> int:
    while pos < len(data) and data[pos] != 0:
        pos += data[pos] + 1
    return pos + 1


_BLOCK_START = re.compile(rb"[\x21\x2c\x3b]")  # extension, image descriptor, trailer


def _check_descriptors(data: bytes) -> list[int]:
    """Walk the GIF blocks without decoding pixels and enforce the frame and pixel budgets on the canvas as it grows.

    The logical screen in the header is only the starting canvas: Pillow enlarges the canvas whenever a later frame
    reaches past it, so each frame costs the largest extent seen so far. The walk follows Pillow's reader (it skips
    bytes that start no block) but is only a first, cheap gate: Pillow has quirks a walk can disagree on, so
    `_verify_offsets` later checks that Pillow found every frame's pixel data at the offset recorded here.
    Returns those offsets, one per frame; truncated data just ends the walk (Pillow reports it when decoding).
    """
    offsets: list[int] = []
    if len(data) < 13:
        return offsets
    width, height = int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    pos = 13 + (3 << ((data[10] & 7) + 1) if data[10] & 0x80 else 0)
    total = 0
    while pos < len(data):
        marker = data[pos]
        if marker == 0x3B:
            break
        if marker == 0x21:  # extension: introducer, label, then data sub-blocks
            if pos + 2 < len(data) and data[pos + 2] == 0 and data[pos + 1] != 0xFE:
                # Pillow reads a second chain after an empty first sub-block; refuse rather than guess.
                raise GifError("GIF has an empty extension block")
            pos = _skip_sub_blocks(data, pos + 2)
        elif marker == 0x2C:  # image descriptor: left, top, width, height, flags
            if pos + 10 > len(data):
                break
            left, top, frame_width, frame_height = (
                int.from_bytes(data[pos + i : pos + i + 2], "little") for i in (1, 3, 5, 7)
            )
            flags = data[pos + 9]
            pos += 10 + (3 << ((flags & 7) + 1) if flags & 0x80 else 0)
            offsets.append(pos + 1)  # where Pillow records the pixel data: after the LZW minimum code size
            pos = _skip_sub_blocks(data, pos + 1)
            width, height = max(width, left + frame_width), max(height, top + frame_height)
            total += width * height
            if len(offsets) > MAX_GIF_FRAMES:
                raise GifError(f"GIF has more than {MAX_GIF_FRAMES} frames")
            if width * height > MAX_RASTER_PIXELS:
                raise GifError(f"GIF is too large ({width}x{height})")
            if total > MAX_GIF_PIXELS:
                raise GifError(f"GIF has too many pixels ({len(offsets)} frames up to {width}x{height})")
        else:
            match = _BLOCK_START.search(data, pos + 1)
            pos = match.start() if match else len(data)
    return offsets


def _verify_offsets(image: Image.Image, offsets: list[int]) -> None:
    """Fail closed unless Pillow locates every frame's pixel data exactly where the block walk did.

    Seeking without updating the image records each frame's position but neither grows the canvas nor loads pixels.
    If a Pillow release renames the private attribute read here, every GIF is rejected cleanly (and the tests that
    play ordinary GIFs fail), rather than the check silently passing.
    """
    try:
        for index, expected in enumerate(offsets):
            image._seek(index, index == 0)  # type: ignore[attr-defined]  # pylint: disable=protected-access
            if getattr(image, "_GifImageFile__offset") != expected:
                raise GifError("GIF frames are laid out differently from what the decoder reads")
        try:
            image._seek(len(offsets), False)  # type: ignore[attr-defined]  # pylint: disable=protected-access
        except EOFError:
            image.seek(0)
            return
        raise GifError("GIF has frames the block walk did not see")
    except GifError:
        raise
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise GifError(f"cannot verify GIF layout: {exc}") from exc


def _check_budget(image: Image.Image, offsets: list[int]) -> None:
    frames = getattr(image, "n_frames", 1)
    if len(offsets) != frames:
        raise GifError(f"GIF block walk found {len(offsets)} frames but the decoder {frames}")
    if frames > MAX_GIF_FRAMES:
        raise GifError(f"GIF has more than {MAX_GIF_FRAMES} frames")
    if image.width * image.height > MAX_RASTER_PIXELS:
        raise GifError(f"GIF is too large ({image.width}x{image.height})")
    if frames * image.width * image.height > MAX_GIF_PIXELS:
        raise GifError(f"GIF has too many pixels ({frames} frames of {image.width}x{image.height})")
    _verify_offsets(image, offsets)


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
        offsets = _check_descriptors(data)
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "GIF":
                raise GifError("not a GIF")
            _check_budget(image, offsets)
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
