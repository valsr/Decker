import base64
import io
import json
import os
import shutil
import signal
import stat
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that
from PIL import Image

from decker.common.model import DeviceHardwareInfo, KeyInfo, PageInfo
from decker.plugin.events import PluginLoadFailedEvent
from decker.plugin.gestures import Gesture
from decker.plugin.loader import InstalledPlugin
from decker.plugin.manifest import PluginManifest, StateSpec
from decker.plugin.protocol import Message
from decker.plugin.runtime.supervisor import SupervisorPolicy
from decker.plugin.settings_store import PluginSettingsStore
from decker.plugin.target import ActionTarget
from decker.server.appearance import compose_key_image, resolve_appearance
from decker.server.devices.state import DeviceState
from decker.server.plugins import PluginManager

_RECORDER = f"""#!{sys.executable}
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(here, "crash")):
    sys.exit(1)
for line in sys.stdin:
    with open(os.path.join(here, "received.log"), "a") as log:
        log.write(line)
    event = json.loads(line)["event"]
    if event == "hello":
        print(json.dumps({{"event": "ready"}}), flush=True)
    elif event == "ping":
        print(json.dumps({{"event": "pong"}}), flush=True)
    elif event == "shutdown":
        break
"""

_REC_MANIFEST: dict[str, Any] = {
    "format": 1,
    "id": "com.decker.rec",
    "name": "Recorder",
    "version": "1.0.0",
    "author": "Decker",
    "runtime": {"type": "executable", "entry": "rec.py"},
    "contributes": {
        "actions": [
            {
                "id": "com.decker.rec.show",
                "name": "Show",
                "tooltip": "Shows things",
                "settings": [
                    {"key": "n", "type": "int", "label": "N", "default": 5, "min": 1, "max": 9},
                    {"key": "t", "type": "text", "label": "T", "default": "x"},
                ],
            }
        ]
    },
}

_REC_MANIFEST["contributes"]["actions"].append(
    {
        "id": "com.decker.rec.tpl",
        "name": "Templated",
        "settings": [
            {"key": "label", "type": "text", "label": "Label", "default": "", "template": True},
            {"key": "plain", "type": "text", "label": "Plain", "default": ""},
            {"key": "style", "type": "text_style", "label": "Style", "template": True},
            {"key": "where", "type": "page", "label": "Where"},
        ],
    }
)
_STATIC_MANIFEST: dict[str, Any] = {
    "format": 1,
    "id": "com.t.static",
    "name": "Static",
    "version": "1.0.0",
    "author": "Decker",
    "contributes": {
        "actions": [
            {
                "id": "com.t.static.preset",
                "name": "Preset",
                "static": True,
                "appearance": {"background": "#336699", "title": {"text": "Hi", "position": "middle"}},
            }
        ]
    },
}
_MIXED_MANIFEST = {
    **_REC_MANIFEST,
    "id": "com.t.mixed",
    "contributes": {
        "actions": [
            {"id": "com.t.mixed.live", "name": "Live"},
            {"id": "com.t.mixed.preset", "name": "Preset", "static": True, "appearance": {"background": "#336699"}},
        ]
    },
}
_STATIC_ACTION = "com.t.static.preset"

_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "plugins" / "com.decker.testfixture"
_COUNTER = "com.decker.testfixture"
_COUNTER_ACTION = "com.decker.testfixture.counter"
_REC_ACTION = "com.decker.rec.show"
_FAST = SupervisorPolicy(idle_grace_s=30.0, backoff_s=(0.05,), max_crashes=1, ping_interval_s=30.0)
_RESTARTING = SupervisorPolicy(idle_grace_s=30.0, backoff_s=(0.05,), max_crashes=5, ping_interval_s=30.0)


def _target(plugin: str, action: str, context: str = "ctx-1", key: int = 0) -> ActionTarget:
    return ActionTarget(plugin, action, context, "dev-1", key)


COUNTER_TARGET = _target(_COUNTER, _COUNTER_ACTION)
REC_TARGET = _target("com.decker.rec", _REC_ACTION)
STATIC_TARGET = _target("com.t.static", _STATIC_ACTION, "ctx-static", 1)
TPL_TARGET = _target("com.decker.rec", "com.decker.rec.tpl", "ctx-tpl", 4)
MIXED_STATIC_TARGET = _target("com.t.mixed", "com.t.mixed.preset", "ctx-mixed", 2)


