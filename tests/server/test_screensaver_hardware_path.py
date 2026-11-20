"""The screensaver through the real server wiring: real DeviceManager, engine and controller over a fake deck."""

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from assertpy import assert_that

from decker.common import paths as decker_paths
from decker.common.context import ServerAppContext
from decker.common.model import ScreensaverSettings
from decker.server.devices.manager import device_id_for_serial
from decker.server.server import ServerProcess
from decker.server.server_context import ServerContext
from tests.server import test_device_manager

_deck = test_device_manager.TestDeviceWatcher._deck  # pylint: disable=protected-access
_DEVICE_ID = device_id_for_serial("ABC123")


@contextmanager
def _server(tmp_path: Path, deck: MagicMock) -> Iterator[ServerContext]:
    previous = decker_paths.home().parent
    decker_paths.configure(tmp_path)
    patcher = patch("decker.server.devices.manager._HardwareDeviceManager")
    patcher.start().return_value.enumerate.return_value = [deck]
    try:
        server = ServerProcess(0, 0.0, ServerAppContext(prefix=tmp_path))
        ctx, managers = server._build_context()  # pylint: disable=protected-access
        try:
            yield ctx
        finally:
            server._cleanup(ctx, managers)  # pylint: disable=protected-access
    finally:
        patcher.stop()
        decker_paths.configure(previous)


def test_opening_a_device_applies_its_normal_brightness(tmp_path: Path) -> None:
    deck = _deck()
    with _server(tmp_path, deck) as ctx:
        assert ctx.screensaver_store is not None
        ctx.screensaver_store.set(_DEVICE_ID, ScreensaverSettings(brightness=55))

        ctx.device_manager.check_devices()

        deck.set_brightness.assert_called_with(55)


def test_a_hardware_key_press_wakes_the_deck_through_the_engine_worker(tmp_path: Path) -> None:
    deck = _deck()
    with _server(tmp_path, deck) as ctx:
        assert ctx.screensaver_store is not None and ctx.screensaver_engine is not None
        ctx.screensaver_store.set(_DEVICE_ID, ScreensaverSettings(brightness=60, saver_brightness=3))
        ctx.device_manager.check_devices()
        woke = threading.Event()
        pushed: list[tuple[str, Any]] = []

        def push(event: str, payload: str) -> None:
            pushed.append((event, json.loads(payload)))
            if event == "screensaver_changed" and not json.loads(payload)["active"]:
                woke.set()

        ctx.event_bus.push = push  # type: ignore[method-assign,assignment]
        assert_that(ctx.screensaver_engine.activate(_DEVICE_ID)).is_true()
        deck.set_brightness.assert_called_with(3)
        callback = deck.set_key_callback.call_args.args[0]

        callback(deck, 0, True)  # the HID reader thread's callback

        assert_that(woke.wait(timeout=5)).is_true()
        callback(deck, 0, False)
        assert_that(ctx.device_manager.overlay_active(_DEVICE_ID)).is_false()
        assert_that(ctx.screensaver_engine.is_active(_DEVICE_ID)).is_false()
        deck.set_brightness.assert_called_with(60)
        assert_that([event for event, _ in pushed]).does_not_contain("key_event")  # the wake press never fired
