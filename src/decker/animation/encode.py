"""Scales and encodes composed key images into the deck's native format."""

import io
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from PIL import Image


@dataclass(frozen=True)
class KeyFormat:
    """A deck's key image format: size, codec, rotation, flips and HID report payload size."""

    size: tuple[int, int]
    image_format: str
    rotation: int
    flip: tuple[bool, bool]
    report_payload: int = 1016

    @classmethod
    def from_deck(cls, fmt: Mapping[str, Any], report_payload: int = 1016) -> "KeyFormat":
        """Build from a deck's key_image_format() mapping."""
        return cls(
            size=(int(fmt["size"][0]), int(fmt["size"][1])),
            image_format=str(fmt["format"]),
            rotation=int(fmt["rotation"]),
            flip=(bool(fmt["flip"][0]), bool(fmt["flip"][1])),
            report_payload=report_payload,
        )


def encode_native(image: Image.Image, fmt: KeyFormat, quality: int) -> bytes:
    """Scale to the key size, rotate then flip as the deck expects, and encode (quality applies to JPEG only)."""
    out = image.convert("RGB")
    if out.size != fmt.size:
        out = out.resize(fmt.size, Image.Resampling.LANCZOS)
    if fmt.rotation:
        out = out.rotate(fmt.rotation)
    if fmt.flip[0]:
        out = out.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if fmt.flip[1]:
        out = out.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    buf = io.BytesIO()
    if fmt.image_format.upper() == "JPEG":
        out.save(buf, format="JPEG", quality=quality)
    else:
        out.save(buf, format=fmt.image_format)
    return buf.getvalue()
