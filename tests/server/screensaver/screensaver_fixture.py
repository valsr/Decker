"""A fake DeviceManager and a wired real stack (stores, engine, controller, event bus) for screensaver tests."""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from decker.common.model import DeviceHardwareInfo, KeyInfo
from decker.server.device_state_store import DeviceStateStore
from decker.server.event_bus import EventBus
from decker.server.key_assignments import KeyAssignmentStore
from decker.server.page_controller import PageController
from decker.server.pages import PageStore
from decker.server.screensaver.screensaver_controller import ScreensaverController
from decker.server.screensaver.screensaver_engine import ScreensaverEngine
from decker.server.screensaver.screensaver_store import ScreensaverStore
from decker.server.server_context import ServerContext

DEV = "dev1"
ROWS, COLS, PX = 2, 3, 24


def hw_info(device_id: str = DEV) -> DeviceHardwareInfo:
    keys = [
        KeyInfo(row=r, col=c, pixel_width=PX, pixel_height=PX, type="key") for r in range(ROWS) for c in range(COLS)
    ]
    return DeviceHardwareInfo(id=device_id, type="fake", vendor_id=0, product_id=0, num_keys=ROWS * COLS, keys=keys)


class FakeDevice:
    def get_hw_info(self) -> DeviceHardwareInfo:
        return hw_info()


class FakeDevices:
    """The hardware-facing surface of DeviceManager the screensaver uses; records what it is asked to do."""

    def __init__(self) -> None:
        self.opened: list[str] = [DEV]
        self.overlay: set[str] = set()
        self.calls: list[tuple[Any, ...]] = []

    def opened_device_ids(self) -> list[str]:
        return list(self.opened)

    def list_devices(self) -> list[DeviceHardwareInfo]:
        return [hw_info(device_id) for device_id in self.opened]

    def open_device(self, device_id: str) -> FakeDevice | None:
        return FakeDevice() if device_id in self.opened else None

    def set_overlay(self, device_id: str, active: bool) -> None:
        self.calls.append(("overlay", device_id, active))
        (self.overlay.add if active else self.overlay.discard)(device_id)

    def overlay_active(self, device_id: str) -> bool:
        return device_id in self.overlay

    def set_brightness(self, device_id: str, percent: int) -> None:
        self.calls.append(("brightness", device_id, percent))

    def write_overlay(self, device_id: str, images: list[bytes] | None) -> bool:
        self.calls.append(("write", device_id, images))
        return True

    def show_page(self, device_id: str, page_id: str) -> bool:
        self.calls.append(("show_page", device_id, page_id))
        return True

    def set_activity_hook(self, hook: Callable[[str], None] | None) -> None:
        pass

    def set_wake_hook(self, hook: Callable[[str], None] | None) -> None:
        pass


class FakeConn:
    def __init__(self) -> None:
        self.received: list[tuple[str, dict]] = []
        self.root = MagicMock()
        self.root.on_server_event = lambda event, payload: self.received.append((event, json.loads(payload)))

    def events(self, name: str) -> list[dict]:
        return [payload for event, payload in self.received if event == name]


@contextmanager
def saver_context(tmp_path: Path) -> Iterator[tuple[ServerContext, FakeDevices]]:
    """A ServerContext with real stores, event bus, engine and controller over fake devices."""
    db = tmp_path / "decker.db"
    devices = FakeDevices()
    states = DeviceStateStore(data_dir=tmp_path)
    pages, keys, store = PageStore(db_path=db), KeyAssignmentStore(db_path=db), ScreensaverStore(db_path=db)
    controller = ScreensaverController()
    page_controller = PageController()
    engine = ScreensaverEngine(store, devices, lambda device_id: "page-1", controller.notify_changed)
    ctx = ServerContext(
        device_manager=devices,  # type: ignore[arg-type]
        plugin_manager=MagicMock(),
        key_assignment_store=keys,
        device_state_store=states,
        page_store=pages,
        page_controller=page_controller,
        event_bus=EventBus(),
        screensaver_store=store,
        screensaver_controller=controller,
        screensaver_engine=engine,
    )
    managers = (states, pages, keys, store, page_controller, engine, controller)
    with patch("decker.server.event_bus.async_", side_effect=lambda method: method):
        for manager in managers:
            manager.create(ctx)
        try:
            yield ctx, devices
        finally:
            for manager in reversed(managers):
                manager.destroy()
