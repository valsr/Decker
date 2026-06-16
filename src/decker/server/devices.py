"""Stream Deck device enumeration."""

import logging
import zlib
from typing import Any

from StreamDeck.DeviceManager import DeviceManager


def device_id_for_serial(serial: str) -> str:
    """Derive a stable hex ID from a device serial number via CRC-32."""
    return format(zlib.crc32(serial.encode()) & 0xFFFFFFFF, "08x")


def list_devices() -> list[dict[str, Any]]:
    """Return info for every connected Stream Deck device.

    Each device is opened briefly to read its serial number, then closed.
    Devices that fail to open are included with a best-effort subset of info
    and no id (serial could not be read).
    """
    try:
        decks = DeviceManager().enumerate()
    except Exception as e:
        logging.error("Failed to enumerate Stream Deck devices: %s", e)
        return []

    result = []
    for deck in decks:
        info: dict[str, Any] = {
            "id": None,
            "type": deck.deck_type(),
            "vendor_id": deck.vendor_id(),
            "product_id": deck.product_id(),
            "keys": deck.key_count(),
            "serial": None,
        }
        try:
            deck.open()
            serial = deck.get_serial_number()
            info["serial"] = serial
            info["id"] = device_id_for_serial(serial)
        except Exception as e:
            logging.warning("Could not open device to read serial: %s", e)
        finally:
            try:
                deck.close()
            except Exception:  # pylint: disable=broad-except
                pass
        result.append(info)

    return result
