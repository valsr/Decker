"""Value types for animated key faces: what to animate and the encoded result."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from typing import Any


@dataclass(frozen=True)
class AnimationSpec:
    """A GIF plus the key appearance, title and image scale it is composed with."""

    gif: bytes
    appearance: Mapping[str, Any]
    title: str
    scale: float
    layer: str = "foreground"
    overlay: bytes | None = None
    overlay_color: str | None = None
    background: bytes | None = None  # static base drawn under every foreground frame (a GIF shows its first frame)

    @cached_property
    def gif_sha(self) -> str:
        """SHA-256 hex digest of the GIF bytes."""
        return hashlib.sha256(self.gif).hexdigest()

    @cached_property
    def animation_id(self) -> str:
        """Stable id of the composed animation; independent of key size and quality."""
        look = json.dumps([dict(self.appearance), self.title, repr(float(self.scale))], sort_keys=True, default=str)
        extra = ""
        if self.layer != "foreground" or self.overlay is not None:
            overlay_sha = hashlib.sha256(self.overlay).hexdigest() if self.overlay is not None else ""
            extra = f":{self.layer}:{overlay_sha}:{self.overlay_color or ""}"
        if self.background is not None:  # only when set, so ids of specs without a background never change
            extra += f":bg:{hashlib.sha256(self.background).hexdigest()}"
        return hashlib.sha256(f"{self.gif_sha}:{look}{extra}".encode()).hexdigest()


@dataclass(frozen=True)
class Frame:
    """One natively encoded key frame, its HID report count and display time."""

    data: bytes
    reports: int
    delay_ms: int


@dataclass(frozen=True)
class Animation:
    """An animation encoded for one key format at one quality, with its poster PNG."""

    animation_id: str
    quality: int
    frames: tuple[Frame, ...]
    poster_png: bytes
    reports_by_quality: Mapping[int, float]

    @property
    def total_ms(self) -> int:
        """Length of one loop in milliseconds."""
        return sum(frame.delay_ms for frame in self.frames)

    def frame_index_at(self, elapsed_ms: int) -> int:
        """Index of the frame shown elapsed_ms after the start, looping forever."""
        remaining = elapsed_ms % self.total_ms
        for index, frame in enumerate(self.frames):
            if remaining < frame.delay_ms:
                return index
            remaining -= frame.delay_ms
        return len(self.frames) - 1
