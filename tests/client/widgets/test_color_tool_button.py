"""Tests for decker.client.widgets.color_tool_button."""

from typing import Any

from assertpy import assert_that
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QColorDialog

from decker.client.widgets.color_tool_button import ColorToolButton, hex_to_qcolor, qcolor_to_hex

_GET_COLOR = "decker.client.widgets.color_tool_button.QColorDialog.getColor"


def _none_action(button: ColorToolButton) -> Any:
    return next((a for a in button.menu().actions() if a.text() == "None"), None)


class TestHexConversion:
    def test_opaque_colour_is_six_digits(self):
        assert_that(qcolor_to_hex(QColor(17, 34, 51))).is_equal_to("#112233")

    def test_translucent_colour_is_rrggbbaa(self):
        assert_that(qcolor_to_hex(QColor(17, 34, 51, 128))).is_equal_to("#11223380")

    def test_parses_rrggbbaa_with_alpha_last(self):
        color = hex_to_qcolor("#11223380")
        assert color is not None
        assert_that((color.red(), color.green(), color.blue(), color.alpha())).is_equal_to((17, 34, 51, 128))

    def test_rejects_malformed(self):
        for bad in ("red", "#12", "#1122334", "112233", ""):
            assert_that(hex_to_qcolor(bad)).is_none()


class TestColorToolButton:
    def test_set_color_updates_property_without_signal(self, qapp):  # pylint: disable=unused-argument
        button = ColorToolButton("T")
        emitted: list[Any] = []
        button.color_changed.connect(emitted.append)

        button.set_color("#11223380")

        assert_that(button.color).is_equal_to("#11223380")
        assert_that(emitted).is_empty()

    def test_pick_emits_color_changed(self, qapp, monkeypatch):  # pylint: disable=unused-argument
        button = ColorToolButton("T")
        emitted: list[Any] = []
        button.color_changed.connect(emitted.append)
        monkeypatch.setattr(_GET_COLOR, lambda *_a, **_k: QColor("#00ff00"))

        button.click()

        assert_that(button.color).is_equal_to("#00ff00")
        assert_that(emitted).is_equal_to(["#00ff00"])

    def test_pick_keeps_alpha(self, qapp, monkeypatch):  # pylint: disable=unused-argument
        button = ColorToolButton("T")
        monkeypatch.setattr(_GET_COLOR, lambda *_a, **_k: QColor(17, 34, 51, 128))

        button.click()

        assert_that(button.color).is_equal_to("#11223380")

    def test_dialog_opened_with_alpha_channel_and_current_colour(
        self, qapp, monkeypatch
    ):  # pylint: disable=unused-argument
        button = ColorToolButton("T")
        button.set_color("#11223380")
        seen: dict[str, Any] = {}

        def fake(initial: QColor, _parent: Any, _title: str, options: Any) -> QColor:
            seen["alpha"] = initial.alpha()
            seen["options"] = options
            return QColor()

        monkeypatch.setattr(_GET_COLOR, fake)
        button.click()

        assert_that(seen["alpha"]).is_equal_to(128)
        assert_that(bool(seen["options"] & QColorDialog.ColorDialogOption.ShowAlphaChannel)).is_true()

    def test_cancelled_or_same_colour_does_not_emit(self, qapp, monkeypatch):  # pylint: disable=unused-argument
        button = ColorToolButton("T")
        button.set_color("#000000")
        emitted: list[Any] = []
        button.color_changed.connect(emitted.append)
        for result in (QColor(), QColor("#000000")):
            monkeypatch.setattr(_GET_COLOR, lambda *_a, r=result, **_k: r)
            button.click()

        assert_that(emitted).is_empty()
        assert_that(button.color).is_equal_to("#000000")

    def test_none_action_clears_color_and_emits_none(self, qapp):  # pylint: disable=unused-argument
        button = ColorToolButton("A", allow_none=True)
        button.set_color("#ff0000")
        emitted: list[Any] = []
        button.color_changed.connect(emitted.append)

        _none_action(button).trigger()

        assert_that(button.color).is_none()
        assert_that(emitted).is_equal_to([None])

    def test_none_action_absent_unless_allowed(self, qapp):  # pylint: disable=unused-argument
        assert_that(_none_action(ColorToolButton("T"))).is_none()

    def test_invalid_color_ignored(self, qapp):  # pylint: disable=unused-argument
        button = ColorToolButton("T")
        button.set_color("#ff0000")

        button.set_color("not a colour")

        assert_that(button.color).is_equal_to("#ff0000")

    def test_set_color_none_only_when_allowed(self, qapp):  # pylint: disable=unused-argument
        optional = ColorToolButton("A", allow_none=True)
        optional.set_color("#ff0000")
        optional.set_color(None)
        required = ColorToolButton("T")
        required.set_color("#ff0000")
        required.set_color(None)

        assert_that(optional.color).is_none()
        assert_that(required.color).is_equal_to("#ff0000")
