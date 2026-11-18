"""Helpers for device animation tests: a small GIF spec, a write log for a fake deck, and polling."""

import io
import threading
import time
from collections.abc import Callable
from unittest.mock import MagicMock

from PIL import Image

from decker.animation.model import AnimationSpec
from decker.server.appearance import resolve_appearance

WRITER_THREAD = "decker-key-writer"


def make_gif(count: int = 3, delay_ms: int = 100) -> bytes:
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    frames = [Image.new("RGB", (16, 16), colors[i % len(colors)]) for i in range(count)]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=delay_ms, loop=0)
    return buffer.getvalue()


def make_spec() -> AnimationSpec:
    return AnimationSpec(make_gif(), resolve_appearance({}, {"background": "#202020"}), "", 1.0)


def wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class WriteLog:
    """Records every set_key_image call on a fake deck: key, data, writing thread and time."""

    def __init__(self) -> None:
        self.writes: list[tuple[int, bytes | None, str, float]] = []

    def __call__(self, key_index: int, data: bytes | None) -> None:
        self.writes.append((key_index, data, threading.current_thread().name, time.monotonic()))

    def for_key(self, key_index: int) -> list[tuple[int, bytes | None, str, float]]:
        return [write for write in self.writes if write[0] == key_index]


LIFECYCLE = ("open", "close", "reset")


def stateful_deck(serial: str = "ABC123", path: str = "/dev/hidraw0") -> MagicMock:
    """A fake deck whose is_open follows open()/close(); set get_serial_number.side_effect to make it fail."""
    deck = MagicMock()
    opened = [False]
    deck.is_open.side_effect = lambda: opened[0]
    deck.open.side_effect = lambda: opened.__setitem__(0, True)
    deck.close.side_effect = lambda: opened.__setitem__(0, False)
    deck.get_serial_number.return_value = serial
    deck.id.return_value = path
    deck.KEY_PIXEL_WIDTH = 72
    deck.KEY_PIXEL_HEIGHT = 72
    deck.IMAGE_REPORT_PAYLOAD_LENGTH = 1016
    deck.key_count.return_value = 15
    deck.key_layout.return_value = (3, 5)
    deck.key_image_format.return_value = {"size": (72, 72), "format": "JPEG", "flip": (False, False), "rotation": 0}
    deck.get_firmware_version.return_value = "1.0"
    deck.deck_type.return_value = "Stream Deck"
    deck.vendor_id.return_value = 1
    deck.product_id.return_value = 2
    return deck


def lifecycle(deck: MagicMock) -> list[str]:
    """The deck's open/close/reset calls in order."""
    return [call[0] for call in deck.mock_calls if call[0] in LIFECYCLE]
