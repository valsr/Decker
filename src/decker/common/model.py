"""Common model classes."""

from dataclasses import dataclass, field


@dataclass
class KeyInfo:
    """Layout and pixel dimensions for a single button key."""

    row: int
    col: int
    pixel_width: int
    pixel_height: int
    type: str  # "key", "dial", "touchscreen"


@dataclass
class DeviceHardwareInfo:
    """Hardware info for a Stream Deck device."""

    id: str | None
    type: str
    vendor_id: int
    product_id: int
    num_keys: int
    keys: list[KeyInfo] = field(default_factory=list)
    serial: str | None = None
    path: str = ""
