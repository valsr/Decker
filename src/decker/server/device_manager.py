"""Stream Deck device lifecycle management."""

import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from StreamDeck.DeviceManager import DeviceManager as _HardwareDeviceManager
from StreamDeck.ImageHelpers import PILHelper

from decker.asset.renderer import AssetRenderer
from decker.common.manager import Manager
from decker.server.devices import device_id_for_serial

if TYPE_CHECKING:
    from decker.server.server_context import ServerContext

_KeyEventCallback = Callable[[str, int, bool], None]  # (device_id, key_index, pressed)


class NoSuchDeviceError(Exception):
    """Raised when a requested device ID does not correspond to any connected Stream Deck."""

    def __init__(self, device_id: str):
        super().__init__(f"No such device with ID {device_id}")
        self.device_id = device_id


class Device:
    """Maintains an open connection to a single Stream Deck and routes image pushes."""

    def __init__(self, deck: Any, device_id: str, on_key_event: _KeyEventCallback) -> None:
        self._deck = deck
        self._device_id = device_id
        self._renderer = AssetRenderer()
        deck.set_key_callback(lambda _deck, key_index, pressed: on_key_event(device_id, key_index, pressed))

    @property
    def device_id(self) -> str:
        """Stable 8-char CRC-32 hex ID for this device."""
        return self._device_id

    def set_image_bytes(self, key_index: int, image: bytes) -> None:
        """Render image bytes (SVG/PNG/JPEG) and push to the hardware key."""
        try:
            pil_image = self._renderer.render_bytes(image, self._deck.KEY_PIXEL_WIDTH, self._deck.KEY_PIXEL_HEIGHT)
            if pil_image is not None:
                scaled = PILHelper.create_scaled_key_image(self._deck, pil_image)
                native = PILHelper.to_native_key_format(self._deck, scaled)
            else:
                native = image
            self._deck.set_key_image(key_index, native)
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Device.set_image_bytes failed for %s[%d]: %s", self._device_id, key_index, exc)

    def close(self) -> None:
        """Reset and close the underlying hardware connection."""
        try:
            self._deck.reset()
            self._deck.close()
        except Exception:  # pylint: disable=broad-except
            pass


class DeviceManager(Manager):
    """Opens Stream Deck devices on first request and caches one Device instance per device ID."""

    def __init__(self, on_key_event: _KeyEventCallback) -> None:
        self._on_key_event = on_key_event
        self._devices: dict[str, Device] = {}
        self._lock = threading.Lock()

    def create(self, context: "ServerContext") -> None:
        """No-op: devices are opened lazily on first get_device() call."""

    def destroy(self) -> None:
        """Reset and close all open devices."""
        with self._lock:
            devices = list(self._devices.values())
            self._devices.clear()
        for device in devices:
            device.close()
        logging.info("DeviceManager: closed all devices")

    def get_device(self, device_id: str) -> Device | None:
        """Return the Device for this id, opening and caching it lazily on first request."""
        with self._lock:
            if device_id in self._devices:
                return self._devices[device_id]

        try:
            decks = _HardwareDeviceManager().enumerate()
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("DeviceManager: could not enumerate devices: %s", exc)
            return None

        for deck in decks:
            try:
                deck.open()
                serial = deck.get_serial_number()
                found_id = device_id_for_serial(serial)
                if found_id != device_id:
                    deck.close()
                    continue
                device = Device(deck, device_id, self._on_key_event)
                with self._lock:
                    self._devices[device_id] = device
                logging.info("DeviceManager: opened device %s", device_id)
                return device
            except Exception as exc:  # pylint: disable=broad-except
                logging.warning("DeviceManager: could not open device: %s", exc)

        return None

    def set_image_bytes(self, device_id: str, key_index: int, image: bytes) -> None:
        """Push image bytes to the given device's key (no-op if the device is not open)."""
        with self._lock:
            device = self._devices.get(device_id)
        if device is None:
            logging.debug("DeviceManager.set_image_bytes: device %s not open", device_id)
            return
        device.set_image_bytes(key_index, image)
