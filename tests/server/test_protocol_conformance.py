"""Drives a tiny non-SDK executable plugin through the protocol using only the spec's payload shapes."""

import base64
import io
import json
import stat
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from assertpy import assert_that
from PIL import Image

from decker.plugin.settings_store import PluginSettingsStore
from decker.plugin.target import ActionTarget
from decker.server.plugins import PluginManager
from tests.server.test_plugins import _FAST, FakeBus, FakeDeviceManager

_PLUGIN_ID = "com.example.conform"
_ACTION_ID = "com.example.conform.act"

_MANIFEST = {
    "format": 1,
    "id": _PLUGIN_ID,
    "name": "Conformance",
    "version": "1.0.0",
    "author": "Test",
    "runtime": {"type": "executable", "entry": "run.py"},
    "global_settings": [{"key": "token", "type": "text", "label": "Token", "default": ""}],
    "contributes": {"actions": [{"id": _ACTION_ID, "name": "Act"}]},
}

_PNG = base64.b64encode(
    (lambda buf: (Image.new("RGBA", (8, 8), (0, 255, 0, 255)).save(buf, format="PNG"), buf.getvalue())[1])(io.BytesIO())
).decode()

_SCRIPT = f"""#!{sys.executable}
import json, os, sys

here = os.path.dirname(os.path.abspath(__file__))


def send(**message):
    print(json.dumps(message), flush=True)


def note(**record):
    with open(os.path.join(here, "seen.log"), "a") as log:
        log.write(json.dumps(record) + "\\n")


for line in sys.stdin:
    message = json.loads(line)
    event, context, payload = message["event"], message.get("context"), message.get("payload", {{}})
    if event == "hello":
        note(event=event, keys=sorted(payload), protocol=payload["protocol"], plugin_id=payload["plugin_id"])
        send(event="ready")
    elif event == "will_appear":
        note(event=event, keys=sorted(payload), key=sorted(payload["key"]), context=context)
        send(event="set_image", context=context, payload={{"image": "{_PNG}", "format": "png"}})
    elif event == "global_settings_changed":
        note(event=event, keys=sorted(payload), token=payload["global_settings"]["token"])
    elif event == "ping":
        send(event="pong")
    elif event == "shutdown":
        note(event=event)
        break
"""


def _wait_for(predicate, timeout=8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_non_sdk_executable_plugin_speaks_the_documented_protocol(tmp_path):
    folder = tmp_path / "plugins" / _PLUGIN_ID
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps(_MANIFEST))
    script = folder / "run.py"
    script.write_text(_SCRIPT)
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    device_manager = FakeDeviceManager()
    manager = PluginManager(tmp_path / "plugins", _FAST, PluginSettingsStore(tmp_path / "plugins.db"))
    manager.create(
        SimpleNamespace(
            device_manager=device_manager,
            event_bus=FakeBus(),
            page_controller=MagicMock(),
            key_assignment_store=MagicMock(),
        )
    )

    def seen() -> list[dict]:
        log = folder / "seen.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    try:
        manager.activate_action(ActionTarget(_PLUGIN_ID, _ACTION_ID, "ctx-1", "dev-1", 0))
        assert _wait_for(lambda: any(r["event"] == "will_appear" for r in seen()))
        hello = next(r for r in seen() if r["event"] == "hello")
        assert_that(hello["keys"]).is_equal_to(["decker_version", "global_settings", "plugin_id", "protocol"])
        will_appear = next(r for r in seen() if r["event"] == "will_appear")
        assert_that(will_appear["keys"]).is_equal_to(["action", "device", "key", "settings", "state"])
        assert_that(will_appear["key"]).is_equal_to(["column", "index", "row"])

        assert _wait_for(
            lambda: any(
                Image.open(io.BytesIO(b)).convert("RGB").getpixel((72, 72)) == (0, 255, 0)
                for _k, b in device_manager.hardware_images
            )
        )

        manager.update_global_settings(_PLUGIN_ID, {"token": "abc"})
        assert _wait_for(lambda: any(r["event"] == "global_settings_changed" for r in seen()))
        changed = next(r for r in seen() if r["event"] == "global_settings_changed")
        assert_that(changed["keys"]).is_equal_to(["global_settings"])
        assert_that(changed["token"]).is_equal_to("abc")
    finally:
        manager.destroy()
    assert_that([r["event"] for r in seen()][-1]).is_equal_to("shutdown")
