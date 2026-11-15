"""Tests for decker.client.widgets.color_button."""

from assertpy import assert_that
from PyQt6.QtGui import QColor

from decker.client.widgets.color_button import ColorButton


class TestColorButton:
    def test_shows_colour_name_and_swatch(self, qapp):  # pylint: disable=unused-argument
        button = ColorButton("#1F618D")

        assert_that(button.color).is_equal_to("#1f618d")
        assert_that(button.text()).is_equal_to("#1f618d")
        assert_that(button.icon().isNull()).is_false()

    def test_set_color_ignores_invalid(self, qapp):  # pylint: disable=unused-argument
        button = ColorButton("#000000")

        button.set_color("not a colour")
        assert_that(button.color).is_equal_to("#000000")
        button.set_color("#ff0000")
        assert_that(button.color).is_equal_to("#ff0000")

    def test_click_picks_colour_and_emits(self, qapp, monkeypatch):  # pylint: disable=unused-argument
        button = ColorButton("#000000")
        emitted: list[str] = []
        button.color_changed.connect(emitted.append)
        monkeypatch.setattr(
            "decker.client.widgets.color_button.QColorDialog.getColor", lambda *_args: QColor("#00ff00")
        )

        button.click()

        assert_that(button.color).is_equal_to("#00ff00")
        assert_that(emitted).is_equal_to(["#00ff00"])

    def test_cancelled_or_same_colour_does_not_emit(self, qapp, monkeypatch):  # pylint: disable=unused-argument
        button = ColorButton("#000000")
        emitted: list[str] = []
        button.color_changed.connect(emitted.append)
        for result in (QColor(), QColor("#000000")):
            monkeypatch.setattr("decker.client.widgets.color_button.QColorDialog.getColor", lambda *_args, r=result: r)
            button.click()

        assert_that(emitted).is_empty()
        assert_that(button.color).is_equal_to("#000000")
