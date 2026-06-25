"""Common model classes."""

from dataclasses import dataclass


@dataclass
class DeviceHardwareInfo:
    """Hardware info for a Stream Deck device."""

    id: str | None
    type: str
    vendor_id: int
    product_id: int
    keys: int
    serial: str | None
    path: str
