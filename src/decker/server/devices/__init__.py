"""Stream Deck device abstraction and per-key gesture tracking."""

import io
import logging
import threading
import time
from collections.abc import Callable

from StreamDeck.Devices.StreamDeck import StreamDeck
from StreamDeck.ImageHelpers import PILHelper

from decker.asset.renderer import AssetRenderer
from decker.common.error import DeckNotOpenedError
from decker.common.model import DeviceHardwareInfo, KeyInfo, KeyPressState

DeviceCloseCallback = Callable[[str], None]  # called when the device is detected as closed

_HELD_THRESHOLD_S: float = 0.5
_MULTI_TAP_WINDOW_S: float = 0.35


class _KeyTracker:
    """Per-key state machine tracking press gestures and the last rendered image."""

    def __init__(self) -> None:
        self.state: KeyPressState = KeyPressState.UP
        self.image: bytes | None = None  # cached PNG of the last image pushed to this key
        self._tap_count: int = 0
        self._last_up: float = 0.0
        self._held_timer: threading.Timer | None = None
        self._latch_timer: threading.Timer | None = None

    def on_down(self) -> None:
        """Handle a key-down hardware event."""
        self._cancel_latch()
        self._cancel_held()
        if time.monotonic() - self._last_up > _MULTI_TAP_WINDOW_S:
            self._tap_count = 0
        self.state = KeyPressState.DOWN
        self._held_timer = threading.Timer(_HELD_THRESHOLD_S, self._fire_held)
        self._held_timer.daemon = True
        self._held_timer.start()

    def on_up(self) -> None:
        """Handle a key-up hardware event, updating gesture state."""
        self._cancel_held()
        if self.state == KeyPressState.HELD:
            self._tap_count = 0
            self.state = KeyPressState.UP
            return
        self._last_up = time.monotonic()
        self._tap_count += 1
        if self._tap_count >= 3:
            self.state = KeyPressState.TRIPLE_PRESSED
            self._start_latch()
        elif self._tap_count >= 2:
            self.state = KeyPressState.DOUBLE_PRESSED
            self._start_latch()
        else:
            self.state = KeyPressState.UP
            # tap_count intentionally kept at 1 so a second press within the
            # window can still be detected as a double-press

    def _fire_held(self) -> None:
        self.state = KeyPressState.HELD
        self._tap_count = 0

    def _expire_latch(self) -> None:
        if self.state in (KeyPressState.DOUBLE_PRESSED, KeyPressState.TRIPLE_PRESSED):
            self.state = KeyPressState.UP
        self._tap_count = 0

    def _start_latch(self) -> None:
        self._latch_timer = threading.Timer(_MULTI_TAP_WINDOW_S, self._expire_latch)
        self._latch_timer.daemon = True
        self._latch_timer.start()

    def _cancel_held(self) -> None:
        if self._held_timer:
            self._held_timer.cancel()
            self._held_timer = None

    def _cancel_latch(self) -> None:
        if self._latch_timer:
            self._latch_timer.cancel()
            self._latch_timer = None


def try_open_device(device: StreamDeck) -> bool:
    """Attempt to open a StreamDeck device if not already open. Returns True if open."""
    if not device.is_open():
        try:
            logging.debug("Opening deck %s", device.id())
            device.open()
        except Exception:  # pylint: disable=broad-except
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
        self._key_trackers: dict[int, _KeyTracker] = {}

    def validate(self) -> None:
        """Raise DeckNotOpenedError if the device can no longer be reached."""
        if not self._try_open():
            raise DeckNotOpenedError(self.path)
        try:
            self._device.get_serial_number()
        except Exception as exc:
            if self._notify_on_closed:
                self._notify_on_closed(self.device_id)
            raise DeckNotOpenedError(self.path) from exc

    def try_validate(self) -> bool:
        """Return True if the device is reachable, False otherwise."""
        try:
            self._device.get_serial_number()
            return True
        except Exception:  # pylint: disable=broad-except
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

    def on_key_event(self, key_index: int, pressed: bool) -> None:
        """Update the key state machine from a hardware callback."""
        tracker = self._key_trackers.setdefault(key_index, _KeyTracker())
        if pressed:
            tracker.on_down()
        else:
            tracker.on_up()

    def get_key_state(self, key_index: int) -> KeyPressState:
        """Return the current gesture state for a key."""
        tracker = self._key_trackers.get(key_index)
        return tracker.state if tracker else KeyPressState.UP

    def get_key_image(self, key_index: int) -> bytes | None:
        """Return cached PNG bytes of the last image pushed to this key, or None."""
        tracker = self._key_trackers.get(key_index)
        return tracker.image if tracker else None

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
                buf = io.BytesIO()
                scaled.save(buf, format="PNG")
                self._key_trackers.setdefault(key_index, _KeyTracker()).image = buf.getvalue()
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
