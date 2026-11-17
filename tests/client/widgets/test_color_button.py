"""Tests for decker.client.widgets.color_button."""

from assertpy import assert_that
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QColorDialog

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


class TestColorButtonAlpha:
    def test_shows_rgba_name(self, qapp):  # pylint: disable=unused-argument
        button = ColorButton("#000000", alpha=True)

        button.set_color("#11223380")

        assert_that(button.color).is_equal_to("#11223380")
        assert_that(button.text()).is_equal_to("#11223380")

    def test_opaque_alpha_colour_is_six_digits(self, qapp):  # pylint: disable=unused-argument
        assert_that(ColorButton("#112233", alpha=True).color).is_equal_to("#112233")

    def test_pick_keeps_alpha_and_asks_for_alpha_channel(self, qapp, monkeypatch):  # pylint: disable=unused-argument
        button = ColorButton("#000000", alpha=True)
        emitted: list[str] = []
        button.color_changed.connect(emitted.append)
        seen: dict = {}

        def fake(_initial, _parent, _title, options=None):
            seen["options"] = options
            return QColor(17, 34, 51, 128)

        monkeypatch.setattr("decker.client.widgets.color_button.QColorDialog.getColor", fake)
        button.click()

        assert_that(emitted).is_equal_to(["#11223380"])
        assert_that(bool(seen["options"] & QColorDialog.ColorDialogOption.ShowAlphaChannel)).is_true()

    def test_opaque_button_rejects_rgba_names(self, qapp):  # pylint: disable=unused-argument
        button = ColorButton("#112233")

        button.set_color("#11223380")

        assert_that(button.color).is_equal_to("#112233")

    def test_swatch_icon_present_for_transparent_colour(self, qapp):  # pylint: disable=unused-argument
        button = ColorButton("#00000000", alpha=True)

        assert_that(button.icon().isNull()).is_false()
        assert_that(button.color).is_equal_to("#00000000")


class TestColorButtonSwatchOnly:
    def test_hiding_the_name_leaves_only_the_swatch_and_a_tooltip(self, qapp):  # pylint: disable=unused-argument
        button = ColorButton("#11223380", alpha=True)

        button.set_show_name(False)

        assert_that(button.text()).is_equal_to("")
        assert_that(button.icon().isNull()).is_false()
        assert_that(button.toolTip()).is_equal_to("#11223380")

    def test_tooltip_follows_the_colour(self, qapp):  # pylint: disable=unused-argument
        button = ColorButton("#000000")
        button.set_show_name(False)

        button.set_color("#ff0000")

        assert_that(button.toolTip()).is_equal_to("#ff0000")
        assert_that(button.text()).is_equal_to("")

    def test_showing_the_name_again_restores_the_text(self, qapp):  # pylint: disable=unused-argument
        button = ColorButton("#ff0000")
        button.set_show_name(False)

        button.set_show_name(True)

        assert_that(button.text()).is_equal_to("#ff0000")
