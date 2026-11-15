"""Tests for the bundled counter plugin (com.decker.counter)."""

import importlib.util
import io
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that
from PIL import Image

from decker.plugin import Gesture

_PLUGIN = Path(__file__).parents[2] / "src" / "decker" / "bundled_plugins" / "com.decker.counter" / "plugin.py"


@pytest.fixture(scope="module")
def counter() -> ModuleType:
    spec = importlib.util.spec_from_file_location("decker_plugin_test_counter", _PLUGIN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ctx(settings: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.get_settings.return_value = settings or {}
    return ctx


def _image(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


class TestGestures:
    def test_without_double_step_presses_never_wait(self, counter):
        action = counter.CounterAction()

        for settings in ({}, {"double_step": None}, {"double_step": ""}, {"double_step": "  "}):
            assert_that(action.gestures(settings)).is_equal_to(frozenset({Gesture.PRESS, Gesture.LONG_PRESS}))

    def test_double_step_registers_double_press(self, counter):
        assert_that(counter.CounterAction().gestures({"double_step": 5})).contains(Gesture.DOUBLE_PRESS)
        assert_that(counter.CounterAction().gestures({"double_step": 0})).contains(Gesture.DOUBLE_PRESS)


class TestCounting:
    def test_press_adds_step_and_pushes_image_and_label(self, counter):
        action = counter.CounterAction()
        ctx = _ctx({"step": 3})

        action.on_press(ctx)
        action.on_press(ctx)

        ctx.set_title.assert_called_with("6")
        ctx.set_image.assert_called()

    def test_default_step_is_one(self, counter):
        action = counter.CounterAction()
        ctx = _ctx()

        action.on_press(ctx)

        ctx.set_title.assert_called_with("1")

    def test_double_press_adds_double_step(self, counter):
        action = counter.CounterAction()
        ctx = _ctx({"step": 1, "double_step": 10})

        action.on_press(ctx)
        action.on_double_press(ctx)

        ctx.set_title.assert_called_with("11")

    def test_long_press_resets(self, counter):
        action = counter.CounterAction()
        ctx = _ctx({"step": 4})
        action.on_press(ctx)

        action.on_long_press(ctx)

        ctx.set_title.assert_called_with("0")

    def test_max_wraps_to_zero(self, counter):
        action = counter.CounterAction()
        ctx = _ctx({"step": 2, "max": 4})

        action.on_press(ctx)
        action.on_press(ctx)

        ctx.set_title.assert_called_with("0")

    def test_will_appear_and_settings_change_redraw(self, counter):
        action = counter.CounterAction()
        ctx = _ctx()

        action.on_will_appear(ctx)
        action.on_settings_changed(ctx)

        assert_that(ctx.set_image.call_count).is_equal_to(2)

    def test_bad_numbers_fall_back_to_defaults(self, counter):
        action = counter.CounterAction()
        ctx = _ctx({"step": "lots", "max": None})

        action.on_press(ctx)

        ctx.set_title.assert_called_with("1")


class TestRender:
    def test_default_background_is_the_counter_blue(self, counter):
        image = _image(counter.render(0, {}))

        assert_that(image.size).is_equal_to((144, 144))
        assert_that(image.getpixel((2, 2))).is_equal_to((31, 97, 141))

    def test_custom_background_and_invalid_colour_fallback(self, counter):
        assert_that(_image(counter.render(0, {"background": "#ff0000"})).getpixel((2, 2))).is_equal_to((255, 0, 0))
        assert_that(_image(counter.render(0, {"background": "red"})).getpixel((2, 2))).is_equal_to((31, 97, 141))

    @pytest.mark.parametrize("position,band", [("top", (0, 40)), ("middle", (52, 92)), ("bottom", (104, 144))])
    def test_title_is_drawn_at_its_position(self, counter, position, band):
        settings = {"title": "WWWW", "title_position": position, "title_color": "#ffff00", "title_size": 14}

        image = _image(counter.render(8, settings))

        yellow_rows = {y for y in range(144) for x in range(144) if image.getpixel((x, y)) == (255, 255, 0)}
        assert_that(yellow_rows).is_not_empty()
        assert_that(min(yellow_rows)).is_greater_than_or_equal_to(band[0])
        assert_that(max(yellow_rows)).is_less_than(band[1])

    def test_outline_is_drawn_only_when_set(self, counter):
        settings = {"title": "WWWW", "title_color": "#ffff00", "title_outline_width": 2}

        plain = _image(counter.render(0, settings))
        outlined = _image(counter.render(0, {**settings, "title_outline": "#ff00ff"}))

        magenta = (255, 0, 255)
        assert_that(any(p == magenta for p in plain.get_flattened_data())).is_false()
        assert_that(any(p == magenta for p in outlined.get_flattened_data())).is_true()

    def test_unknown_position_uses_default(self, counter):
        assert_that(counter.render(0, {"title": "x", "title_position": "sideways"})).is_equal_to(
            counter.render(0, {"title": "x", "title_position": "bottom"})
        )

    def test_missing_fontconfig_falls_back(self, counter):
        counter._font_file.cache_clear()  # pylint: disable=protected-access
        with patch.object(counter.subprocess, "run", side_effect=FileNotFoundError("fc-match")):
            data = counter.render(0, {"title": "x", "title_font": "Anything"})
        counter._font_file.cache_clear()  # pylint: disable=protected-access

        assert_that(_image(data).size).is_equal_to((144, 144))
