"""Common model classes."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


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
    firmware: str | None = None


class KeyPressState(StrEnum):
    """Physical and gesture state of a key."""

    UP = "up"
    DOWN = "down"
    HELD = "held"
    DOUBLE_PRESSED = "double_pressed"
    TRIPLE_PRESSED = "triple_pressed"


@dataclass
class KeyState:
    """Full runtime state for a single key on a Stream Deck device."""

    key_index: int
    row: int
    col: int
    state: KeyPressState
    image_b64: str | None = None  # base64 PNG of the last image sent to this key
    label: str = ""
    plugin_uuid: str | None = None
    action_uuid: str | None = None
    context_id: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    appearance: dict[str, Any] = field(default_factory=dict)
    appearance_defaults: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PageInfo:
    """One page of key assignments on a device."""

    page_id: str
    name: str


@dataclass(frozen=True)
class DevicePages:
    """A device's pages in display order, its default page, and the page currently on the hardware."""

    device_id: str
    pages: list[PageInfo]
    default_page_id: str
    active_page_id: str
