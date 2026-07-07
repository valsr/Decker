"""Stream Deck device lifecycle management."""

import logging
import threading
import zlib
from collections.abc import Callable
from typing import TYPE_CHECKING

from StreamDeck.DeviceManager import DeviceManager as _HardwareDeviceManager
from StreamDeck.Devices.StreamDeck import StreamDeck

from decker.common.manager import Manager
from decker.common.model import DeviceHardwareInfo
from decker.server import devices
from decker.server.devices import Device
from decker.server.devices.state import DeviceState

if TYPE_CHECKING:
    from decker.server.device_state_store import DeviceStateStore
    from decker.server.server_context import ServerContext

_KeyEventCallback = Callable[[str, int, bool], None]  # (device_id, key_index, pressed)


def device_id_for_serial(serial: str) -> str:
    """Return the stable 8-char CRC-32 hex device ID for a given serial number."""
    return format(zlib.crc32(serial.encode()) & 0xFFFFFFFF, "08x")


class NoSuchDeviceError(Exception):
    """Raised when a requested device ID does not correspond to any connected Stream Deck."""

    def __init__(self, path: str):
        super().__init__(f"Device at path {path} does not exist")


class DeviceNotOpened(Exception):
    """Raises when device can't be opened"""

    def __init__(self, path: str):
        super().__init__(f"Unable to open device at {path}")


class DeviceManager(Manager):
    """Opens Stream Deck devices on first request and caches one Device instance per device ID."""

    def __init__(self, on_key_event: _KeyEventCallback) -> None:
        self._on_key_event_cb = on_key_event
        self._devices: dict[str, Device] = {}
        self._states: dict[str, DeviceState] = {}
        self._lock = threading.Lock()
        self._state_store: "DeviceStateStore | None" = None

    def create(self, context: "ServerContext") -> None:
        """Wire the device state store; devices are opened lazily on first open_device() call."""
        self._state_store = context.device_state_store

    def destroy(self) -> None:
        """Reset and close all open devices."""
        with self._lock:
            devices_to_close = list(self._devices.values())
            self._devices.clear()
            self._states.clear()
        for device in devices_to_close:
            device.close()
        logging.info("DeviceManager: closed all devices")

    def get_device_state(self, device_id: str) -> DeviceState | None:
        """Return the in-memory state tracker for an open device, or None if not open."""
        return self._states.get(device_id)

    def clear_key_state(self, device_id: str, key_index: int) -> None:
        """Remove in-memory and persisted key state for a slot."""
        state = self._states.get(device_id)
        if state is not None:
            state.clear_key(key_index)
        elif self._state_store is not None:
            self._state_store.delete_key_state(device_id, key_index)

    def _on_hw_key_event(self, device: Device, key_index: int, pressed: bool) -> None:
        device.on_key_event(key_index, pressed)
        self._on_key_event_cb(device.device_id, key_index, pressed)

    def _on_device_closed(self, device_id: str) -> None:
        with self._lock:
            # Collect matching key first to avoid modifying the dict while iterating
            key = next(
                (k for k, d in self._devices.items() if d.path == device_id or d.device_id == device_id),
                None,
            )
            if key is not None:
                del self._devices[key]

    def list_devices(self) -> list[DeviceHardwareInfo]:
        """Return hardware info for all connected Stream Deck devices, even if not yet opened."""
        with self._lock:
            opened_by_path = {d.path: d for d in self._devices.values()}

        hardware_info: list[DeviceHardwareInfo] = []
        deck: StreamDeck
        for deck in _HardwareDeviceManager().enumerate():
            try:
                path = deck.id()
                existing = opened_by_path.get(path)
                if existing and existing.try_validate():
                    hardware_info.append(existing.get_hw_info())
                    continue

                # open the device temporarily and read the information
                if not devices.try_open_device(deck):
                    logging.warning(f"Unable to open device at {deck.id()}")
                    continue

                serial = deck.get_serial_number()
                id = device_id_for_serial(serial)
                tmp = Device(id, serial, deck)
                hardware_info.append(tmp.get_hw_info())
                deck.reset()
                logging.debug("Closing deck %s" % deck.id())
                deck.close()
            except Exception as exc:  # pylint: disable=broad-except
                logging.error("DeviceManager.list_devices failed for deck %s: %s", deck.id(), exc)

        return hardware_info

    def _close_device(self, device: Device) -> bool:
        with self._lock:
            if device.device_id in self._devices:
                device.close()
                del self._devices[device.device_id]
                return True
        return False

    def close_device(self, device: str | Device) -> bool:
        """Close and remove a device by instance or ID/path."""
        if isinstance(device, Device):
            return self._close_device(device)
        with self._lock:
            match = next(
                (d for d in self._devices.values() if d.path == device or d.device_id == device),
                None,
            )
        if match:
            return self._close_device(match)
        return False

    def _open_device(self, deck: StreamDeck) -> Device:
        with self._lock:
            existing = next((d for d in self._devices.values() if d.path == deck.id()), None)
            if existing:
                return existing

            # try open the device
            if not devices.try_open_device(deck):
                raise DeviceNotOpened(deck.id())

            serial = deck.get_serial_number()
            id = device_id_for_serial(serial)
            device = Device(id, serial, deck, self._on_device_closed)
            deck.set_key_callback(
                lambda _, key_index, pressed, dev=device: self._on_hw_key_event(dev, key_index, pressed)
            )
            self._devices[device.device_id] = device

        state = DeviceState(device.device_id, self._state_store, device.get_key_state)
        state.restore_from_store()
        self._states[device.device_id] = state

        if self._state_store is not None:
            self._state_store.save_device(device.get_hw_info())

        return device

    def open_device(self, device_id: str) -> Device | None:
        """Return the Device for this id, opening and caching it lazily on first request."""
        with self._lock:
            match = next(
                (d for d in self._devices.values() if d.path == device_id or d.device_id == device_id),
                None,
            )
        if match:
            return match

        for hw_info in self.list_devices():
            if hw_info.id == device_id:
                deck = next((d for d in _HardwareDeviceManager().enumerate() if d.id() == hw_info.path), None)
                if not deck:
                    logging.warning("DeviceManager: unable to open device at path %s", hw_info.path)
                    return None
                return self._open_device(deck)

        logging.warning("DeviceManager: unable to find device %s", device_id)
        return None

    def set_image_bytes(self, device_id: str, key_index: int, image: bytes) -> None:
        """Push image bytes to the given device's key and persist the rendered result."""
        device = self.open_device(device_id)
        if device is None:
            logging.debug("DeviceManager.set_image_bytes: device %s not open", device_id)
            return
        device.set_image_bytes(key_index, image)
        rendered = device.get_key_image(key_index)
        if rendered is not None:
            state = self._states.get(device_id)
            if state is not None:
                state.update_key_image(key_index, rendered)
            elif self._state_store is not None:
                self._state_store.save_key_image(device_id, key_index, rendered)
