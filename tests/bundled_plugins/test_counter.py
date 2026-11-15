"""Tests for the bundled counter plugin (com.decker.counter), run through the SDK loop on pipes."""

import base64
import importlib.util
import io
import json
import os
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from assertpy import assert_that
from PIL import Image

from decker.plugin.manifest import PluginManifest
from decker.plugin.settings_schema import apply_schema
from decker_plugin_sdk import run

_DIR = Path(__file__).parents[2] / "src" / "decker" / "bundled_plugins" / "com.decker.counter"
_ACTION = "com.decker.counter.counter"
_SCHEMA = PluginManifest.load(_DIR / "manifest.json").actions[0].settings


@pytest.fixture(scope="module", name="counter")
def counter_fixture() -> ModuleType:
    spec = importlib.util.spec_from_file_location("decker_plugin_test_counter", _DIR / "plugin.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _settings(**values: Any) -> dict[str, Any]:
    return apply_schema(_SCHEMA, values)


def _image(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


class Harness:
    """Runs the counter through the SDK loop on os.pipe streams."""

    def __init__(self, counter: ModuleType) -> None:
        in_r, in_w = os.pipe()
        out_r, out_w = os.pipe()
        self._to_plugin = os.fdopen(in_w, "wb")
        self._plugin_in = os.fdopen(in_r, "rb")
        self._plugin_out = os.fdopen(out_w, "wb")
        self._from_plugin = os.fdopen(out_r, "rb")
        self._thread = threading.Thread(
            target=run, args=({_ACTION: counter.CounterAction}, self._plugin_in, self._plugin_out)
        )
        self._thread.start()
        self.send("hello", payload={"protocol": 1, "decker_version": "x", "plugin_id": "com.decker.counter"})
        assert_that(self.recv()["event"]).is_equal_to("ready")

    def send(self, event: str, context: str | None = None, payload: dict | None = None) -> None:
        data: dict[str, Any] = {"event": event, "payload": payload or {}}
        if context:
            data["context"] = context
        self._to_plugin.write(json.dumps(data).encode() + b"\n")
        self._to_plugin.flush()

    def recv(self) -> dict:
        line = self._from_plugin.readline()
        assert line, "plugin closed stdout"
        return json.loads(line)

    def recv_until(self, event: str) -> dict:
        while True:
            message = self.recv()
            if message["event"] == event:
                return message

    def appear(self, **values: Any) -> None:
        self.send(
            "will_appear",
            "c1",
            {
                "action": _ACTION,
                "device": "d",
                "key": {"index": 0, "column": 0, "row": 0},
                "settings": _settings(**values),
                "state": 0,
            },
        )

    def next_title(self) -> str:
        return self.recv_until("set_title")["payload"]["title"]

    def close(self) -> None:
        self.send("shutdown")
        self._thread.join(5)
        for stream in (self._to_plugin, self._plugin_in, self._plugin_out, self._from_plugin):
            stream.close()


@pytest.fixture(name="harness")
def harness_fixture(counter):
    harness = Harness(counter)
    yield harness
    harness.close()


class TestGestures:
    def test_double_press_registered_only_with_double_step(self, harness):
        harness.appear()
        without = harness.recv_until("set_gestures")["payload"]["gestures"]
        harness.send("settings_changed", "c1", {"settings": _settings(double_step=5)})
        with_double = harness.recv_until("set_gestures")["payload"]["gestures"]

        assert_that(without).is_equal_to(["long_press", "press"])
        assert_that(with_double).is_equal_to(["double_press", "long_press", "press"])

    def test_cleared_double_step_unregisters_it(self, harness):
        harness.appear(double_step=5)
        harness.recv_until("set_gestures")
        harness.send("settings_changed", "c1", {"settings": _settings(double_step=None)})

        assert_that(harness.recv_until("set_gestures")["payload"]["gestures"]).does_not_contain("double_press")


class TestCounting:
    def test_press_increments(self, harness):
        harness.appear(step=3)
        assert_that(harness.next_title()).is_equal_to("0")

        harness.send("press", "c1")
        assert_that(harness.next_title()).is_equal_to("3")
        harness.send("press", "c1")
        assert_that(harness.next_title()).is_equal_to("6")

    def test_default_step_is_one(self, harness):
        harness.appear()
        harness.next_title()

        harness.send("press", "c1")

        assert_that(harness.next_title()).is_equal_to("1")

    def test_double_press_adds_double_step(self, harness):
        harness.appear(step=1, double_step=10)
        harness.next_title()

        harness.send("press", "c1")
        harness.next_title()
        harness.send("double_press", "c1")

        assert_that(harness.next_title()).is_equal_to("11")

    def test_long_press_resets(self, harness):
        harness.appear(step=4)
        harness.next_title()
        harness.send("press", "c1")
        harness.next_title()

        harness.send("long_press", "c1")

        assert_that(harness.next_title()).is_equal_to("0")

    def test_max_wraps(self, harness):
        harness.appear(step=2, max=4)
        harness.next_title()

        harness.send("press", "c1")
        assert_that(harness.next_title()).is_equal_to("2")
        harness.send("press", "c1")
        assert_that(harness.next_title()).is_equal_to("0")

    def test_image_is_a_png_in_the_chosen_background(self, harness):
        harness.appear(background="#ff0000")

        message = harness.recv_until("set_image")["payload"]

        assert_that(message["format"]).is_equal_to("png")
        assert_that(_image(base64.b64decode(message["image"])).getpixel((2, 2))).is_equal_to((255, 0, 0))

    def test_settings_change_redraws(self, harness):
        harness.appear()
        harness.recv_until("set_image")

        harness.send("settings_changed", "c1", {"settings": _settings(background="#00ff00")})
        message = harness.recv_until("set_image")["payload"]

        assert_that(_image(base64.b64decode(message["image"])).getpixel((2, 2))).is_equal_to((0, 255, 0))


class TestSettingsSchema:
    def test_empty_outline_and_double_step_become_none(self):
        settings = _settings(title_outline="", double_step="")

        assert_that(settings["title_outline"]).is_none()
        assert_that(settings["double_step"]).is_none()

    def test_defaults_match_the_original_counter(self):
        assert_that(_settings()).is_equal_to(
            {
                "step": 1,
                "double_step": None,
                "max": 0,
                "background": "#1f618d",
                "title": "",
                "title_position": "bottom",
                "title_font": "DejaVu Sans",
                "title_size": 12,
                "title_color": "#ffffff",
                "title_outline": None,
                "title_outline_width": 1,
            }
        )

    def test_everything_the_client_form_sends_is_kept(self):
        sent = {
            "step": 5,
            "double_step": -3,
            "max": 99999,
            "background": "#102030",
            "title": "Hi",
            "title_position": "top",
            "title_font": "Noto Sans",
            "title_size": 48,
            "title_color": "#abcdef",
            "title_outline": "#000000",
            "title_outline_width": 6,
        }

        assert_that(_settings(**sent)).is_equal_to(sent)


class TestRender:
    def test_default_background_is_the_counter_blue(self, counter):
        image = _image(counter.render(0, _settings()))

        assert_that(image.size).is_equal_to((144, 144))
        assert_that(image.getpixel((2, 2))).is_equal_to((31, 97, 141))

    @pytest.mark.parametrize("position,band", [("top", (0, 40)), ("middle", (52, 92)), ("bottom", (104, 144))])
    def test_title_is_drawn_at_its_position(self, counter, position, band):
        settings = _settings(title="WWWW", title_position=position, title_color="#ffff00", title_size=14)

        image = _image(counter.render(8, settings))

        yellow_rows = {y for y in range(144) for x in range(144) if image.getpixel((x, y)) == (255, 255, 0)}
        assert_that(yellow_rows).is_not_empty()
        assert_that(min(yellow_rows)).is_greater_than_or_equal_to(band[0])
        assert_that(max(yellow_rows)).is_less_than(band[1])

    def test_outline_is_drawn_only_when_set(self, counter):
        values = {"title": "WWWW", "title_color": "#ffff00", "title_outline_width": 2}

        plain = _image(counter.render(0, _settings(**values)))
        outlined = _image(counter.render(0, _settings(**values, title_outline="#ff00ff")))

        magenta = (255, 0, 255)
        assert_that(any(p == magenta for p in plain.get_flattened_data())).is_false()
        assert_that(any(p == magenta for p in outlined.get_flattened_data())).is_true()

    def test_missing_fontconfig_falls_back(self, counter, monkeypatch):
        def _missing(*_args: Any, **_kwargs: Any) -> None:
            raise FileNotFoundError("fc-match")

        counter._font_file.cache_clear()  # pylint: disable=protected-access
        monkeypatch.setattr(counter.subprocess, "run", _missing)
        data = counter.render(0, _settings(title="x", title_font="Anything"))
        counter._font_file.cache_clear()  # pylint: disable=protected-access

        assert_that(_image(data).size).is_equal_to((144, 144))
