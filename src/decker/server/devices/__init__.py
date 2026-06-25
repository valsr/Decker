import logging
from collections.abc import Callable

from StreamDeck.Devices.StreamDeck import StreamDeck
from StreamDeck.ImageHelpers import PILHelper

from decker.asset.renderer import AssetRenderer
from decker.common.error import DeckNotOpenedError
from decker.common.model import DeviceHardwareInfo, KeyInfo

DeviceCloseCallback = Callable[[str], None]  # called when the device is detected as closed


def try_open_device(device: StreamDeck) -> bool:
    if not device.is_open():
        try:
            logging.debug("Opening deck %s" % device.id())
            device.open()
        except Exception:
            pass
    return device.is_open()


class Device:
    """Maintains an open connection to a single Stream Deck and routes image pushes."""

    def __init__(
        self, id: str, serial: str, deck: StreamDeck, notify_on_closed: DeviceCloseCallback | None = None
    ) -> None:
        self._device: StreamDeck = deck
        self.serial: str = serial
        self.id: str = id
        self._renderer = AssetRenderer()
        self._notify_on_closed = notify_on_closed

    def validate(self) -> None:
        """Raise DeckNotOpenedError if the device can no longer be reached."""
        if not self._try_open():
            raise DeckNotOpenedError(self.path)
        try:
            self._device.get_serial_number()
        except Exception:
            if self._notify_on_closed:
                self._notify_on_closed(self.device_id)
            raise DeckNotOpenedError(self.path)

    def try_validate(self) -> bool:
        """Return True if the device is reachable, False otherwise."""
        try:
            self._device.get_serial_number()
            return True
        except Exception:
            if self._notify_on_closed:
                self._notify_on_closed(self.device_id)
            return False

    def get_hw_info(self) -> DeviceHardwareInfo:
        """Return hardware metadata for this device."""
        rows, cols = self._device.key_layout()
        fmt = self._device.key_image_format()
        w, h = fmt["size"]
        keys = [
            KeyInfo(row=r, col=c, pixel_width=w, pixel_height=h, type="key") for r in range(rows) for c in range(cols)
        ]
        return DeviceHardwareInfo(
            id=self.id,
            type=self._device.deck_type(),
            vendor_id=self._device.vendor_id(),
            product_id=self._device.product_id(),
            num_keys=self._device.key_count(),
            keys=keys,
            serial=self.serial,
            path=self.path,
        )

    @property
    def path(self) -> str:
        """USB path used as a stable physical identifier."""
        return self._device.id()

    @property
    def device_id(self) -> str:
        """Stable 8-char CRC-32 hex ID derived from the serial number."""
        return self.id

    def _try_open(self) -> bool:
        if not self._device.is_open() or not self.try_validate():
            try_open_device(self._device)

        is_open = self._device.is_open() and self.try_validate()
        if not is_open and self._notify_on_closed:
            self._notify_on_closed(self.device_id)
        return is_open

    def set_image_bytes(self, key_index: int, image: bytes) -> None:
        """Render image bytes (SVG/PNG/JPEG) and push to the hardware key."""
        try:
            pil_image = self._renderer.render_bytes(image, self._device.KEY_PIXEL_WIDTH, self._device.KEY_PIXEL_HEIGHT)
            if pil_image is not None:
                scaled = PILHelper.create_scaled_key_image(self._device, pil_image)
                native = PILHelper.to_native_key_format(self._device, scaled)
            else:
                native = image
            self._try_open()
            self._device.set_key_image(key_index, native)
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Device.set_image_bytes failed for %s[%d]: %s", self.id, key_index, exc)

    def close(self) -> None:
        """Reset and close the underlying hardware connection."""
        try:
            logging.debug("Closing device %s", self.id)
            self._device.reset()
            self._device.close()
        except Exception:  # pylint: disable=broad-except
            logging.warning("Failed to close device %s cleanly", self.id)
