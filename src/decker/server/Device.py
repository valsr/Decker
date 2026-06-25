import logging
from collections.abc import Callable

from compression import zlib
from StreamDeck.Devices.StreamDeck import StreamDeck
from StreamDeck.ImageHelpers import PILHelper

from decker.asset.renderer import AssetRenderer
from decker.common.error import DeckNotOpenedError
from decker.common.model import DeviceHardwareInfo

DeviceCloseCallback = Callable[[str], None]  # called when the device is detected as closed


def device_id_for_serial(serial: str) -> str:
    """Return the stable 8-char CRC-32 hex device ID for a given serial number."""
    return format(zlib.crc32(serial.encode()) & 0xFFFFFFFF, "08x")


class Device:
    """Maintains an open connection to a single Stream Deck and routes image pushes."""

    def __init__(self, deck: StreamDeck, notify_on_closed: DeviceCloseCallback | None = None) -> None:
        self._deck: StreamDeck = deck
        self.serial: str = ""
        self.id: str = ""
        self._renderer = AssetRenderer()
        self._notify_on_closed = notify_on_closed
        self._init()

    def _init(self) -> None:
        logging.info("Initializing device %s", self._deck.id())
        self._try_open()
        self.serial = self._deck.get_serial_number()
        self.id = device_id_for_serial(self.serial)

    def validate(self) -> None:
        """Raise DeckNotOpenedError if the device can no longer be reached."""
        if not self._try_open():
            raise DeckNotOpenedError(self.path)
        try:
            self._deck.get_serial_number()
        except Exception:
            if self._notify_on_closed:
                self._notify_on_closed(self.device_id)
            raise DeckNotOpenedError(self.path)

    def try_validate(self) -> bool:
        """Return True if the device is reachable, False otherwise."""
        if not self._try_open():
            return False
        try:
            self._deck.get_serial_number()
            return True
        except Exception:
            if self._notify_on_closed:
                self._notify_on_closed(self.device_id)
            return False

    def get_hw_info(self) -> DeviceHardwareInfo:
        """Return hardware metadata for this device."""
        return DeviceHardwareInfo(
            id=self.id,
            type=self._deck.deck_type(),
            vendor_id=self._deck.vendor_id(),
            product_id=self._deck.product_id(),
            keys=self._deck.key_count(),
            serial=self.serial,
            path=self.path,
        )

    @property
    def path(self) -> str:
        """USB path used as a stable physical identifier."""
        return self._deck.id()

    @property
    def device_id(self) -> str:
        """Stable 8-char CRC-32 hex ID derived from the serial number."""
        return self.id

    def _try_open(self) -> bool:
        if not self._deck.is_open():
            try:
                self._deck.open()
            except Exception:
                pass
        is_open = self._deck.is_open()
        if not is_open and self._notify_on_closed:
            self._notify_on_closed(self.device_id)
        return is_open

    def set_image_bytes(self, key_index: int, image: bytes) -> None:
        """Render image bytes (SVG/PNG/JPEG) and push to the hardware key."""
        try:
            pil_image = self._renderer.render_bytes(image, self._deck.KEY_PIXEL_WIDTH, self._deck.KEY_PIXEL_HEIGHT)
            if pil_image is not None:
                scaled = PILHelper.create_scaled_key_image(self._deck, pil_image)
                native = PILHelper.to_native_key_format(self._deck, scaled)
            else:
                native = image
            self._try_open()
            self._deck.set_key_image(key_index, native)
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Device.set_image_bytes failed for %s[%d]: %s", self.id, key_index, exc)

    def close(self) -> None:
        """Reset and close the underlying hardware connection."""
        try:
            logging.debug("Closing device %s", self.id)
            self._deck.reset()
            self._deck.close()
        except Exception:  # pylint: disable=broad-except
            logging.warning("Failed to close device %s cleanly", self.id)
