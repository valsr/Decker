import io
import logging
import sqlite3
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that
from PIL import Image

from decker.common.model import DeviceHardwareInfo, KeyInfo, ScreensaverSettings
from decker.server.screensaver import screensaver_engine
from decker.server.screensaver.screensaver_engine import ScreensaverEngine
from decker.server.screensaver.screensaver_store import ScreensaverStore

DEV = "dev1"
ROWS, COLS, PX = 2, 3, 24


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeDevice:
    def get_hw_info(self) -> DeviceHardwareInfo:
        keys = [
            KeyInfo(row=r, col=c, pixel_width=PX, pixel_height=PX, type="key") for r in range(ROWS) for c in range(COLS)
        ]
        return DeviceHardwareInfo(id=DEV, type="fake", vendor_id=0, product_id=0, num_keys=ROWS * COLS, keys=keys)


class FakeManager:
    """Records the hardware-facing calls the engine makes, with the thread each ran on."""

    def __init__(self) -> None:
        self.opened: list[str] = [DEV]
        self.device = FakeDevice()
        self.calls: list[tuple[Any, ...]] = []
        self.threads: list[threading.Thread] = []
        self.overlay: set[str] = set()
        self.activity_hook: Callable[[str], None] | None = None
        self.wake_hook: Callable[[str], None] | None = None

    def _record(self, *call: Any) -> None:
        self.calls.append(call)
        self.threads.append(threading.current_thread())

    def opened_device_ids(self) -> list[str]:
        return list(self.opened)

    def open_device(self, device_id: str) -> FakeDevice | None:
        return self.device if device_id in self.opened else None

    def set_overlay(self, device_id: str, active: bool) -> None:
        self._record("overlay", device_id, active)
        if active:
            self.overlay.add(device_id)
        else:
            self.overlay.discard(device_id)

    def overlay_active(self, device_id: str) -> bool:
        return device_id in self.overlay

    def set_brightness(self, device_id: str, percent: int) -> None:
        self._record("brightness", device_id, percent)

    def write_overlay(self, device_id: str, images: list[bytes] | None) -> bool:
        self._record("write", device_id, images)
        return True

    def show_page(self, device_id: str, page_id: str) -> bool:
        self._record("show_page", device_id, page_id)
        return True

    def set_activity_hook(self, hook: Callable[[str], None] | None) -> None:
        self.activity_hook = hook

    def set_wake_hook(self, hook: Callable[[str], None] | None) -> None:
        self.wake_hook = hook

    def names(self) -> list[str]:
        return [call[0] for call in self.calls]

    def writes(self) -> list[list[bytes] | None]:
        return [call[2] for call in self.calls if call[0] == "write"]


@pytest.fixture()
def store(tmp_path):
    s = ScreensaverStore(db_path=tmp_path / "test.db")
    s.create(MagicMock())
    yield s
    s.destroy()


@pytest.fixture()
def manager() -> FakeManager:
    return FakeManager()


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def changes() -> list[tuple[str, bool]]:
    return []


@pytest.fixture()
def engine(store, manager, clock, changes):
    eng = ScreensaverEngine(
        store, manager, lambda device_id: "page-1", lambda d, a: changes.append((d, a)), clock=clock
    )
    yield eng
    eng.destroy()


def _png(path: Path, color: tuple[int, ...], mode: str = "RGB") -> Path:
    Image.new(mode, (60, 40), color).save(path)
    return path


