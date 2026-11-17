"""Tests for decker.client.widgets.text_style_edit."""

# pylint: disable=protected-access,unused-argument
from assertpy import assert_that
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtTest import QTest

from decker.client.widgets.text_style_edit import TextStyleEdit
from decker.common.text_style import TEXT_STYLE_DEFAULTS


class TestTextStyleEdit:
    def test_value_is_normalised_dict(self, qapp):
        assert_that(TextStyleEdit().value()).is_equal_to(dict(TEXT_STYLE_DEFAULTS))

    def test_typing_emits_value_changed_and_updates_text(self, qapp):
        edit = TextStyleEdit()
        emitted: list[None] = []
        edit.value_changed.connect(lambda: emitted.append(None))

        QTest.keyClicks(edit._line, "Hi")

        assert_that(emitted).is_not_empty()
        assert_that(edit.value()["text"]).is_equal_to("Hi")

    def test_style_edit_emits_value_changed(self, qapp):
        edit = TextStyleEdit()
        emitted: list[None] = []
        edit.value_changed.connect(lambda: emitted.append(None))

        edit._toolbar._bold.click()

        assert_that(emitted).is_not_empty()
        assert_that(edit.value()["bold"]).is_true()

    def test_set_value_emits_nothing_and_updates_controls(self, qapp):
        edit = TextStyleEdit()
        emitted: list[None] = []
        edit.value_changed.connect(lambda: emitted.append(None))

        edit.set_value({"text": "Play", "bold": True, "position": "top"})

        assert_that(emitted).is_empty()
        assert_that(edit._line.text()).is_equal_to("Play")
        assert_that(edit._toolbar._bold.isChecked()).is_true()
        assert_that(edit.value()).is_equal_to({**TEXT_STYLE_DEFAULTS, "text": "Play", "bold": True, "position": "top"})

    def test_set_value_while_popup_open_emits_nothing(self, qapp):
        edit = TextStyleEdit()
        edit.show()
        edit._cog.trigger()
        emitted: list[None] = []
        edit.value_changed.connect(lambda: emitted.append(None))

        edit.set_value({"text": "X", "italic": True})

        assert_that(edit._toolbar.isVisible()).is_true()
        assert_that(emitted).is_empty()
        assert_that(edit._toolbar._italic.isChecked()).is_true()
        edit._toolbar.close()

    def test_set_value_with_garbage_uses_defaults(self, qapp):
        edit = TextStyleEdit()
        edit.set_value("garbage")
        assert_that(edit.value()).is_equal_to(dict(TEXT_STYLE_DEFAULTS))
        edit.set_value({"size": "abc", "position": "left", "text": "ok"})
        assert_that(edit.value()).is_equal_to({**TEXT_STYLE_DEFAULTS, "text": "ok"})

    def test_cog_toggles_popup(self, qapp):
        edit = TextStyleEdit()
        edit.show()

        edit._cog.trigger()
        assert_that(edit._toolbar.isVisible()).is_true()
        edit._cog.trigger()
        assert_that(edit._toolbar.isVisible()).is_false()

    def test_escape_closes_popup_and_unchecks_cog(self, qapp):
        edit = TextStyleEdit()
        edit.show()
        edit._cog.trigger()

        QTest.keyClick(edit._toolbar, Qt.Key.Key_Escape)

        assert_that(edit._toolbar.isVisible()).is_false()
        assert_that(edit._cog.isChecked()).is_false()

    def test_popup_clamped_to_screen_bottom_right(self, qapp):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        edit = TextStyleEdit()
        edit.show()
        edit.move(screen.right() - 40, screen.bottom() - 10)

        edit._cog.trigger()

        assert_that(screen.contains(edit._toolbar.geometry())).is_true()
        edit._toolbar.close()

    def test_popup_opens_below_field_when_there_is_room(self, qapp):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        edit = TextStyleEdit()
        edit.show()
        edit.move(screen.left() + 200, screen.top() + 20)

        edit._cog.trigger()

        field_bottom = edit.mapToGlobal(edit.rect().bottomLeft()).y()
        assert_that(edit._toolbar.geometry().top()).is_greater_than_or_equal_to(field_bottom)
        edit._toolbar.close()
