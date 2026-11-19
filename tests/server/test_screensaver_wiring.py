import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that

from decker.common import paths as decker_paths
from decker.common.context import ServerAppContext
from decker.server.devices.manager import DeviceManager, device_id_for_serial
from decker.server.server import ServerProcess
from tests.server import test_device_manager

_deck = test_device_manager.TestDeviceWatcher._deck  # pylint: disable=protected-access


def _enumerate(*decks):
    patcher = patch("decker.server.devices.manager._HardwareDeviceManager")
    patcher.start().return_value.enumerate.return_value = list(decks)
    return patcher


@pytest.fixture(name="manager")
def manager_fixture(tmp_path):
    context = MagicMock()
    context.page_controller.active_page_id.return_value = "p1"
    context.device_state_store.get_device.return_value = None
    dm = DeviceManager(on_key_event=lambda *_: None)
    dm.create(context)
    yield dm
    dm.destroy()


def test_open_hook_runs_after_open_outside_the_lock(manager):
    seen: list[tuple[str, bool]] = []

    def hook(device_id: str) -> None:
        free = manager._lock.acquire(blocking=False)  # pylint: disable=protected-access
        if free:
            manager._lock.release()  # pylint: disable=protected-access
        seen.append((device_id, free and threading.current_thread() is threading.main_thread()))
        assert_that(manager.opened_device_ids()).contains(device_id)  # already published

    manager.set_open_hook(hook)
    patcher = _enumerate(_deck())

    manager.check_devices()
    patcher.stop()

    assert_that(seen).is_equal_to([(device_id_for_serial("ABC123"), True)])


def test_open_hook_runs_again_for_a_reopened_device(manager):
    calls: list[str] = []
    manager.set_open_hook(calls.append)
    old = _deck(path="/dev/hidraw3")
    patcher = _enumerate(old)
    manager.check_devices()
    patcher.stop()
    old.get_serial_number.side_effect = OSError("gone")
    patcher = _enumerate()
    manager.check_devices()
    patcher.stop()
    patcher = _enumerate(_deck(path="/dev/hidraw7"))

    manager.check_devices()
    patcher.stop()

    assert_that(calls).is_equal_to([device_id_for_serial("ABC123")] * 2)


def test_open_hook_exception_does_not_break_opening(manager):
    manager.set_open_hook(MagicMock(side_effect=RuntimeError("boom")))
    patcher = _enumerate(_deck())

    manager.check_devices()
    patcher.stop()

    assert_that(manager.opened_device_ids()).is_equal_to([device_id_for_serial("ABC123")])


def test_a_cleared_open_hook_is_not_called(manager):
    hook = MagicMock()
    manager.set_open_hook(hook)
    manager.set_open_hook(None)
    patcher = _enumerate(_deck())

    manager.check_devices()
    patcher.stop()

    hook.assert_not_called()


def test_server_shutdown_wakes_an_active_device_before_the_device_manager_closes(tmp_path: Path) -> None:
    previous = decker_paths.home().parent
    decker_paths.configure(tmp_path)
    try:
        server = ServerProcess(0, 0.0, ServerAppContext(prefix=tmp_path))
        ctx, managers = server._build_context()  # pylint: disable=protected-access
        order: list[str] = []
        for manager in managers:
            original = manager.destroy
            manager.destroy = lambda m=manager, o=original: (order.append(type(m).__name__), o())  # type: ignore
        deck = _deck()
        patcher = _enumerate(deck)
        ctx.device_manager.check_devices()
        device_id = device_id_for_serial("ABC123")
        assert ctx.screensaver_engine is not None
        assert_that(ctx.screensaver_engine.activate(device_id)).is_true()
        assert_that(ctx.device_manager.overlay_active(device_id)).is_true()

        server._cleanup(ctx, managers)  # pylint: disable=protected-access
        patcher.stop()
    finally:
        decker_paths.configure(previous)

    assert_that(order.index("ScreensaverEngine")).is_less_than(order.index("DeviceManager"))
    assert_that(ctx.device_manager.overlay_active(device_id)).is_false()
    assert_that(ctx.screensaver_engine.is_active(device_id)).is_false()