class FakeDevice:
    def __init__(self, manager: "FakeDeviceManager") -> None:
        self._manager = manager

    def get_hw_info(self) -> DeviceHardwareInfo:
        keys = [KeyInfo(row=i // 3, col=i % 3, pixel_width=72, pixel_height=72, type="key") for i in range(6)]
        return DeviceHardwareInfo(id="dev-1", type="StreamDeck", vendor_id=1, product_id=2, num_keys=6, keys=keys)

    def clear_key_image(self, key_index: int) -> None:
        self._manager.cleared.append(key_index)


class FakeDeviceManager:
    def __init__(self) -> None:
        self.state = DeviceState("dev-1", None, lambda _k: "up", "p1")  # type: ignore[arg-type,return-value]
        self.cleared: list[int] = []
        self.hardware_images: list[tuple[int, bytes]] = []

    def get_device_state(self, device_id: str) -> DeviceState | None:
        return self.state if device_id == "dev-1" else None

    def open_device(self, _device_id: str) -> FakeDevice:
        return FakeDevice(self)

    def list_devices(self) -> list[DeviceHardwareInfo]:
        return [DeviceHardwareInfo(id="dev-1", type="StreamDeck", vendor_id=1, product_id=2, num_keys=6)]

    def set_image_bytes(self, _device_id: str, key_index: int, image: bytes) -> None:
        self.hardware_images.append((key_index, image))
        self.state.update_key_image(key_index, image)

    def clear_key_state(self, _device_id: str, key_index: int) -> None:
        self.state.clear_key(key_index)


class FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def push(self, event_type: str, payload: str) -> None:
        self.events.append((event_type, json.loads(payload)))

    def of(self, event_type: str) -> list[dict]:
        return [p for t, p in self.events if t == event_type]


_BARE_COUNTER = compose_key_image(resolve_appearance({"background": "#1f618d"}, {}), None, "")


def _pixel(png: bytes | None, x: int, y: int) -> tuple[int, ...]:
    assert png is not None
    return Image.open(io.BytesIO(png)).convert("RGB").getpixel((x, y))  # type: ignore[return-value]


def _png(color: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


_RED_PNG = _png("#ff0000")


def _wait_for(predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class FakePages:
    """Stands in for both the page store and the page controller of one device."""

    def __init__(self) -> None:
        self.pages = {"dev-1": [PageInfo("p1", "Home"), PageInfo("p2", "Settings"), PageInfo("p3", "Media")]}
        self.active = {"dev-1": "p2"}
        self.activations: list[tuple[str, str]] = []

    def list_pages(self, device_id: str) -> list[PageInfo]:
        return list(self.pages.get(device_id, []))

    def active_page_id(self, device_id: str) -> str:
        return self.active.get(device_id, "")

    def activate(self, device_id: str, page_id: str) -> bool:
        self.activations.append((device_id, page_id))
        self.active[device_id] = page_id
        return True

    def rename(self, page_id: str, name: str, device_id: str = "dev-1") -> None:
        self.pages[device_id] = [
            PageInfo(p.page_id, name if p.page_id == page_id else p.name) for p in self.pages[device_id]
        ]


class Env:
    """A running PluginManager over a fake device, with the recorder plugin installed."""

    def __init__(self, tmp_path, policy: SupervisorPolicy = _FAST) -> None:
        self.plugins_dir = tmp_path / "plugins"
        self.rec_dir = self.plugins_dir / "com.decker.rec"
        self.rec_dir.mkdir(parents=True)
        (self.rec_dir / "manifest.json").write_text(json.dumps(_REC_MANIFEST))
        script = self.rec_dir / "rec.py"
        script.write_text(_RECORDER)
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        shutil.copytree(_FIXTURE_DIR, self.plugins_dir / _COUNTER)
        (self.plugins_dir / "com.t.static").mkdir()
        (self.plugins_dir / "com.t.static" / "manifest.json").write_text(json.dumps(_STATIC_MANIFEST))
        self.mixed_dir = self.plugins_dir / "com.t.mixed"
        shutil.copytree(self.rec_dir, self.mixed_dir)
        (self.mixed_dir / "manifest.json").write_text(json.dumps(_MIXED_MANIFEST))
        self.pages = FakePages()
        self.dm = FakeDeviceManager()
        self.bus = FakeBus()
        self.persisted: list[tuple[ActionTarget, dict]] = []
        self.manager = PluginManager(self.plugins_dir, policy, PluginSettingsStore(tmp_path / "plugins.db"))
        context = SimpleNamespace(
            device_manager=self.dm,
            event_bus=self.bus,
            page_controller=self.pages,
            page_store=self.pages,
            key_assignment_store=MagicMock(),
        )
        self.manager.create(context)  # type: ignore[arg-type]
        self.manager.settings_persister = lambda target, settings: self.persisted.append((target, settings))

    def received(self, event: str | None = None) -> list[dict]:
        log = self.rec_dir / "received.log"
        if not log.exists():
            return []
        messages = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
        return [m for m in messages if event is None or m["event"] == event]

    def label(self, key: int = 0) -> str:
        return self.dm.state.get_key_state(key).label

    def image(self, key: int = 0) -> bytes | None:
        return self.dm.state.get_key_state(key).image

    def counter_drawn(self) -> bool:
        """True once the counter plugin's own image has been composed over the bare background."""
        return self.image() not in (None, _BARE_COUNTER)

    def process_pid(self, plugin_id: str) -> int:
        entry = self.manager._supervisor._entries[plugin_id]  # pylint: disable=protected-access
        assert entry.process is not None and entry.process.pid is not None
        return entry.process.pid


@pytest.fixture(name="env")
def env_fixture(tmp_path):
    environment = Env(tmp_path)
    yield environment
    environment.manager.destroy()


@pytest.fixture(name="restarting_env")
def restarting_env_fixture(tmp_path):
    environment = Env(tmp_path, _RESTARTING)
    yield environment
    environment.manager.destroy()


class TestListing:
    def test_list_actions_includes_settings_schema_and_tooltip(self, env):
        actions = {a["action_uuid"]: a for a in env.manager.list_actions()}

        rec = actions[_REC_ACTION]
        assert_that(rec["plugin_uuid"]).is_equal_to("com.decker.rec")
        assert_that(rec["plugin_name"]).is_equal_to("Recorder")
        assert_that(rec["action_name"]).is_equal_to("Show")
        assert_that(rec["tooltip"]).is_equal_to("Shows things")
        assert_that(rec["icon_b64"]).is_equal_to("")
        assert_that(rec["settings_schema"][0]).is_equal_to(
            {"key": "n", "type": "int", "label": "N", "default": 5, "min": 1, "max": 9}
        )
        counter = actions[_COUNTER_ACTION]
        assert base64.b64decode(counter["icon_b64"]).startswith(b"\x89PNG")
        assert_that(counter["tooltip"]).is_equal_to("Press to count, long press to reset")
        keys = [e.get("key") for e in counter["settings_schema"]]
        assert_that(keys).contains("step", "double_step", "max")
        json.dumps(counter["settings_schema"])

    def test_action_icons_are_read_once(self, env, monkeypatch):
        env.manager.list_actions()
        monkeypatch.setattr("decker.server.plugins.read_icon", MagicMock(side_effect=AssertionError("re-read")))

        assert_that(env.manager.list_actions()).is_not_empty()

    def test_installed_plugins_are_loaded(self, env):
        plugins = {p.manifest.id for p in env.manager.plugins()}

        assert_that(plugins).is_equal_to(
            {_COUNTER, "com.decker.rec", "com.t.static", "com.t.mixed", "com.decker.blank"}
        )
        assert_that(env.manager.load_failures()).is_empty()

    def test_key_for_missing_plugin_keeps_assignment_and_label(self, env):
        missing = _target("com.example.gone", "com.example.gone.act")

        env.manager.activate_action(missing)

        assert_that(env.label()).is_equal_to("Plugin missing")
        assert_that(env.dm.cleared).contains(0)
        assert_that(env.manager.live_targets("com.example.gone")).is_empty()

    def test_missing_label_is_cleared_when_the_plugin_is_installed(self, env):
        removed = next(p for p in env.manager.plugins() if p.manifest.id == "com.decker.rec")
        env.manager.remove_plugin("com.decker.rec")
        env.manager.activate_action(REC_TARGET)
        assert_that(env.label()).is_equal_to("Plugin missing")

        env.manager.add_plugin(removed)
        env.manager.activate_action(REC_TARGET)

        assert_that(env.label()).is_equal_to("")
        assert _wait_for(lambda: env.received("will_appear"))

    def test_key_of_plugin_that_failed_to_load_says_failed(self, env):
        env.manager._failures.append(
            PluginLoadFailedEvent("com.example.broken", "bad manifest")
        )  # pylint: disable=protected-access

        env.manager.activate_action(_target("com.example.broken", "com.example.broken.act"))

        assert_that(env.label()).is_equal_to("Plugin failed")

    def test_complete_settings_fills_defaults(self, env):
        assert_that(env.manager.complete_settings(REC_TARGET, {"n": "3", "junk": 1})).is_equal_to({"n": 3, "t": "x"})

    def test_remove_plugin_forgets_it_and_its_live_instances(self, env):
        env.manager.activate_action(REC_TARGET)

        env.manager.remove_plugin("com.decker.rec")

        assert_that(env.manager.live_targets("com.decker.rec")).is_empty()
        assert_that(env.manager.list_actions()).extracting("action_uuid").does_not_contain(_REC_ACTION)

    def test_add_plugin_makes_actions_available(self, env):
        removed = next(p for p in env.manager.plugins() if p.manifest.id == "com.decker.rec")
        env.manager.remove_plugin("com.decker.rec")

        env.manager.add_plugin(removed)

        assert_that(env.manager.list_actions()).extracting("action_uuid").contains(_REC_ACTION)


class TestWillAppear:
    def test_activate_sends_will_appear_with_complete_settings(self, env):
        env.manager.store_settings(REC_TARGET, {"n": "7", "junk": True})

        env.manager.activate_action(REC_TARGET)

        assert _wait_for(lambda: env.received("will_appear"))
        message = env.received("will_appear")[0]
        assert_that(message["context"]).is_equal_to("ctx-1")
        assert_that(message["payload"]).is_equal_to(
            {
                "action": _REC_ACTION,
                "device": "dev-1",
                "key": {"index": 0, "column": 0, "row": 0},
                "settings": {"n": 7, "t": "x"},
                "state": 0,
            }
        )
        assert_that(env.received("hello")[0]["payload"]["plugin_id"]).is_equal_to("com.decker.rec")

    def test_key_column_and_row_come_from_the_device_layout(self, env):
        env.manager.activate_action(_target("com.decker.rec", _REC_ACTION, "ctx-5", key=4))

        assert _wait_for(lambda: env.received("will_appear"))
        assert_that(env.received("will_appear")[0]["payload"]["key"]).is_equal_to({"index": 4, "column": 1, "row": 1})

    def test_only_one_will_appear_on_first_start(self, env):
        env.manager.activate_action(REC_TARGET)
        assert _wait_for(lambda: env.received("will_appear"))
        time.sleep(0.3)

        assert_that(env.received("will_appear")).is_length(1)

    def test_unknown_action_is_ignored(self, env):
        env.manager.activate_action(_target("com.decker.rec", "com.decker.rec.nope"))

        assert_that(env.manager.live_targets("com.decker.rec")).is_empty()

    def test_deactivate_sends_will_disappear_and_releases(self, env):
        env.manager.activate_action(REC_TARGET)
        assert _wait_for(lambda: env.received("will_appear"))

        env.manager.deactivate_action(REC_TARGET)

        assert _wait_for(lambda: env.received("will_disappear"))
        assert_that(env.received("will_disappear")[0]["context"]).is_equal_to("ctx-1")
        assert_that(env.manager.live_targets("com.decker.rec")).is_empty()
        entry = env.manager._supervisor._entries["com.decker.rec"]  # pylint: disable=protected-access
        assert_that(entry.refs).is_equal_to(0)

    def test_ready_after_restart_replays_will_appear_for_live_contexts(self, restarting_env):
        restarting_env.manager.activate_action(REC_TARGET)
        assert _wait_for(lambda: restarting_env.received("will_appear"))

        os.kill(restarting_env.process_pid("com.decker.rec"), signal.SIGKILL)

        assert _wait_for(lambda: len(restarting_env.received("will_appear")) == 2)
        assert_that(restarting_env.received("will_appear")[1]["context"]).is_equal_to("ctx-1")

    def test_device_connected_sent_after_ready(self, env):
        env.manager.activate_action(REC_TARGET)

        assert _wait_for(lambda: env.received("device_connected"))
        assert_that(env.received("device_connected")[0]["payload"]).is_equal_to({"device": "dev-1"})
        events = [m["event"] for m in env.received()]
        assert_that(events.index("device_connected")).is_greater_than(events.index("will_appear"))


class TestCounterEndToEnd:
    def test_press_reaches_plugin_and_image_reaches_sink(self, env):
        env.manager.activate_action(COUNTER_TARGET)
        assert _wait_for(env.counter_drawn)
        first = env.image()

        env.manager.dispatch_key_down(COUNTER_TARGET)
        env.manager.dispatch_key_up(COUNTER_TARGET)

        assert _wait_for(lambda: env.image() != first)
        assert env.image().startswith(b"\x89PNG")
        assert_that(env.dm.hardware_images[-1][0]).is_equal_to(0)

    def test_set_gestures_changes_recognizer_registration(self, env):
        env.manager.store_settings(COUNTER_TARGET, {"double_step": 5})
        env.manager.activate_action(COUNTER_TARGET)
        assert _wait_for(env.counter_drawn)
        live = env.manager._live["ctx-1"]  # pylint: disable=protected-access
        assert _wait_for(lambda: Gesture.DOUBLE_PRESS in live.gestures)
        first = env.image()

        env.manager.dispatch_key_down(COUNTER_TARGET)
        env.manager.dispatch_key_up(COUNTER_TARGET)
        time.sleep(0.15)
        assert_that(env.image()).is_equal_to(first)  # press is held back by the double-press window

        assert _wait_for(lambda: env.image() != first)

    def test_press_is_immediate_without_double_step(self, env):
        env.manager.activate_action(COUNTER_TARGET)
        assert _wait_for(env.counter_drawn)
        live = env.manager._live["ctx-1"]  # pylint: disable=protected-access
        assert_that(live.gestures).does_not_contain(Gesture.DOUBLE_PRESS)

    def test_settings_changed_is_applied_and_redraws(self, env):
        env.manager.activate_action(COUNTER_TARGET)
        assert _wait_for(env.counter_drawn)
        first = env.image()

        env.manager.store_settings(COUNTER_TARGET, {"step": 5})
        env.manager.dispatch_settings_changed(COUNTER_TARGET)
        env.manager.dispatch_key_down(COUNTER_TARGET)
        env.manager.dispatch_key_up(COUNTER_TARGET)

        assert _wait_for(lambda: env.image() != first)

    def test_set_image_for_disappeared_context_is_dropped(self, env):
        env.manager.activate_action(COUNTER_TARGET)
        assert _wait_for(env.counter_drawn)
        env.manager.deactivate_action(COUNTER_TARGET)
        sent_before = list(env.dm.hardware_images)
        image_before = env.image()
        stale = base64.b64encode(b"stale-image").decode()

        env.manager._on_plugin_message(  # pylint: disable=protected-access
            _COUNTER, Message("set_image", "ctx-1", {"image": stale, "format": "png"})
        )

        assert_that(env.dm.hardware_images).is_equal_to(sent_before)
        assert_that(env.image()).is_equal_to(image_before)

    def test_set_image_from_another_plugin_is_dropped(self, env):
        env.manager.activate_action(COUNTER_TARGET)
        assert _wait_for(env.counter_drawn)
        sent_before = list(env.dm.hardware_images)

        env.manager._on_plugin_message(  # pylint: disable=protected-access
            "com.decker.rec", Message("set_image", "ctx-1", {"image": base64.b64encode(b"x").decode()})
        )

        assert_that(env.dm.hardware_images).is_equal_to(sent_before)

    def test_null_image_falls_back_to_the_bare_composition(self, env):
        env.manager.activate_action(COUNTER_TARGET)
        assert _wait_for(env.counter_drawn)

        env.manager._on_plugin_message(  # pylint: disable=protected-access
            _COUNTER, Message("set_image", "ctx-1", {"image": None})
        )

        assert_that(env.image()).is_equal_to(_BARE_COUNTER)

    def test_invalid_base64_image_is_dropped(self, env):
        env.manager.activate_action(COUNTER_TARGET)
        assert _wait_for(env.counter_drawn)
        sent_before = list(env.dm.hardware_images)

        env.manager._on_plugin_message(  # pylint: disable=protected-access
            _COUNTER, Message("set_image", "ctx-1", {"image": "***not base64***"})
        )

        assert_that(env.dm.hardware_images).is_equal_to(sent_before)


_DOT_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    b'<path fill="currentColor" d="M0 0h10v10H0z"/></svg>'
)
_PACK_ID = "com.t.ip.icons"
_DOT_REF = f"pack:{_PACK_ID}/dot.svg"


def _install_pack(env, tmp_path) -> InstalledPlugin:
    root = tmp_path / "ip"
    (root / "pack").mkdir(parents=True)
    (root / "pack" / "dot.svg").write_bytes(_DOT_SVG)
    manifest = PluginManifest.from_dict(
        {
            "format": 1,
            "id": "com.t.ip",
            "name": "IP",
            "version": "1.0.0",
            "author": "a",
            "description": "d",
            "contributes": {"icon_packs": [{"id": _PACK_ID, "name": "Pack", "path": "pack"}]},
        }
    )
    plugin = InstalledPlugin(manifest, root)
    env.manager.icon_packs.register(plugin)
    return plugin


def _icon_env(env, tmp_path):
    _install_pack(env, tmp_path)
    env.manager.activate_action(COUNTER_TARGET)
    assert _wait_for(env.counter_drawn)
    live = env.manager._live["ctx-1"]  # pylint: disable=protected-access
    live.plugin_image = None
    env.manager.set_appearance(COUNTER_TARGET, {})
    return live


def _send_set_image(env, payload: dict) -> None:
    env.manager._on_plugin_message(_COUNTER, Message("set_image", "ctx-1", payload))  # pylint: disable=protected-access


class TestIconOverride:
    def test_override_replaces_the_static_default_icon(self, env, tmp_path):
        _icon_env(env, tmp_path)

        env.manager.set_appearance(COUNTER_TARGET, {"icon": {"ref": _DOT_REF, "color": "#ff0000"}})

        assert_that(_pixel(env.image(), 72, 72)).is_equal_to((255, 0, 0))

    def test_plugin_image_beats_the_override(self, env, tmp_path):
        _icon_env(env, tmp_path)
        _send_set_image(env, {"image": base64.b64encode(_RED_PNG).decode(), "format": "png"})
        before = env.image()

        env.manager.set_appearance(COUNTER_TARGET, {"icon": {"ref": _DOT_REF, "color": "#00ff00"}})

        assert_that(env.image()).is_equal_to(before)

    def test_plugin_icon_beats_the_override(self, env, tmp_path):
        _icon_env(env, tmp_path)
        _send_set_image(env, {"icon": _DOT_REF, "color": "#ff0000"})

        env.manager.set_appearance(COUNTER_TARGET, {"icon": {"ref": _DOT_REF, "color": "#00ff00"}})

        assert_that(_pixel(env.image(), 72, 72)).is_equal_to((255, 0, 0))

    def test_override_to_an_unknown_pack_falls_back_to_the_default(self, env, tmp_path):
        _icon_env(env, tmp_path)

        env.manager.set_appearance(COUNTER_TARGET, {"icon": {"ref": "pack:no.such/x.svg", "color": "#ff0000"}})

        assert_that(env.image()).is_equal_to(_BARE_COUNTER)


class TestSetImageIcon:
    def test_icon_reference_composes_the_pack_icon_in_the_colour(self, env, tmp_path):
        _icon_env(env, tmp_path)

        _send_set_image(env, {"icon": _DOT_REF, "color": "#ff0000"})

        assert_that(_pixel(env.image(), 72, 72)).is_equal_to((255, 0, 0))

    def test_pack_icon_leaves_a_margin_so_the_title_stays_readable(self, env, tmp_path):
        _icon_env(env, tmp_path)

        _send_set_image(env, {"icon": _DOT_REF, "color": "#ff0000"})

        assert_that(_pixel(env.image(), 72, 72)).is_equal_to((255, 0, 0))
        assert_that(_pixel(env.image(), 5, 5)).is_equal_to(
            (31, 97, 141)
        )  # the counter's background shows in the margin

    def test_raster_plugin_image_stays_full_bleed(self, env, tmp_path):
        _icon_env(env, tmp_path)

        _send_set_image(env, {"image": base64.b64encode(_RED_PNG).decode(), "format": "png"})

        assert_that(_pixel(env.image(), 5, 5)).is_equal_to((255, 0, 0))

    def test_icon_without_colour_renders_untinted(self, env, tmp_path):
        _icon_env(env, tmp_path)

        _send_set_image(env, {"icon": _DOT_REF})

        assert_that(_pixel(env.image(), 72, 72)).is_equal_to((0, 0, 0))

    def test_unknown_reference_clears_the_image(self, env, tmp_path):
        _icon_env(env, tmp_path)
        _send_set_image(env, {"icon": _DOT_REF, "color": "#ff0000"})

        _send_set_image(env, {"icon": f"pack:{_PACK_ID}/missing.svg"})

        assert_that(env.image()).is_equal_to(_BARE_COUNTER)

    @pytest.mark.parametrize(
        "ref",
        [
            "pack:",
            "pack:x",
            f"pack:{_PACK_ID}/../../etc/passwd",
            f"pack:{_PACK_ID}//etc/passwd",
            "pack:unknown.pack/dot.svg",
            "file:///etc/passwd",
            "",
            None,
            7,
        ],
    )
    def test_bad_or_escaping_references_clear_the_image(self, env, tmp_path, ref):
        _icon_env(env, tmp_path)
        _send_set_image(env, {"icon": _DOT_REF, "color": "#ff0000"})

        _send_set_image(env, {"icon": ref})

        assert_that(env.image()).is_equal_to(_BARE_COUNTER)

    def test_invalid_colour_is_untinted_and_logged(self, env, tmp_path, caplog):
        _icon_env(env, tmp_path)

        _send_set_image(env, {"icon": _DOT_REF, "color": "red"})

        assert_that(_pixel(env.image(), 72, 72)).is_equal_to((0, 0, 0))
        assert_that(caplog.text).contains("color")

    def test_payload_with_both_image_and_icon_is_dropped(self, env, tmp_path):
        _icon_env(env, tmp_path)
        before = env.image()

        _send_set_image(env, {"image": base64.b64encode(_RED_PNG).decode(), "icon": _DOT_REF})

        assert_that(env.image()).is_equal_to(before)

    def test_null_image_clears_icon_and_colour(self, env, tmp_path):
        live = _icon_env(env, tmp_path)
        _send_set_image(env, {"icon": _DOT_REF, "color": "#ff0000"})

        _send_set_image(env, {"image": None})

        assert_that(env.image()).is_equal_to(_BARE_COUNTER)
        assert_that(live.plugin_icon_ref).is_none()
        assert_that(live.plugin_image_color).is_none()

    def test_raster_image_after_icon_resets_the_tint(self, env, tmp_path):
        live = _icon_env(env, tmp_path)
        _send_set_image(env, {"icon": _DOT_REF, "color": "#00ff00"})

        _send_set_image(env, {"image": base64.b64encode(_RED_PNG).decode(), "format": "png"})

        assert_that(live.plugin_image_color).is_none()
        assert_that(live.plugin_icon_ref).is_none()
        assert_that(_pixel(env.image(), 72, 72)).is_equal_to((255, 0, 0))

    def test_uninstalled_pack_leaves_the_key_without_an_image(self, env, tmp_path):
        _icon_env(env, tmp_path)
        _send_set_image(env, {"icon": _DOT_REF, "color": "#ff0000"})
        assert_that(_pixel(env.image(), 72, 72)).is_equal_to((255, 0, 0))

        env.manager.icon_packs.unregister("com.t.ip")
        env.manager.set_appearance(COUNTER_TARGET, {})

        assert_that(env.image()).is_equal_to(_BARE_COUNTER)


class TestAppearanceComposition:
    def test_counter_key_is_blue_by_default(self, env):
        env.manager.activate_action(COUNTER_TARGET)
        assert _wait_for(env.counter_drawn)

        assert_that(_pixel(env.image(), 2, 2)).is_equal_to((31, 97, 141))

    def test_counter_no_longer_sets_title(self, env):
        env.manager.activate_action(COUNTER_TARGET)
        assert _wait_for(env.counter_drawn)
        env.manager.dispatch_key_down(COUNTER_TARGET)
        env.manager.dispatch_key_up(COUNTER_TARGET)
        assert _wait_for(lambda: len(env.dm.hardware_images) >= 3)

        assert_that(env.label()).is_equal_to("")

    def test_appearance_change_recomposes_key_without_plugin_round_trip(self, env):
        env.manager.activate_action(COUNTER_TARGET)
        assert _wait_for(env.counter_drawn)
        sent = len(env.dm.hardware_images)
        received = len(env.received())

        env.manager.set_appearance(COUNTER_TARGET, {"background": "#ff0000"})

        assert_that(len(env.dm.hardware_images)).is_equal_to(sent + 1)
        assert_that(_pixel(env.image(), 2, 2)).is_equal_to((255, 0, 0))
        assert_that(len(env.received())).is_equal_to(received)

    def test_initial_appearance_is_applied_on_activation(self, env):
        env.manager.activate_action(COUNTER_TARGET, {"background": "#00ff00"})

        assert_that(_pixel(env.dm.hardware_images[0][1], 2, 2)).is_equal_to((0, 255, 0))

    def test_set_appearance_for_inactive_context_is_ignored(self, env):
        env.manager.set_appearance(COUNTER_TARGET, {"background": "#ff0000"})

        assert_that(env.dm.hardware_images).is_empty()

    def test_plugin_title_is_composed_under_appearance_title(self, env):
        env.manager.activate_action(COUNTER_TARGET)
        assert _wait_for(env.counter_drawn)
        env.manager._on_plugin_message(  # pylint: disable=protected-access
            _COUNTER, Message("set_title", "ctx-1", {"title": "WWWW"})
        )

        assert_that(env.label()).is_equal_to("WWWW")
        assert_that(env.image()).is_not_equal_to(_BARE_COUNTER)

    def test_state_image_used_until_plugin_sets_image(self, env):
        env.manager.activate_action(COUNTER_TARGET)
        assert _wait_for(env.counter_drawn)
        live = env.manager._live["ctx-1"]  # pylint: disable=protected-access
        live.action = replace(live.action, states=(StateSpec(image="icons/counter", title="S"),))
        live.plugin_image = None
        env.manager.set_appearance(COUNTER_TARGET, {})
        with_state = env.image()
        assert_that(with_state).is_not_equal_to(_BARE_COUNTER)

        env.manager._on_plugin_message(  # pylint: disable=protected-access
            _COUNTER, Message("set_image", "ctx-1", {"image": base64.b64encode(_RED_PNG).decode()})
        )

        assert_that(env.image()).is_not_equal_to(with_state)

    def test_set_state_selects_the_state_image(self, env):
        env.manager.activate_action(COUNTER_TARGET)
        assert _wait_for(env.counter_drawn)
        live = env.manager._live["ctx-1"]  # pylint: disable=protected-access
        live.action = replace(live.action, states=(StateSpec(), StateSpec(title="Two")))
        live.plugin_image = None
        env.manager.set_appearance(COUNTER_TARGET, {})
        before = env.image()

        env.manager._on_plugin_message(  # pylint: disable=protected-access
            _COUNTER, Message("set_state", "ctx-1", {"state": 1})
        )

        assert_that(env.image()).is_not_equal_to(before)

    def test_key_state_changed_event_carries_appearance(self, env):
        env.manager.activate_action(COUNTER_TARGET, {"title": "Hi"})

        event = env.bus.of("key_state_changed")[-1]

        assert_that(event["appearance"]["title"]["text"]).is_equal_to("Hi")
        assert_that(event["appearance"]["background"]).is_equal_to("#1f618d")
        assert_that(event["appearance_defaults"]["title"]["text"]).is_equal_to("")
        assert_that(event["appearance_defaults"]["background"]).is_equal_to("#1f618d")

    def test_appearance_for_merges_manifest_defaults(self, env):
        resolved, defaults = env.manager.appearance_for(COUNTER_TARGET, {"title": "x"})

        assert_that(resolved["background"]).is_equal_to("#1f618d")
        assert_that(resolved["title"]["text"]).is_equal_to("x")
        assert_that(defaults["title"]["text"]).is_equal_to("")


class TestComposeFailureIsContained:
    def _failing_first_key(self, env):
        original = env.manager._sink.set_image  # pylint: disable=protected-access

        def flaky(device_id, key_index, image):
            if key_index == 0:
                raise OSError("sink broke")
            original(device_id, key_index, image)

        env.manager._sink.set_image = flaky  # pylint: disable=protected-access

    def test_failing_key_does_not_stop_the_rest_of_the_page(self, env):
        self._failing_first_key(env)
        first, second = REC_TARGET, _target("com.decker.rec", _REC_ACTION, "ctx-2", key=1)

        env.manager.activate_action(first)
        env.manager.activate_action(second)

        assert_that(env.manager._live).contains_key("ctx-1", "ctx-2")  # pylint: disable=protected-access
        assert _wait_for(lambda: {m["context"] for m in env.received("will_appear")} == {"ctx-1", "ctx-2"})
        assert_that(env.image(1)).is_not_none()

    def test_set_appearance_with_raising_sink_does_not_raise(self, env):
        env.manager.activate_action(COUNTER_TARGET)
        self._failing_first_key(env)

        env.manager.set_appearance(COUNTER_TARGET, {"background": "#ff0000"})

        assert_that(env.manager._live).contains_key("ctx-1")  # pylint: disable=protected-access


class TestFailure:
    def test_failed_plugin_keys_marked_and_failure_reported(self, env):
        (env.rec_dir / "crash").write_text("")

        env.manager.activate_action(REC_TARGET)

        assert _wait_for(lambda: env.label() == "Plugin failed")
        assert_that(env.dm.cleared).contains(0)
        assert_that(env.manager.load_failures()).extracting("plugin_uuid").contains("com.decker.rec")
        assert _wait_for(lambda: env.bus.of("plugin_failed"))
        assert_that(env.bus.of("plugin_failed")[0]["plugin_id"]).is_equal_to("com.decker.rec")

    def test_activating_while_failed_marks_the_key(self, env):
        (env.rec_dir / "crash").write_text("")
        env.manager.activate_action(REC_TARGET)
        assert _wait_for(lambda: env.label() == "Plugin failed")

        env.manager.activate_action(_target("com.decker.rec", _REC_ACTION, "ctx-2", key=2))

        assert _wait_for(lambda: env.label(2) == "Plugin failed")

    def test_resaving_settings_retries_failed_plugin(self, env):
        (env.rec_dir / "crash").write_text("")
        env.manager.activate_action(REC_TARGET)
        assert _wait_for(lambda: env.label() == "Plugin failed")
        (env.rec_dir / "crash").unlink()

        env.manager.store_settings(REC_TARGET, {"n": 2})
        env.manager.dispatch_settings_changed(REC_TARGET)

        assert _wait_for(lambda: env.received("will_appear"))
        assert_that(env.received("will_appear")[0]["payload"]["settings"]["n"]).is_equal_to(2)
        assert_that(env.manager.load_failures()).is_empty()
        assert _wait_for(lambda: env.label() == "")


class TestPluginRequests:
    def test_open_url_non_http_dropped(self, env):
        for url in ("file:///etc/passwd", "javascript:alert(1)", "http://", "", 5):
            env.manager._on_plugin_message(
                "com.decker.rec", Message("open_url", "ctx-1", {"url": url})
            )  # pylint: disable=protected-access

        assert_that(env.bus.of("open_url")).is_empty()

    def test_open_url_http_and_https_pushed(self, env):
        for url in ("http://example.com/a", "https://example.com"):
            env.manager._on_plugin_message(
                "com.decker.rec", Message("open_url", "ctx-1", {"url": url})
            )  # pylint: disable=protected-access

        assert_that(env.bus.of("open_url")).is_equal_to(
            [
                {"plugin_id": "com.decker.rec", "url": "http://example.com/a"},
                {"plugin_id": "com.decker.rec", "url": "https://example.com"},
            ]
        )

    def test_set_settings_from_plugin_is_validated_and_persisted(self, env):
        env.manager.activate_action(REC_TARGET)
        assert _wait_for(lambda: env.received("will_appear"))

        env.manager._on_plugin_message(  # pylint: disable=protected-access
            "com.decker.rec", Message("set_settings", "ctx-1", {"settings": {"n": 99, "t": "hi", "junk": 1}})
        )

        expected = {"n": 5, "t": "hi"}  # 99 is out of range -> default; unknown keys dropped
        assert_that(env.persisted).is_equal_to([(REC_TARGET, expected)])
        stored = env.manager._settings_store.get_settings(  # pylint: disable=protected-access
            "com.decker.rec", _REC_ACTION, "ctx-1"
        )
        assert_that(stored).is_equal_to(expected)
        time.sleep(0.2)
        assert_that(env.received("settings_changed")).is_empty()  # not echoed back

    def test_set_gestures_ignores_invalid_values(self, env):
        env.manager.activate_action(REC_TARGET)
        live = env.manager._live["ctx-1"]  # pylint: disable=protected-access
        assert_that(live.gestures).is_equal_to(frozenset({Gesture.PRESS}))

        env.manager._on_plugin_message(
            "com.decker.rec", Message("set_gestures", "ctx-1", {"gestures": ["nope"]})
        )  # pylint: disable=protected-access
        assert_that(live.gestures).is_equal_to(frozenset({Gesture.PRESS}))
        env.manager._on_plugin_message(  # pylint: disable=protected-access
            "com.decker.rec", Message("set_gestures", "ctx-1", {"gestures": ["press", "long_press", "x"]})
        )

        assert_that(live.gestures).is_equal_to(frozenset({Gesture.PRESS, Gesture.LONG_PRESS}))

    def test_raw_key_events_and_gestures_are_forwarded(self, env):
        env.manager.activate_action(REC_TARGET)
        assert _wait_for(lambda: env.received("will_appear"))

        env.manager.dispatch_key_down(REC_TARGET)
        env.manager.dispatch_key_up(REC_TARGET)

        assert _wait_for(lambda: env.received("press"))
        events = [m["event"] for m in env.received()]
        assert_that(events).contains("key_down", "key_up", "press")

    def test_log_messages_do_not_raise(self, env):
        env.manager._on_plugin_message(
            "com.decker.rec", Message("log", None, {"level": "warning", "message": "hi"})
        )  # pylint: disable=protected-access


class TestThreadSafety:
    def test_add_remove_while_listing(self, env):
        rec = next(p for p in env.manager.plugins() if p.manifest.id == "com.decker.rec")
        errors: list[BaseException] = []
        stop = threading.Event()

        def churn() -> None:
            try:
                while not stop.is_set():
                    env.manager.remove_plugin("com.decker.rec")
                    env.manager.add_plugin(rec)
            except BaseException as exc:  # pylint: disable=broad-except
                errors.append(exc)

        def read() -> None:
            try:
                while not stop.is_set():
                    env.manager.list_actions()
                    env.manager.plugins()
                    env.manager.load_failures()
            except BaseException as exc:  # pylint: disable=broad-except
                errors.append(exc)

        threads = [threading.Thread(target=churn), threading.Thread(target=read)]
        for thread in threads:
            thread.start()
        time.sleep(0.5)
        stop.set()
        for thread in threads:
            thread.join(5)

        assert_that(errors).is_empty()

    def test_no_sink_call_after_deactivate_returns(self, env):
        env.manager.activate_action(COUNTER_TARGET)
        assert _wait_for(env.counter_drawn)
        calls: list[float] = []
        original = env.manager._sink.set_image  # pylint: disable=protected-access

        def recording(device_id, key_index, image):
            calls.append(time.monotonic())
            original(device_id, key_index, image)

        env.manager._sink.set_image = recording  # pylint: disable=protected-access
        payload = {"image": base64.b64encode(b"img").decode()}
        done = threading.Event()

        def burst() -> None:
            while not done.is_set():
                env.manager._on_plugin_message(  # pylint: disable=protected-access
                    _COUNTER, Message("set_image", "ctx-1", payload)
                )

        threads = [threading.Thread(target=burst) for _ in range(3)]
        for thread in threads:
            thread.start()
        time.sleep(0.1)
        env.manager.deactivate_action(COUNTER_TARGET)
        returned = time.monotonic()
        time.sleep(0.1)
        done.set()
        for thread in threads:
            thread.join(5)

        assert_that(calls).is_not_empty()
        assert_that([c for c in calls if c > returned]).is_empty()


def test_page_switch_and_plugin_messages_do_not_deadlock(tmp_path):
    from decker.server.page_controller import (
        PageController,  # pylint: disable=import-outside-toplevel
    )

    controller = PageController()
    dm = FakeDeviceManager()
    original = dm.set_image_bytes

    def resolving_set_image(device_id: str, key_index: int, image: bytes) -> None:
        controller.active_page_id(device_id)  # what the real DeviceManager does while persisting
        original(device_id, key_index, image)

    dm.set_image_bytes = resolving_set_image  # type: ignore[method-assign,assignment]
    dm.show_page = lambda _device, _page: True  # type: ignore[attr-defined]
    manager = PluginManager(tmp_path, _FAST, PluginSettingsStore(tmp_path / "db.sqlite"))
    bus = FakeBus()
    manager.create(SimpleNamespace(device_manager=dm, event_bus=bus))  # type: ignore[arg-type]
    page_store = MagicMock()
    page_store.default_page_id.return_value = "p1"
    keys = MagicMock()
    keys.all_for_page.return_value = [(0, SimpleNamespace(target=COUNTER_TARGET, settings={}, appearance={}))]
    controller.create(
        SimpleNamespace(page_store=page_store, key_assignment_store=keys, device_manager=dm, plugin_manager=manager, event_bus=bus)  # type: ignore[arg-type]
    )
    done = threading.Event()
    payload = {"image": base64.b64encode(b"img").decode()}

    def switcher() -> None:
        for i in range(300):
            controller.activate("dev-1", "p2" if i % 2 == 0 else "p1")
        done.set()

    def router() -> None:
        while not done.is_set():
            manager._on_plugin_message(
                _COUNTER, Message("set_image", "ctx-1", payload)
            )  # pylint: disable=protected-access

    controller.restore("dev-1")
    threads = [threading.Thread(target=switcher, daemon=True), threading.Thread(target=router, daemon=True)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    alive = [t.is_alive() for t in threads]
    done.set()
    if not any(alive):
        manager.destroy()
    assert_that(alive).is_equal_to([False, False])


def test_plugins_dir_loader_failure_is_reported(tmp_path):
    broken = tmp_path / "bad"
    broken.mkdir()
    (broken / "manifest.json").write_text("{")
    manager = PluginManager(tmp_path, _FAST, PluginSettingsStore(tmp_path / "db.sqlite"))
    context = SimpleNamespace(device_manager=FakeDeviceManager(), event_bus=FakeBus())
    manager.create(context)  # type: ignore[arg-type]
    try:
        assert_that(manager.load_failures()).extracting("plugin_uuid").contains("bad")
    finally:
        manager.destroy()


def test_duplicate_plugin_id_is_rejected(tmp_path):
    shutil.copytree(_FIXTURE_DIR, tmp_path / "a")
    shutil.copytree(_FIXTURE_DIR, tmp_path / "b")
    manager = PluginManager(tmp_path, _FAST, PluginSettingsStore(tmp_path / "db.sqlite"))
    manager.create(SimpleNamespace(device_manager=FakeDeviceManager(), event_bus=FakeBus()))  # type: ignore[arg-type]
    try:
        assert_that(manager.load_failures()).extracting("error").contains("duplicate plugin id")
        assert_that(manager.plugins()).is_length(2)  # the fixture plugin and the built-in Blank
    finally:
        manager.destroy()


class TestLockDiscipline:
    def test_composition_and_state_push_run_outside_the_manager_lock(self, env, monkeypatch):
        import decker.server.plugins as plugins_module

        held: list[bool] = []
        real = plugins_module.compose_key_image

        def watching(*args, **kwargs):
            held.append(env.manager._lock._is_owned())  # pylint: disable=protected-access
            return real(*args, **kwargs)

        monkeypatch.setattr(plugins_module, "compose_key_image", watching)
        pushes: list[bool] = []
        original = env.manager._state_changed_cb  # pylint: disable=protected-access

        def notified(device_id, key_index):
            pushes.append(env.manager._lock._is_owned())  # pylint: disable=protected-access
            original(device_id, key_index)

        env.manager._state_changed_cb = notified  # pylint: disable=protected-access
        env.manager.activate_action(REC_TARGET)
        env.manager._on_plugin_message(  # pylint: disable=protected-access
            "com.decker.rec", Message("set_title", "ctx-1", {"title": "T"})
        )

        assert_that(held).is_not_empty()
        assert_that(any(held)).is_false()
        assert_that(pushes).is_not_empty()
        assert_that(any(pushes)).is_false()

    def test_will_appear_carries_the_live_state(self, env):
        env.manager.activate_action(REC_TARGET)
        assert _wait_for(lambda: env.received("will_appear"))
        env.manager._live["ctx-1"].state = 1  # pylint: disable=protected-access
        env.manager._send_will_appear(env.manager._live["ctx-1"])  # pylint: disable=protected-access

        assert _wait_for(lambda: len(env.received("will_appear")) == 2)
        assert_that(env.received("will_appear")[-1]["payload"]["state"]).is_equal_to(1)

    def test_global_settings_changed_uses_the_spec_key(self, env):
        env.manager.activate_action(REC_TARGET)
        assert _wait_for(lambda: env.received("will_appear"))
        env.manager.update_global_settings("com.decker.rec", {})
        assert _wait_for(lambda: env.received("global_settings_changed"))
        assert_that(env.received("global_settings_changed")[0]["payload"]).contains_key("global_settings")


class TestStaticActions:
    def test_static_action_draws_its_appearance(self, env):
        env.manager.activate_action(STATIC_TARGET)

        image = env.image(1)
        assert_that(_pixel(image, 2, 2)).is_equal_to((0x33, 0x66, 0x99))
        assert_that(image).is_not_equal_to(
            compose_key_image(resolve_appearance({"background": "#336699"}, {}), None, "")
        )

    def test_static_action_starts_no_process_and_sends_nothing(self, env):
        env.manager.activate_action(MIXED_STATIC_TARGET)

        entry = env.manager._supervisor._entries.get("com.t.mixed")  # pylint: disable=protected-access
        assert_that(entry is None or entry.process is None).is_true()
        assert_that(env.mixed_dir.joinpath("received.log").exists()).is_false()
        assert_that(env.image(2)).is_not_none()

    def test_press_and_long_press_on_a_static_key_do_nothing(self, env):
        env.manager.activate_action(MIXED_STATIC_TARGET)

        env.manager.dispatch_key_down(MIXED_STATIC_TARGET)
        env.manager.dispatch_key_up(MIXED_STATIC_TARGET)
        env.manager.dispatch_key_down(MIXED_STATIC_TARGET)
        time.sleep(0.8)
        env.manager.dispatch_key_up(MIXED_STATIC_TARGET)

        assert_that(env.mixed_dir.joinpath("received.log").exists()).is_false()

    def test_deactivating_a_static_key_does_not_touch_the_supervisor(self, env):
        env.manager.activate_action(MIXED_STATIC_TARGET)
        env.manager._supervisor.release = MagicMock(side_effect=AssertionError("released"))

        env.manager.deactivate_action(MIXED_STATIC_TARGET)

        assert_that(env.manager._live).does_not_contain_key("ctx-mixed")  # pylint: disable=protected-access

    def test_user_appearance_overrides_the_static_defaults(self, env):
        env.manager.activate_action(STATIC_TARGET, {"background": "#ff0000"})

        assert_that(_pixel(env.image(1), 2, 2)).is_equal_to((255, 0, 0))

    def test_static_action_in_a_runtime_plugin_does_not_start_the_process(self, env):
        env.manager.activate_action(MIXED_STATIC_TARGET)
        env.manager.dispatch_settings_changed(MIXED_STATIC_TARGET)
        time.sleep(0.3)

        assert_that(env.mixed_dir.joinpath("received.log").exists()).is_false()

    def test_ready_plugin_does_not_send_will_appear_for_its_static_key(self, env):
        mixed_live = _target("com.t.mixed", "com.t.mixed.live", "ctx-live", 3)
        env.manager.activate_action(MIXED_STATIC_TARGET)
        env.manager.activate_action(mixed_live)

        assert_that(_wait_for(lambda: env.mixed_dir.joinpath("received.log").exists())).is_true()
        time.sleep(0.3)
        log = [json.loads(x) for x in env.mixed_dir.joinpath("received.log").read_text().splitlines()]
        contexts = [m.get("context") for m in log if m["event"] == "will_appear"]
        assert_that(contexts).is_equal_to(["ctx-live"])

    def test_static_action_listed_in_list_actions(self, env):
        actions = {a["action_uuid"]: a for a in env.manager.list_actions()}

        assert_that(actions).contains_key(_STATIC_ACTION)
        assert_that(actions[_STATIC_ACTION]["settings_schema"]).is_equal_to([])


_STATIC_MANIFEST_DEFAULTS = _STATIC_MANIFEST["contributes"]["actions"][0]["appearance"]


class TestTemplates:
    def test_title_template_is_expanded_when_drawn(self, env):
        env.manager.activate_action(STATIC_TARGET, {"title": {"text": "{page_index}/{page_count}"}})

        assert_that(env.image(1)).is_equal_to(
            compose_key_image(resolve_appearance(_STATIC_MANIFEST_DEFAULTS, {"title": {"text": "2/3"}}), None, "")
        )

    def test_unknown_and_escaped_braces_in_the_title(self, env):
        env.manager.activate_action(STATIC_TARGET, {"title": {"text": "{{x}} {nope}"}})

        assert_that(env.image(1)).is_equal_to(
            compose_key_image(
                resolve_appearance(_STATIC_MANIFEST_DEFAULTS, {"title": {"text": "{x} {nope}"}}), None, ""
            )
        )

    def test_title_without_pages_keeps_text_literal(self, env):
        env.pages.pages["dev-1"] = []
        env.manager.activate_action(STATIC_TARGET, {"title": {"text": "{page_name}"}})

        assert_that(env.image(1)).is_equal_to(
            compose_key_image(
                resolve_appearance(_STATIC_MANIFEST_DEFAULTS, {"title": {"text": "{page_name}"}}), None, ""
            )
        )

    def test_plugin_fallback_title_is_not_expanded(self, env):
        live_target = _target("com.decker.rec", _REC_ACTION)
        env.manager.activate_action(live_target)
        assert _wait_for(lambda: env.received("will_appear"))

        env.manager._route_context_message(  # pylint: disable=protected-access
            "com.decker.rec", Message("set_title", "ctx-1", {"title": "{page_name}"})
        )

        appearance = resolve_appearance({}, {})
        assert_that(env.image()).is_equal_to(compose_key_image(appearance, None, "{page_name}"))

    def _tpl_settings(self, env, **values):
        env.manager.store_settings(TPL_TARGET, values)
        env.manager.activate_action(TPL_TARGET)
        assert _wait_for(lambda: env.received("will_appear"))
        return env.received("will_appear")[-1]["payload"]["settings"]

    def test_opted_in_text_field_is_delivered_expanded(self, env):
        settings = self._tpl_settings(env, label="On {page_name}")

        assert_that(settings["label"]).is_equal_to("On Settings")
        assert_that(
            env.manager._settings_store.get_settings(  # pylint: disable=protected-access
                "com.decker.rec", "com.decker.rec.tpl", "ctx-tpl"
            )["label"]
        ).is_equal_to("On {page_name}")

    def test_not_opted_in_field_is_delivered_verbatim(self, env):
        settings = self._tpl_settings(env, plain="On {page_name}")

        assert_that(settings["plain"]).is_equal_to("On {page_name}")

    def test_text_style_text_is_expanded_other_fields_untouched(self, env):
        settings = self._tpl_settings(env, style={"text": "{page_index}", "size": 33})

        assert_that(settings["style"]["text"]).is_equal_to("2")
        assert_that(settings["style"]["size"]).is_equal_to(33)

    def test_page_field_is_resolved_to_id_name_index(self, env):
        settings = self._tpl_settings(env, where="p3")

        assert_that(settings["where"]).is_equal_to({"page_id": "p3", "name": "Media", "index": 3})

    @pytest.mark.parametrize("stored", ["", "gone", 5, {"page_id": 5}, None])
    def test_deleted_or_unset_or_foreign_page_resolves_to_empty(self, env, stored):
        settings = self._tpl_settings(env, where=stored)

        assert_that(settings["where"]).is_equal_to({"page_id": "", "name": "", "index": 0})

    def test_settings_changed_delivers_the_expanded_copy(self, env):
        self._tpl_settings(env, label="{page_name}")
        env.manager.store_settings(TPL_TARGET, {"label": "Now {page_count}"})

        env.manager.dispatch_settings_changed(TPL_TARGET)

        assert _wait_for(lambda: env.received("settings_changed"))
        assert_that(env.received("settings_changed")[-1]["payload"]["settings"]["label"]).is_equal_to("Now 3")

    def test_set_settings_from_a_plugin_does_not_store_expanded_text(self, env):
        self._tpl_settings(env, label="{page_name}", plain="keep")

        env.manager._route_context_message(  # pylint: disable=protected-access
            "com.decker.rec", Message("set_settings", "ctx-tpl", {"settings": {"plain": "changed"}})
        )

        stored = env.manager._settings_store.get_settings(  # pylint: disable=protected-access
            "com.decker.rec", "com.decker.rec.tpl", "ctx-tpl"
        )
        assert_that(stored["label"]).is_equal_to("{page_name}")
        assert_that(stored["plain"]).is_equal_to("changed")

    def test_echoing_delivered_settings_keeps_the_raw_templates(self, env):
        delivered = self._tpl_settings(env, label="On {page_name}", style={"text": "{page_index}", "size": 33})

        env.manager._route_context_message(  # pylint: disable=protected-access
            "com.decker.rec", Message("set_settings", "ctx-tpl", {"settings": {**delivered, "plain": "x"}})
        )

        stored = env.manager._settings_store.get_settings(  # pylint: disable=protected-access
            "com.decker.rec", "com.decker.rec.tpl", "ctx-tpl"
        )
        assert_that(stored["label"]).is_equal_to("On {page_name}")
        assert_that(stored["style"]["text"]).is_equal_to("{page_index}")
        assert_that(stored["plain"]).is_equal_to("x")

    def test_a_template_the_plugin_really_changed_is_stored(self, env):
        self._tpl_settings(env, label="On {page_name}")

        env.manager._route_context_message(  # pylint: disable=protected-access
            "com.decker.rec", Message("set_settings", "ctx-tpl", {"settings": {"label": "New {page_count}"}})
        )

        stored = env.manager._settings_store.get_settings(  # pylint: disable=protected-access
            "com.decker.rec", "com.decker.rec.tpl", "ctx-tpl"
        )
        assert_that(stored["label"]).is_equal_to("New {page_count}")

    def test_echoed_page_value_keeps_the_page_choice(self, env):
        self._tpl_settings(env, where="p3")

        env.manager._route_context_message(  # pylint: disable=protected-access
            "com.decker.rec",
            Message("set_settings", "ctx-tpl", {"settings": {"where": {"page_id": "p3", "name": "Media", "index": 3}}}),
        )

        stored = env.manager._settings_store.get_settings(  # pylint: disable=protected-access
            "com.decker.rec", "com.decker.rec.tpl", "ctx-tpl"
        )
        assert_that(stored["where"]).is_equal_to("p3")


class TestPageRefresh:
    def test_rename_refreshes_title_and_settings(self, env):
        env.manager.activate_action(STATIC_TARGET, {"title": {"text": "{page_name}"}})
        env.manager.store_settings(TPL_TARGET, {"label": "{page_name}", "where": "p2"})
        env.manager.activate_action(TPL_TARGET)
        assert _wait_for(lambda: env.received("will_appear"))
        before = env.image(1)

        env.pages.rename("p2", "Renamed")
        env.manager.refresh_page_dependent("dev-1")

        assert_that(env.image(1)).is_not_equal_to(before)
        assert _wait_for(lambda: env.received("settings_changed"))
        settings = env.received("settings_changed")[-1]["payload"]["settings"]
        assert_that(settings["label"]).is_equal_to("Renamed")
        assert_that(settings["where"]["name"]).is_equal_to("Renamed")

    def test_no_duplicate_settings_changed_when_nothing_changed(self, env):
        env.manager.store_settings(TPL_TARGET, {"label": "{page_name}"})
        env.manager.activate_action(TPL_TARGET)
        assert _wait_for(lambda: env.received("will_appear"))

        env.manager.refresh_page_dependent("dev-1")
        env.manager.refresh_page_dependent("dev-1")
        time.sleep(0.3)

        assert_that(env.received("settings_changed")).is_empty()

    def test_other_devices_are_untouched(self, env):
        env.manager.activate_action(STATIC_TARGET, {"title": {"text": "{page_name}"}})
        before = env.image(1)
        env.pages.rename("p2", "Renamed")

        env.manager.refresh_page_dependent("dev-2")

        assert_that(env.image(1)).is_equal_to(before)

    def test_keys_without_templates_are_not_recomposed(self, env, monkeypatch):
        env.manager.activate_action(STATIC_TARGET, {"title": {"text": "plain"}})
        calls = MagicMock()
        monkeypatch.setattr("decker.server.plugins.compose_key_image", calls)

        env.manager.refresh_page_dependent("dev-1")

        assert_that(calls.call_count).is_equal_to(0)

    def test_page_switch_redraws_keys_with_the_new_variables(self, env):
        env.manager.activate_action(STATIC_TARGET, {"title": {"text": "{page_name}"}})
        before = env.image(1)
        env.pages.active["dev-1"] = "p3"

        env.manager.activate_action(STATIC_TARGET, {"title": {"text": "{page_name}"}})

        assert_that(env.image(1)).is_not_equal_to(before)


class TestSwitchPage:
    def _switch(self, env, payload, active="p2"):
        env.pages.active["dev-1"] = active
        env.manager.activate_action(REC_TARGET)
        env.manager._route_context_message(  # pylint: disable=protected-access
            "com.decker.rec", Message("switch_page", "ctx-1", payload)
        )
        return [page for _device, page in env.pages.activations]

    def test_next_goes_to_the_following_page(self, env):
        assert_that(self._switch(env, {"to": "next"})).is_equal_to(["p3"])

    def test_previous_goes_to_the_preceding_page(self, env):
        assert_that(self._switch(env, {"to": "previous"})).is_equal_to(["p1"])

    def test_next_on_the_last_page_stays_unless_wrapping(self, env):
        assert_that(self._switch(env, {"to": "next"}, active="p3")).is_empty()
        assert_that(self._switch(env, {"to": "next", "wrap": False}, active="p3")).is_empty()

    def test_previous_on_the_first_page_stays_unless_wrapping(self, env):
        assert_that(self._switch(env, {"to": "previous"}, active="p1")).is_empty()

    def test_wrap_goes_from_last_to_first_and_first_to_last(self, env):
        assert_that(self._switch(env, {"to": "next", "wrap": True}, active="p3")).is_equal_to(["p1"])
        env.pages.activations.clear()
        assert_that(self._switch(env, {"to": "previous", "wrap": True}, active="p1")).is_equal_to(["p3"])

    def test_first_and_last(self, env):
        assert_that(self._switch(env, {"to": "first"}, active="p3")).is_equal_to(["p1"])
        env.pages.activations.clear()
        assert_that(self._switch(env, {"to": "last"}, active="p1")).is_equal_to(["p3"])

    def test_page_id_goes_to_that_page(self, env):
        assert_that(self._switch(env, {"page_id": "p3"})).is_equal_to(["p3"])

    def test_unknown_page_id_is_ignored_and_logged(self, env, caplog):
        caplog.set_level("INFO")
        assert_that(self._switch(env, {"page_id": "nope"})).is_empty()
        assert_that(caplog.text).contains("switch_page")

    def test_single_page_is_a_no_op(self, env):
        env.pages.pages["dev-1"] = [PageInfo("p2", "Only")]

        assert_that(self._switch(env, {"to": "next", "wrap": True})).is_empty()

    @pytest.mark.parametrize("payload", [{}, {"to": "sideways"}, {"to": 5}, {"page_id": 7}])
    def test_bad_payloads_are_ignored(self, env, payload):
        assert_that(self._switch(env, payload)).is_empty()

    def test_non_boolean_wrap_is_treated_as_no_wrap(self, env):
        assert_that(self._switch(env, {"to": "next", "wrap": "yes"}, active="p3")).is_empty()

    def test_page_of_another_device_is_not_reachable(self, env):
        env.pages.pages["dev-2"] = [PageInfo("x1", "Elsewhere")]

        assert_that(self._switch(env, {"page_id": "x1"})).is_empty()

    def test_message_from_an_inactive_context_is_dropped(self, env):
        env.manager._route_context_message(  # pylint: disable=protected-access
            "com.decker.rec", Message("switch_page", "ctx-1", {"to": "next"})
        )

        assert_that(env.pages.activations).is_empty()

    def test_message_from_another_plugin_is_dropped(self, env):
        env.manager.activate_action(REC_TARGET)

        env.manager._route_context_message(  # pylint: disable=protected-access
            "com.t.mixed", Message("switch_page", "ctx-1", {"to": "next"})
        )

        assert_that(env.pages.activations).is_empty()

    def test_switch_does_not_hold_the_manager_lock(self, env):
        outcome: list[bool] = []

        def _activate(device_id: str, page_id: str) -> bool:
            def _try() -> None:
                got = env.manager._lock.acquire(timeout=1)  # pylint: disable=protected-access
                outcome.append(got)
                if got:
                    env.manager._lock.release()  # pylint: disable=protected-access

            thread = threading.Thread(target=_try)
            thread.start()
            thread.join(3)
            return True

        env.pages.activate = _activate

        self._switch(env, {"to": "next"})

        assert_that(outcome).is_equal_to([True])

    def test_a_key_can_switch_away_from_its_own_page(self, env):
        def _activate(device_id: str, page_id: str) -> bool:
            env.manager.deactivate_action(REC_TARGET)  # the page switch hides the sender's page
            env.pages.active[device_id] = page_id
            return True

        env.pages.activate = _activate

        self._switch(env, {"to": "next"})

        assert_that(env.manager._live).does_not_contain_key("ctx-1")  # pylint: disable=protected-access
