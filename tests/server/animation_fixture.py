"""Helpers for device animation tests: a small GIF spec, a write log for a fake deck, and polling."""

import io
import threading
import time
from collections.abc import Callable

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