def _first_pixel(images: list[bytes] | None) -> tuple[int, ...]:
    assert images is not None
    with Image.open(io.BytesIO(images[0])) as image:
        pixel = image.convert("RGB").getpixel((PX // 2, PX // 2))
    assert isinstance(pixel, tuple)
    return pixel


def _set(store: ScreensaverStore, **changes: Any) -> None:
    store.set(DEV, replace(ScreensaverSettings(), **changes))


def _gallery(tmp_path: Path) -> Path:
    folder = tmp_path / "gallery"
    folder.mkdir()
    _png(folder / "a.png", (255, 0, 0))
    _png(folder / "b.png", (0, 255, 0))
    _png(folder / "c.png", (0, 0, 255))
    return folder


def test_idle_timeout_activates_after_deadline(engine, store, changes):
    _set(store, timeout_minutes=1)

    engine.tick(0.0)
    engine.tick(59.0)
    assert_that(engine.is_active(DEV)).is_false()

    engine.tick(60.0)

    assert_that(engine.is_active(DEV)).is_true()
    assert_that(changes).is_equal_to([(DEV, True)])


def test_timeout_zero_never_activates(engine, manager):
    engine.tick(0.0)
    engine.tick(100_000.0)

    assert_that(engine.is_active(DEV)).is_false()
    assert_that(manager.calls).is_empty()


def test_activity_pushes_deadline(engine, store, clock):
    _set(store, timeout_minutes=1)
    engine.tick(0.0)
    clock.now = 50.0
    engine.note_activity(DEV)

    engine.tick(70.0)
    assert_that(engine.is_active(DEV)).is_false()

    engine.tick(110.0)
    assert_that(engine.is_active(DEV)).is_true()


def test_activity_hook_and_wake_hook_registered_on_create(engine, manager):
    engine.create(MagicMock())

    assert_that(manager.activity_hook).is_not_none()
    assert_that(manager.wake_hook).is_not_none()


def test_wake_during_render_aborts_without_writes(engine, store, manager, tmp_path, monkeypatch, changes):
    _set(store, content="image", image_path=str(_png(tmp_path / "a.png", (255, 0, 0))))
    real_load = screensaver_engine.load_image

    def load_then_press(path: str, width: int, height: int) -> Image.Image:
        engine.note_activity(DEV)  # a key press while the slices are being rendered
        return real_load(path, width, height)

    monkeypatch.setattr(screensaver_engine, "load_image", load_then_press)

    assert_that(engine.activate(DEV)).is_false()
    assert_that(manager.calls).is_empty()
    assert_that(engine.is_active(DEV)).is_false()
    assert_that(changes).is_empty()


def test_deactivate_during_render_aborts_without_writes(engine, store, manager, tmp_path, monkeypatch):
    _set(store, content="image", image_path=str(_png(tmp_path / "a.png", (255, 0, 0))))
    real_load = screensaver_engine.load_image

    def load_then_wake(path: str, width: int, height: int) -> Image.Image:
        engine.deactivate(DEV)
        return real_load(path, width, height)

    monkeypatch.setattr(screensaver_engine, "load_image", load_then_wake)

    assert_that(engine.activate(DEV)).is_false()
    assert_that(manager.names()).does_not_contain("write", "overlay")


def test_activate_writes_slices_and_dims(engine, store, manager, tmp_path, changes):
    _set(store, content="image", image_path=str(_png(tmp_path / "a.png", (255, 0, 0))), saver_brightness=7)

    assert_that(engine.activate(DEV)).is_true()

    assert_that(manager.calls[0]).is_equal_to(("overlay", DEV, True))
    assert_that(manager.names()).is_equal_to(["overlay", "write", "brightness"])
    images = manager.writes()[0]
    assert_that(images).is_length(ROWS * COLS)
    assert_that(_first_pixel(images)).is_equal_to((255, 0, 0))
    assert_that(manager.calls[-1]).is_equal_to(("brightness", DEV, 7))
    assert_that(changes).is_equal_to([(DEV, True)])
    assert_that(engine.status(DEV).last_error).is_empty()


def test_rgba_image_flattened_on_black(engine, store, manager, tmp_path):
    _set(store, content="image", image_path=str(_png(tmp_path / "clear.png", (255, 255, 255, 0), "RGBA")))

    engine.activate(DEV)

    assert_that(_first_pixel(manager.writes()[0])).is_equal_to((0, 0, 0))


def test_missing_image_blanks_and_sets_last_error(engine, store, manager, tmp_path):
    _set(store, content="image", image_path=str(tmp_path / "missing.png"))

    assert_that(engine.activate(DEV)).is_true()

    assert_that(manager.writes()).is_equal_to([None])
    status = engine.status(DEV)
    assert_that(status.active).is_true()
    assert_that(status.last_error).contains("not found")
    assert_that(status.last_error).does_not_contain(str(tmp_path))


def test_empty_gallery_blanks(engine, store, manager, tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    _set(store, content="gallery", folder_path=str(folder))

    engine.activate(DEV)

    assert_that(manager.writes()).is_equal_to([None])
    assert_that(engine.status(DEV).last_error).is_not_empty()


def test_gallery_skips_unreadable_files(engine, store, manager, tmp_path):
    folder = _gallery(tmp_path)
    (folder / "0-broken.png").write_bytes(b"not a png")
    _set(store, content="gallery", folder_path=str(folder))

    engine.activate(DEV)

    assert_that(_first_pixel(manager.writes()[0])).is_equal_to((255, 0, 0))


def test_gallery_advances_per_activation(engine, store, manager, tmp_path):
    _set(store, content="gallery", folder_path=str(_gallery(tmp_path)))

    colors = []
    for _ in range(4):
        engine.activate(DEV)
        colors.append(_first_pixel(manager.writes()[-1]))
        engine.deactivate(DEV)

    assert_that(colors).is_equal_to([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 0, 0)])


def test_gallery_interval_advances_while_active(engine, store, manager, tmp_path, changes):
    _set(store, content="gallery", folder_path=str(_gallery(tmp_path)), gallery_mode="interval", gallery_minutes=1)
    engine.activate(DEV)

    engine.tick(30.0)
    assert_that(manager.writes()).is_length(1)

    engine.tick(60.0)
    assert_that(manager.writes()).is_length(2)
    assert_that(_first_pixel(manager.writes()[-1])).is_equal_to((0, 255, 0))

    engine.tick(120.0)
    assert_that(_first_pixel(manager.writes()[-1])).is_equal_to((0, 0, 255))
    assert_that(changes).is_equal_to([(DEV, True)])


def test_gallery_activation_mode_does_not_advance_on_tick(engine, store, manager, tmp_path):
    _set(store, content="gallery", folder_path=str(_gallery(tmp_path)))
    engine.activate(DEV)

    engine.tick(10_000.0)

    assert_that(manager.writes()).is_length(1)


def test_activate_works_when_timeout_zero(engine, store, manager):
    _set(store, saver_brightness=0)

    assert_that(engine.activate(DEV)).is_true()

    assert_that(manager.writes()).is_equal_to([None])
    assert_that(manager.calls[-1]).is_equal_to(("brightness", DEV, 0))
    assert_that(engine.status(DEV).last_error).is_empty()


def test_activate_unopened_device_returns_false(engine, manager):
    assert_that(engine.activate("other")).is_false()
    assert_that(manager.calls).is_empty()


def test_deactivate_restores_brightness_and_page(engine, store, manager, changes):
    _set(store, brightness=60)
    engine.activate(DEV)
    manager.calls.clear()

    assert_that(engine.deactivate(DEV)).is_true()

    assert_that(manager.calls).is_equal_to(
        [("overlay", DEV, False), ("brightness", DEV, 60), ("show_page", DEV, "page-1")]
    )
    assert_that(changes).is_equal_to([(DEV, True), (DEV, False)])
    assert_that(engine.is_active(DEV)).is_false()


def test_deactivate_when_awake_returns_false(engine, manager, changes):
    assert_that(engine.deactivate(DEV)).is_false()
    assert_that(manager.calls).is_empty()
    assert_that(changes).is_empty()


def test_deactivate_resets_idle_deadline(engine, store, clock):
    _set(store, timeout_minutes=1)
    engine.tick(0.0)
    engine.tick(60.0)
    clock.now = 100.0
    engine.deactivate(DEV)

    engine.tick(130.0)
    assert_that(engine.is_active(DEV)).is_false()
    engine.tick(160.0)
    assert_that(engine.is_active(DEV)).is_true()


def test_device_opened_while_active_wakes(engine, store, manager, changes):
    _set(store, brightness=80)
    engine.activate(DEV)
    manager.calls.clear()

    engine.device_opened(DEV)

    assert_that(manager.calls).contains(("overlay", DEV, False), ("brightness", DEV, 80), ("show_page", DEV, "page-1"))
    assert_that(engine.is_active(DEV)).is_false()
    assert_that(changes[-1]).is_equal_to((DEV, False))


def test_device_opened_while_awake_applies_brightness_and_resets_deadline(engine, store, manager, clock):
    _set(store, brightness=80, timeout_minutes=1)
    engine.tick(0.0)
    clock.now = 50.0

    engine.device_opened(DEV)

    assert_that(manager.calls).is_equal_to([("brightness", DEV, 80)])
    engine.tick(100.0)
    assert_that(engine.is_active(DEV)).is_false()


def test_destroy_wakes_active_devices(store, manager, clock, changes):
    eng = ScreensaverEngine(
        store, manager, lambda device_id: "page-1", lambda d, a: changes.append((d, a)), clock=clock
    )
    eng.create(MagicMock())
    eng.activate(DEV)

    eng.destroy()

    assert_that(changes).is_equal_to([(DEV, True), (DEV, False)])
    assert_that(manager.overlay).is_empty()
    assert_that(manager.activity_hook).is_none()
    assert_that(manager.wake_hook).is_none()


def test_apply_settings_sets_normal_brightness_when_awake_only(engine, store, manager):
    _set(store, brightness=40)
    engine.apply_settings(DEV)
    assert_that(manager.calls).is_equal_to([("brightness", DEV, 40)])

    engine.activate(DEV)
    manager.calls.clear()
    engine.apply_settings(DEV)

    assert_that(manager.calls).is_empty()


def test_apply_settings_reschedules(engine, store, clock):
    engine.tick(0.0)
    clock.now = 500.0
    _set(store, timeout_minutes=1)

    engine.apply_settings(DEV)

    engine.tick(520.0)
    assert_that(engine.is_active(DEV)).is_false()
    engine.tick(560.0)
    assert_that(engine.is_active(DEV)).is_true()


def test_wake_request_handled_off_caller_thread(store, manager, clock):
    done = threading.Event()

    def on_change(device_id: str, active: bool) -> None:
        if not active:
            done.set()

    eng = ScreensaverEngine(store, manager, lambda device_id: "page-1", on_change, clock=clock)
    eng.create(MagicMock())
    try:
        eng.activate(DEV)
        start = len(manager.calls)
        assert manager.wake_hook is not None

        manager.wake_hook(DEV)

        assert_that(done.wait(timeout=5)).is_true()
        deactivation_threads = manager.threads[start:]
        assert_that(deactivation_threads).is_not_empty()
        assert_that(deactivation_threads).does_not_contain(threading.current_thread())
        assert_that(manager.calls[start]).is_equal_to(("overlay", DEV, False))
    finally:
        eng.destroy()


def test_corrupt_settings_row_falls_back_to_defaults(engine, store, manager, tmp_path, caplog):
    with sqlite3.connect(tmp_path / "test.db") as conn:
        conn.execute(
            "INSERT INTO screensaver_settings (device_id, settings_json) VALUES (?, ?)", (DEV, '{"brightness": 0}')
        )
    caplog.set_level(logging.WARNING)

    assert_that(engine.activate(DEV)).is_true()
    engine.deactivate(DEV)
    engine.tick(0.0)

    defaults = ScreensaverSettings()
    assert_that(manager.calls).contains(("brightness", DEV, defaults.saver_brightness))
    assert_that(manager.calls).contains(("brightness", DEV, defaults.brightness))
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and DEV in r.getMessage()]
    assert_that(warnings).is_length(1)


def test_failed_overlay_write_still_marks_active_so_tick_does_not_retry(engine, store, manager, changes):
    _set(store, timeout_minutes=1)
    manager.write_overlay = MagicMock(side_effect=RuntimeError("usb"))
    engine.tick(0.0)

    engine.tick(60.0)  # the activation fails after the overlay is set
    engine.tick(61.0)
    engine.tick(62.0)

    assert_that(manager.names().count("overlay")).is_equal_to(1)
    assert_that(engine.is_active(DEV)).is_true()
    assert_that(changes).is_equal_to([(DEV, True)])
    assert_that(engine.deactivate(DEV)).is_true()
    assert_that(manager.overlay).is_empty()


def test_failed_overlay_set_restarts_the_countdown(engine, store, manager, clock):
    _set(store, timeout_minutes=1)
    manager.set_overlay = MagicMock(side_effect=RuntimeError("usb"))
    engine.tick(0.0)
    clock.now = 60.0

    engine.tick(60.0)
    engine.tick(61.0)

    assert_that(manager.set_overlay.call_count).is_equal_to(1)
    assert_that(engine.is_active(DEV)).is_false()
    engine.tick(120.0)
    assert_that(manager.set_overlay.call_count).is_equal_to(2)


def test_deactivate_notifies_even_when_the_redraw_fails(engine, store, manager, changes):
    engine.activate(DEV)
    manager.show_page = MagicMock(side_effect=RuntimeError("usb"))

    with pytest.raises(RuntimeError):
        engine.deactivate(DEV)

    assert_that(changes).is_equal_to([(DEV, True), (DEV, False)])
    assert_that(engine.is_active(DEV)).is_false()


def test_destroy_wakes_a_device_whose_overlay_is_set_but_not_marked_active(store, manager, clock, changes):
    _set(store, saver_brightness=0, brightness=70)
    eng = ScreensaverEngine(
        store, manager, lambda device_id: "page-1", lambda d, a: changes.append((d, a)), clock=clock
    )
    eng.create(MagicMock())
    eng.note_activity(DEV)  # the runtime exists, but nothing marked it active
    manager.overlay.add(DEV)

    eng.destroy()

    assert_that(manager.overlay).is_empty()
    assert_that(manager.calls).contains(("brightness", DEV, 70), ("show_page", DEV, "page-1"))
    assert_that(changes).is_equal_to([(DEV, False)])


def test_destroy_handles_a_wake_still_pending(store, manager, clock, changes):
    eng = ScreensaverEngine(
        store, manager, lambda device_id: "page-1", lambda d, a: changes.append((d, a)), clock=clock
    )
    manager.overlay.add("other")
    eng.request_wake("other")  # never created, so no worker drains it

    eng.destroy()

    assert_that(manager.overlay).is_empty()
    assert_that(changes).is_equal_to([("other", False)])


def test_unreadable_single_image_is_logged_once_per_activation(engine, store, tmp_path, caplog):
    _set(store, content="image", image_path=str(tmp_path / "missing.png"))
    caplog.set_level(logging.WARNING)

    engine.activate(DEV)
    engine.deactivate(DEV)
    engine.activate(DEV)

    logged = [r for r in caplog.records if "missing.png" in r.getMessage()]
    assert_that(logged).is_length(2)
    assert_that([r.getMessage() for r in logged]).does_not_contain(str(tmp_path))


def test_reopen_during_the_brightness_write_leaves_the_deck_awake(engine, store, manager, changes):
    _set(store, brightness=80, saver_brightness=5)
    real_set_brightness = manager.set_brightness
    reopened: list[bool] = []

    def set_brightness(device_id: str, percent: int) -> None:
        if not reopened:  # DeviceManager.set_brightness reopens the deck; its open hook runs device_opened here
            reopened.append(True)
            engine.device_opened(device_id)
        real_set_brightness(device_id, percent)

    manager.set_brightness = set_brightness

    assert_that(engine.activate(DEV)).is_false()

    assert_that(manager.overlay).is_empty()
    assert_that(engine.is_active(DEV)).is_false()
    assert_that([c for c in manager.calls if c[0] == "brightness"][-1]).is_equal_to(("brightness", DEV, 80))
    assert_that(changes).is_equal_to([(DEV, False)])


def _blind_device() -> FakeDevice:
    device = FakeDevice()
    info = device.get_hw_info()
    blind = replace(info, keys=[replace(key, pixel_width=0, pixel_height=0) for key in info.keys])
    device.get_hw_info = lambda: blind  # type: ignore[method-assign]
    return device


def test_deck_without_key_screens_is_unsupported(engine, store, manager, monkeypatch):
    _set(store, timeout_minutes=1)
    manager.device = _blind_device()
    real_open = manager.open_device
    opens: list[str] = []

    def open_device(device_id: str) -> FakeDevice | None:
        opens.append(device_id)
        return real_open(device_id)

    monkeypatch.setattr(manager, "open_device", open_device)

    assert_that(engine.activate(DEV)).is_false()
    engine.tick(0.0)
    engine.tick(60.0)
    engine.tick(120.0)

    assert_that(manager.overlay).is_empty()
    assert_that(manager.names()).does_not_contain("overlay", "write")
    assert_that(engine.is_active(DEV)).is_false()
    assert_that(opens).is_length(1)  # the idle timer never tries again


def test_gallery_scans_the_folder_once_per_render(engine, store, manager, tmp_path, monkeypatch):
    folder = tmp_path / "broken"
    folder.mkdir()
    for index in range(10):
        (folder / f"{index}.png").write_bytes(b"not a png")
    _set(store, content="gallery", folder_path=str(folder))
    real_iterdir = Path.iterdir
    scans: list[Path] = []

    def iterdir(self: Path):
        scans.append(self)
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", iterdir)

    engine.activate(DEV)

    assert_that(scans).is_length(1)
    assert_that(manager.writes()).is_equal_to([None])


def test_render_of_a_large_image_never_converts_it_at_full_size(engine, store, manager, tmp_path, monkeypatch):
    Image.new("RGB", (3000, 2000), "red").save(tmp_path / "big.png")
    _set(store, content="image", image_path=str(tmp_path / "big.png"))
    seen: list[tuple[int, int]] = []
    for name in ("convert", "resize", "copy", "alpha_composite"):
        original = getattr(Image.Image, name)

        def spy(self: Image.Image, *args: Any, _original: Any = original, **kwargs: Any) -> Any:
            seen.append(self.size)
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(Image.Image, name, spy)

    assert_that(engine.activate(DEV)).is_true()

    assert_that(_first_pixel(manager.writes()[0])).is_equal_to((255, 0, 0))
    assert_that(max(w * h for w, h in seen)).is_less_than_or_equal_to(300 * 200)
