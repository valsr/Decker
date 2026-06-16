"""Maintains persistent Stream Deck device connections and routes hardware key events."""

import io
import logging
import threading
from collections.abc import Callable
from typing import Any

from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper

from decker.asset.renderer import AssetRenderer
from decker.server.devices import device_id_for_serial

_KeyEventCallback = Callable[[str, int, bool], None]  # (device_id, key_index, pressed)


class DeviceRunner:
    """Opens Stream Deck devices, registers key-press callbacks, and serves hardware image pushes.

    A single DeviceRunner instance is shared between the PluginManager (which calls
    set_image_bytes) and the server start-up path (which calls open_device for each
    connected device and wires the key-event callback to the PluginManager).
    """

    def __init__(self, on_key_event: _KeyEventCallback) -> None:
        self._on_key_event = on_key_event
        self._decks: dict[str, Any] = {}  # device_id → open StreamDeck
        self._lock = threading.Lock()
        self._renderer = AssetRenderer()

    def open_device(self, device_id: str) -> bool:
        """Open the device with this stable id (if not already open). Returns True on success."""
        with self._lock:
            if device_id in self._decks:
                return True
        try:
            decks = DeviceManager().enumerate()
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("DeviceRunner: could not enumerate devices: %s", exc)
            return False

        for deck in decks:
            try:
                deck.open()
                serial = deck.get_serial_number()
                found_id = device_id_for_serial(serial)
                if found_id != device_id:
                    deck.close()
                    continue
                deck.set_key_callback(
                    lambda _deck, key_index, pressed, _did=device_id: self._on_key_event(_did, key_index, pressed)
                )
                with self._lock:
                    self._decks[device_id] = deck
                logging.info("DeviceRunner: opened device %s", device_id)
                return True
            except Exception as exc:  # pylint: disable=broad-except
                logging.warning("DeviceRunner: could not open device: %s", exc)

        logging.warning("DeviceRunner: device %s not found during enumeration", device_id)
        return False

    def set_image_bytes(self, device_id: str, key_index: int, image: bytes) -> None:
        """Render image bytes (SVG/PNG/JPEG) to the native format and push to the hardware key."""
        with self._lock:
            deck = self._decks.get(device_id)
        if deck is None:
            logging.debug("DeviceRunner.set_image_bytes: device %s not open", device_id)
            return
        try:
            pil_image = self._renderer.render_bytes(image, deck.KEY_PIXEL_WIDTH, deck.KEY_PIXEL_HEIGHT)
            if pil_image is not None:
                scaled = PILHelper.create_scaled_key_image(deck, pil_image)
                native = PILHelper.to_native_key_format(deck, scaled)
            else:
                native = image
            deck.set_key_image(key_index, native)
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("DeviceRunner.set_image_bytes failed for %s[%d]: %s", device_id, key_index, exc)

    def render_text_image(self, text: str) -> bytes:
        """Render a plain-text label on a solid background. Returns PNG bytes."""
        from PIL import Image, ImageDraw  # pylint: disable=import-outside-toplevel

        img = Image.new("RGB", (72, 72), (31, 97, 141))
        draw = ImageDraw.Draw(img)
        try:
            from PIL import ImageFont  # pylint: disable=import-outside-toplevel

            font: Any = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 28)
        except Exception:  # pylint: disable=broad-except
            from PIL import ImageFont  # pylint: disable=import-outside-toplevel

            font = ImageFont.load_default()
        draw.text((36, 36), text, fill=(255, 255, 255), font=font, anchor="mm")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def close_all(self) -> None:
        """Reset and close all open devices."""
        with self._lock:
            decks = list(self._decks.values())
            self._decks.clear()
        for deck in decks:
            try:
                deck.reset()
                deck.close()
            except Exception:  # pylint: disable=broad-except
                pass
        logging.info("DeviceRunner: closed all devices")
