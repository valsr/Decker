"""Stream Deck device enumeration."""

import logging
from typing import Any

from StreamDeck.DeviceManager import DeviceManager


def list_devices() -> list[dict[str, Any]]:
    """Return info for every connected Stream Deck device.

    Each device is opened briefly to read its serial number, then closed.
    Devices that fail to open are included with a best-effort subset of info.
    """
    try:
        decks = DeviceManager().enumerate()
    except Exception as e:
        logging.error("Failed to enumerate Stream Deck devices: %s", e)
        return []

    result = []
    for deck in decks:
        info: dict[str, Any] = {
            "id": deck.id(),
            "type": deck.deck_type(),
            "vendor_id": deck.vendor_id(),
            "product_id": deck.product_id(),
            "keys": deck.key_count(),
            "serial": None,
        }
        try:
            deck.open()
            info["serial"] = deck.get_serial_number()
        except Exception as e:
            logging.warning("Could not open device %s to read serial: %s", info["id"], e)
        finally:
            try:
                deck.close()
            except Exception:  # pylint: disable=broad-except
                pass
        result.append(info)

    return result
