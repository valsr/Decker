"""End to end: a real DeviceManager/Device/KeyWriter/controller against a fake 32-key deck on a simulated clock."""

import io
import math
import random
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that
from PIL import Image

from decker.animation.controller import LADDER, STEP_DOWN_BUSY
from decker.animation.model import AnimationSpec
from decker.animation.writer import AdaptiveConfig, KeyWriter
from decker.server.appearance import resolve_appearance
from decker.server.device_state_store import DeviceStateStore
from decker.server.devices.manager import DeviceManager, device_id_for_serial
from tests.server.animation_fixture import stateful_deck, wait_until

KEYS = 32
PAYLOAD = 1016
SETTLE_S = 60.0
WINDOW_S = 10.0


class _SimClock:
    """Simulated time: only writes and the driver advance it, so tests never sleep for animation time."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._now: float = 1000.0

    def __call__(self) -> float:
        with self._lock:
            return self._now

    def advance_to(self, when: float) -> None:
        with self._lock:
            self._now = max(self._now, when)


class _Link:
    """The fake deck's USB link: each write costs one report time per HID report and is logged with its span."""

    def __init__(self, clock: _SimClock, seconds_per_report: float) -> None:
        self.clock = clock
        self.seconds_per_report = seconds_per_report
        self.writes: list[tuple[int, float, float]] = []  # key, start, end (simulated)

    def __call__(self, key_index: int, data: bytes | None) -> None:
        if data is None:
            return
        started = self.clock()
        self.clock.advance_to(started + math.ceil(len(data) / PAYLOAD) * self.seconds_per_report)
        self.writes.append((key_index, started, self.clock()))

    def busy_fraction(self, window_s: float) -> float:
        end = self.clock()
        busy = sum(
            min(stop, end) - max(start, end - window_s) for _, start, stop in self.writes if stop > end - window_s
        )
        return busy / window_s

    def keys_written(self) -> set[int]:
        return {key for key, _, _ in self.writes}


class _SimulatedKeyWriter(KeyWriter):
    """The production KeyWriter, driven by a thread that jumps the simulated clock to each next deadline."""

    def __init__(self, write: Callable[[int, bytes | None], None], clock: _SimClock, adaptive: AdaptiveConfig | None):
        super().__init__(write, clock, adaptive=adaptive)
        self._sim_clock = clock
        self._stop_sim = threading.Event()
        self._driver: threading.Thread | None = None

    def start(self) -> None:
        self._driver = threading.Thread(target=self._drive, name="sim-key-writer", daemon=True)
        self._driver.start()

    def close(self, timeout: float = 2.0) -> None:
        self._stop_sim.set()
        super().close(timeout)
        if self._driver is not None:
            self._driver.join(timeout)

    def _drive(self) -> None:
        while not self._stop_sim.is_set():
            deadline = self.step(self._sim_clock())
            if deadline is None:
                time.sleep(0.001)
            else:
                self._sim_clock.advance_to(deadline)
                time.sleep(0)  # let the test thread and the factory's build workers run between jumps


def _gif() -> bytes:
    """Ten smooth-noise 96x96 frames at 50 ms: about 9 HID reports each at quality 100, 4 at 90 and 3 at 75."""
    rng = random.Random(7)
    frames = []
    for _ in range(10):
        cells = Image.frombytes("RGB", (16, 16), bytes(rng.randrange(256) for _ in range(16 * 16 * 3)))
        frames.append(cells.resize((96, 96), Image.Resampling.BICUBIC))
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=50, loop=0)
    return buffer.getvalue()


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (72, 72), "red").save(buffer, format="PNG")
    return buffer.getvalue()


def _xl_deck(deck: MagicMock, link: _Link) -> None:
    deck.key_count.return_value = KEYS
    deck.key_layout.return_value = (4, 8)
    deck.KEY_PIXEL_WIDTH = 96
    deck.KEY_PIXEL_HEIGHT = 96
    deck.IMAGE_REPORT_PAYLOAD_LENGTH = PAYLOAD
    deck.key_image_format.return_value = {"size": (96, 96), "format": "JPEG", "flip": (True, True), "rotation": 0}
    deck.set_key_image.side_effect = link


