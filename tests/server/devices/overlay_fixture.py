"""Shared fake deck and manager helpers for the overlay and brightness tests."""

import io
from collections.abc import Callable
from unittest.mock import MagicMock, patch

from PIL import Image

from decker.server.device_state_store import DeviceStateStore
from decker.server.devices import Device
from decker.server.devices.manager import DeviceManager, device_id_for_serial
from decker.server.devices.state import DeviceState

SERIAL = "OVERLAY1"
DEVICE_ID = device_id_for_serial(SERIAL)


def make_deck(serial: str = SERIAL) -> MagicMock:
    deck = MagicMock()
    deck.get_serial_number.return_value = serial
    opened = [False]
    deck.is_open.side_effect = lambda: opened[0]
    deck.open.side_effect = lambda: opened.__setitem__(0, True)
    deck.close.side_effect = lambda: opened.__setitem__(0, False)
    deck.id.return_value = f"path-{serial}"
    deck.deck_type.return_value = "Stream Deck Mini"
    deck.vendor_id.return_value = 0x0FD9
    deck.product_id.return_value = 0x0063
    deck.get_firmware_version.return_value = "1.0"
    deck.KEY_PIXEL_WIDTH = 72
    deck.KEY_PIXEL_HEIGHT = 72
    deck.key_count.return_value = 3
    deck.key_layout.return_value = (1, 3)
    deck.key_image_format.return_value = {"size": (72, 72), "format": "JPEG", "flip": (False, False), "rotation": 0}
    return deck


def png(color: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (72, 72), color).save(buf, format="PNG")
    return buf.getvalue()


def open_manager(
    deck: MagicMock, on_key: Callable[[str, int, bool], None] | None = None, store: DeviceStateStore | None = None
) -> tuple[DeviceManager, Device]:
    manager = DeviceManager(on_key_event=on_key or (lambda *_: None))
    manager._state_store = store  # pylint: disable=protected-access
    with patch("decker.server.devices.manager._HardwareDeviceManager") as hw:
        hw.return_value.enumerate.return_value = [deck]
        device = manager.open_device(DEVICE_ID)
    assert device is not None
    return manager, device


def press(deck: MagicMock, key_index: int, pressed: bool) -> None:
    deck.set_key_callback.call_args.args[0](deck, key_index, pressed)


def state_of(manager: DeviceManager) -> DeviceState:
    state = manager.get_device_state(DEVICE_ID)
    assert state is not None
    return state
