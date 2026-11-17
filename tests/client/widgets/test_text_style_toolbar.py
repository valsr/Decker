"""Tests for decker.client.widgets.text_style_toolbar."""

# pylint: disable=protected-access,unused-argument
from typing import Any

import pytest
from assertpy import assert_that
from PyQt6.QtGui import QFontDatabase, QShortcut
from PyQt6.QtWidgets import QToolButton

from decker.client.widgets.text_style_toolbar import TextStyleToolbar
from decker.common.text_style import TEXT_STYLE_DEFAULTS


def _style(**overrides: Any) -> dict[str, Any]:
    style = {k: v for k, v in TEXT_STYLE_DEFAULTS.items() if k != "text"}
    style.update(overrides)
    return style


def _family() -> str:
    families = QFontDatabase.families()
    assert families, "no fonts available to the test platform"
    return families[0]


class TestTextStyleToolbar:
    def test_set_style_round_trips(self, qapp):
        toolbar = TextStyleToolbar()
        style = _style(
            font=_family(),
            size=20,
            bold=True,
            italic=True,
            underline=True,
            strike=True,
            position="top",
            color="#11223380",
            outline="#445566",
            outline_width=3,
            visible=False,
        )

        toolbar.set_style(style)

        assert_that(toolbar.style_value()).is_equal_to(style)

    def test_style_value_excludes_text(self, qapp):
        assert_that(TextStyleToolbar().style_value()).does_not_contain_key("text")

    def test_set_style_emits_nothing(self, qapp):
        toolbar = TextStyleToolbar()
        emitted: list[None] = []
        toolbar.style_changed.connect(lambda: emitted.append(None))

        toolbar.set_style(_style(bold=True, size=30, position="top", outline="#ff0000"))

        assert_that(emitted).is_empty()

    @pytest.mark.parametrize(
        "action",
        [
            lambda t: t._bold.click(),
            lambda t: t._italic.click(),
            lambda t: t._underline.click(),
            lambda t: t._strike.click(),
            lambda t: t._positions["top"].click(),
            lambda t: t._size.setValue(30),
            lambda t: t._color.color_changed.emit("#112233"),
            lambda t: t._outline.color_changed.emit("#112233"),
            lambda t: t._width.setValue(4),
            lambda t: t._visible.click(),
        ],
    )
    def test_style_changed_on_each_control(self, qapp, action):
        toolbar = TextStyleToolbar()
        toolbar.set_style(_style(outline="#ff0000"))
        emitted: list[None] = []
        toolbar.style_changed.connect(lambda: emitted.append(None))

        action(toolbar)

        assert_that(emitted).is_not_empty()

    def test_position_buttons_are_exclusive(self, qapp):
        toolbar = TextStyleToolbar()

        toolbar._positions["top"].click()

        assert_that(toolbar.style_value()["position"]).is_equal_to("top")
        assert_that([p for p, b in toolbar._positions.items() if b.isChecked()]).is_equal_to(["top"])

    def test_outline_none_disables_outline_width(self, qapp):
        toolbar = TextStyleToolbar()

        toolbar.set_style(_style(outline=None))

        assert_that(toolbar._width.isEnabled()).is_false()
        assert_that(toolbar._width_minus.isEnabled()).is_false()
        assert_that(toolbar._width_plus.isEnabled()).is_false()

    def test_outline_width_enabled_when_outline_set(self, qapp):
        toolbar = TextStyleToolbar()
        toolbar.set_style(_style(outline=None))

        toolbar._outline.color_changed.emit("#ff0000")

        assert_that(toolbar._width.isEnabled()).is_true()
        toolbar._outline.color_changed.emit(None)
        assert_that(toolbar._width.isEnabled()).is_false()

    def test_size_plus_minus_buttons_respect_range(self, qapp):
        toolbar = TextStyleToolbar()
        toolbar.set_style(_style(size=48))
        toolbar._size_plus.click()
        assert_that(toolbar.style_value()["size"]).is_equal_to(48)
        toolbar.set_style(_style(size=4))
        toolbar._size_minus.click()
        assert_that(toolbar.style_value()["size"]).is_equal_to(4)
        toolbar.set_style(_style(size=12))
        toolbar._size_plus.click()
        assert_that(toolbar.style_value()["size"]).is_equal_to(13)

    def test_outline_width_plus_minus_respect_range(self, qapp):
        toolbar = TextStyleToolbar()
        toolbar.set_style(_style(outline="#ff0000", outline_width=6))
        toolbar._width_plus.click()
        assert_that(toolbar.style_value()["outline_width"]).is_equal_to(6)
        toolbar._width.setValue(1)
        toolbar._width_minus.click()
        assert_that(toolbar.style_value()["outline_width"]).is_equal_to(1)

    @pytest.mark.parametrize("key,name", [("Ctrl+B", "bold"), ("Ctrl+I", "italic"), ("Ctrl+U", "underline")])
    def test_shortcuts_toggle_styles(self, qapp, key, name):
        toolbar = TextStyleToolbar()
        shortcut = next(s for s in toolbar.findChildren(QShortcut) if s.key().toString() == key)

        shortcut.activated.emit()

        assert_that(toolbar.style_value()[name]).is_true()

    def test_tooltips_name_the_shortcuts(self, qapp):
        toolbar = TextStyleToolbar()

        assert_that(toolbar._bold.toolTip()).contains("Ctrl+B")
        assert_that(toolbar._italic.toolTip()).contains("Ctrl+I")
        assert_that(toolbar._underline.toolTip()).contains("Ctrl+U")

    def test_toolbar_is_a_single_row(self, qapp):
        toolbar = TextStyleToolbar()

        assert_that(len(toolbar.findChildren(QToolButton))).is_greater_than(10)
        assert_that(toolbar.sizeHint().height()).is_less_than(60)