class _Rig:
    def __init__(self, manager: DeviceManager, device_id: str, link: _Link, writers: list[KeyWriter]) -> None:
        self.manager = manager
        self.device_id = device_id
        self.link = link
        self.writers = writers

    def animate_all(self, spec: AnimationSpec) -> None:
        for key in range(KEYS):
            self.manager.set_image_bytes(self.device_id, key, _png())  # the poster
            self.manager.set_animation(self.device_id, key, spec)

    def run_for(self, sim_seconds: float) -> None:
        target = self.link.clock() + sim_seconds
        assert_that(wait_until(lambda: self.link.clock() >= target, timeout=60.0)).is_true()


@contextmanager
def _rig(tmp_path: Path, seconds_per_report: float) -> Iterator[_Rig]:
    clock = _SimClock()
    link = _Link(clock, seconds_per_report)
    writers: list[KeyWriter] = []

    def build(write: Callable[[int, bytes | None], None], *, adaptive: AdaptiveConfig | None = None) -> KeyWriter:
        writers.append(_SimulatedKeyWriter(write, clock, adaptive))
        return writers[-1]

    store = DeviceStateStore(data_dir=tmp_path)
    store.create(MagicMock())
    store.save_device = MagicMock()  # type: ignore[method-assign]  # mocked deck info is not storable
    context = MagicMock()
    context.device_state_store = store
    context.page_controller.active_page_id.return_value = "p1"
    manager = DeviceManager(on_key_event=lambda *_: None)
    try:
        with patch("decker.server.devices.KeyWriter", build):
            manager.create(context)
            deck = stateful_deck()
            _xl_deck(deck, link)
            with patch("decker.server.devices.manager._HardwareDeviceManager") as hardware:
                hardware.return_value.enumerate.return_value = [deck]
                device = manager.open_device(device_id_for_serial("ABC123"))
            assert device is not None
            yield _Rig(manager, device.device_id, link, writers)
    finally:
        manager.destroy()
        store.destroy()


def _spec() -> AnimationSpec:
    return AnimationSpec(_gif(), resolve_appearance({}, {"background": "#202020"}), "", 1.0)


@pytest.fixture(name="tmp_state")
def tmp_state_fixture(tmp_path: Path) -> Path:
    return tmp_path / "state"


def _settle(rig: _Rig) -> None:
    rig.animate_all(_spec())
    assert_that(wait_until(lambda: len(rig.link.keys_written()) == KEYS, timeout=60.0)).is_true()
    rig.run_for(SETTLE_S)


def test_32_animated_keys_play_through_the_device_and_stay_within_budget(tmp_state: Path) -> None:
    with _rig(tmp_state, 0.00025) as rig:
        _settle(rig)

        assert_that(rig.link.keys_written()).is_equal_to(set(range(KEYS)))
        assert_that(rig.link.busy_fraction(WINDOW_S)).is_less_than_or_equal_to(0.75)

        assert_that(rig.manager.show_page(rig.device_id, "p2")).is_true()
        stopped = len(rig.link.writes)
        time.sleep(0.2)
        assert_that(len(rig.link.writes)).is_equal_to(stopped)

        assert_that(rig.manager.show_page(rig.device_id, "p1")).is_true()
        assert_that(wait_until(lambda: len(rig.link.writes) > stopped + KEYS, timeout=30.0)).is_true()
        assert_that({key for key, _, _ in rig.link.writes[stopped:]}).is_equal_to(set(range(KEYS)))


def test_slower_link_forces_a_lower_level(tmp_state: Path) -> None:
    with _rig(tmp_state, 0.001) as rig:
        _settle(rig)

        level = rig.writers[0].level
        assert_that(LADDER.index(level)).is_greater_than(1)
        assert_that(rig.link.busy_fraction(WINDOW_S)).is_less_than_or_equal_to(STEP_DOWN_BUSY)
