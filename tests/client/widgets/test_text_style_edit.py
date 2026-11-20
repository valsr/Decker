"""Tests for decker.client.widgets.text_style_edit."""

# pylint: disable=protected-access,unused-argument
from assertpy import assert_that
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QWidget

from decker.client.widgets.text_style_edit import TextStyleEdit
from decker.common.text_style import TEXT_STYLE_DEFAULTS


class TestTextStyleEdit:
    def test_value_is_normalised_dict(self, qapp):
        assert_that(TextStyleEdit().value()).is_equal_to(dict(TEXT_STYLE_DEFAULTS))

    def test_typing_emits_value_changed_and_updates_text(self, qapp):
        edit = TextStyleEdit()
        emitted: list[None] = []
        edit.value_changed.connect(lambda: emitted.append(None))

        QTest.keyClicks(edit._line, "Hi")  # type: ignore[call-arg, arg-type]  # PyQt6 stub declares self

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

    def test_set_value_with_garbage_uses_defaults(self, qapp):
        edit = TextStyleEdit()
        edit.set_value("garbage")
        assert_that(edit.value()).is_equal_to(dict(TEXT_STYLE_DEFAULTS))
        edit.set_value({"size": "abc", "position": "left", "text": "ok"})
        assert_that(edit.value()).is_equal_to({**TEXT_STYLE_DEFAULTS, "text": "ok"})

    def test_toolbar_is_hidden_until_the_field_is_entered(self, qapp):
        edit = TextStyleEdit()
        edit.show()

        assert_that(edit._toolbar.isVisible()).is_false()
        edit._on_focus_changed(None, edit._line)

        assert_that(edit._toolbar.isVisible()).is_true()

    def test_toolbar_stays_while_focus_is_inside_it_and_hides_when_focus_leaves(self, qapp):
        edit = TextStyleEdit()
        outside = QWidget()
        edit.show()
        edit._on_focus_changed(None, edit._line)

        edit._on_focus_changed(edit._line, edit._toolbar._bold)
        assert_that(edit._toolbar.isVisible()).is_true()
        edit._on_focus_changed(edit._toolbar._bold, outside)

        assert_that(edit._toolbar.isVisible()).is_false()

    def test_toolbar_stays_open_while_a_colour_dialog_is_up(self, qapp):
        edit = TextStyleEdit()
        outside = QWidget()
        edit.show()
        edit._on_focus_changed(None, edit._line)

        edit._toolbar.picker_opened.emit()
        edit._on_focus_changed(edit._line, outside)
        assert_that(edit._toolbar.isVisible()).is_true()

        edit._toolbar.picker_closed.emit()
        assert_that(edit._toolbar.isVisible()).is_false()
