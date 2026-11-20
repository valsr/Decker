"""Tests for decker.client.widgets.text_style_edit."""

# pylint: disable=protected-access,unused-argument
from assertpy import assert_that
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QGuiApplication
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QWidget

from decker.client.widgets.text_style_edit import TextStyleEdit
from decker.common.text_style import TEXT_STYLE_DEFAULTS


def _screen() -> QRect:
    primary = QGuiApplication.primaryScreen()
    assert primary is not None
    return primary.availableGeometry()


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

        QTest.keyClick(edit._toolbar, Qt.Key.Key_Escape)  # type: ignore[call-overload]  # PyQt6 stub declares self

        assert_that(edit._toolbar.isVisible()).is_false()
        assert_that(edit._cog.isChecked()).is_false()

    def test_popup_clamped_to_screen_bottom_right(self, qapp):
        screen = _screen()
        edit = TextStyleEdit()
        edit.show()
        edit.move(screen.right() - 40, screen.bottom() - 10)

        edit._cog.trigger()

        assert_that(screen.contains(edit._toolbar.geometry())).is_true()
        edit._toolbar.close()

    def test_popup_opens_below_field_when_there_is_room(self, qapp):
        screen = _screen()
        edit = TextStyleEdit()
        edit.show()
        edit.move(screen.left() + 200, screen.top() + 20)

        edit._cog.trigger()

        field_bottom = edit.mapToGlobal(edit.rect().bottomLeft()).y()
        assert_that(edit._toolbar.geometry().top()).is_greater_than_or_equal_to(field_bottom)
        edit._toolbar.close()


class TestPopupSurvivesColourDialog:
    def _dialog_that_hides_popup(self, edit: TextStyleEdit, result: QColor):
        def fake(*_a, **_k) -> QColor:
            edit._toolbar.hide()  # what a Popup-type window does when a modal dialog opens
            return result

        return fake

    def test_popup_reopens_after_picking_a_colour(self, qapp, monkeypatch):  # pylint: disable=unused-argument
        edit = TextStyleEdit()
        edit.show()
        edit._cog.trigger()
        monkeypatch.setattr(
            "decker.client.widgets.color_tool_button.QColorDialog.getColor",
            self._dialog_that_hides_popup(edit, QColor("#00ff00")),
        )

        edit._toolbar._color.click()

        assert_that(edit._toolbar.isVisible()).is_true()
        assert_that(edit._cog.isChecked()).is_true()
        assert_that(edit.value()["color"]).is_equal_to("#00ff00")
        edit._toolbar.close()

    def test_popup_reopens_after_cancelled_outline_dialog(self, qapp, monkeypatch):  # pylint: disable=unused-argument
        edit = TextStyleEdit()
        edit.show()
        edit._cog.trigger()
        monkeypatch.setattr(
            "decker.client.widgets.color_tool_button.QColorDialog.getColor",
            self._dialog_that_hides_popup(edit, QColor()),
        )

        edit._toolbar._outline.click()

        assert_that(edit._toolbar.isVisible()).is_true()
        assert_that(edit.value()["outline"]).is_none()
        edit._toolbar.close()

    def test_closed_popup_stays_closed_after_dialog(self, qapp, monkeypatch):  # pylint: disable=unused-argument
        edit = TextStyleEdit()
        edit.show()
        monkeypatch.setattr(
            "decker.client.widgets.color_tool_button.QColorDialog.getColor", lambda *_a, **_k: QColor("#00ff00")
        )

        edit._toolbar._color.click()

        assert_that(edit._toolbar.isVisible()).is_false()


class TestColourDialogIsolatedFromPopup:
    def _open_with_host(self, qapp):  # pylint: disable=unused-argument
        host = QWidget()
        edit = TextStyleEdit(host)
        host.show()
        edit._cog.trigger()
        return host, edit

    def test_dialog_is_parented_to_the_editors_window_not_the_popup(
        self, qapp, monkeypatch
    ):  # pylint: disable=unused-argument
        host, edit = self._open_with_host(qapp)
        seen: dict = {}

        def fake(_initial, parent, *_a, **_k) -> QColor:
            seen["parent"] = parent
            return QColor()

        monkeypatch.setattr("decker.client.widgets.color_tool_button.QColorDialog.getColor", fake)
        edit._toolbar._color.click()

        assert_that(seen["parent"].window()).is_same_as(host)
        edit._toolbar.close()

    def test_popup_is_closed_before_the_dialog_opens(self, qapp, monkeypatch):  # pylint: disable=unused-argument
        _host, edit = self._open_with_host(qapp)
        seen: dict = {}

        def fake(*_a, **_k) -> QColor:
            seen["popup_visible"] = edit._toolbar.isVisible()
            return QColor()

        monkeypatch.setattr("decker.client.widgets.color_tool_button.QColorDialog.getColor", fake)
        edit._toolbar._outline.click()

        assert_that(seen["popup_visible"]).is_false()
        assert_that(edit._toolbar.isVisible()).is_true()  # and it is back afterwards
        edit._toolbar.close()


class TestOpensOnEntry:
    def test_entering_the_field_opens_the_popup_but_returning_from_it_does_not(self, qapp):
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QFocusEvent

        edit = TextStyleEdit()
        edit.show()

        edit.eventFilter(edit._line, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason))
        assert_that(edit._toolbar.isVisible()).is_true()
        edit._toolbar.close()
        edit.eventFilter(edit._line, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.PopupFocusReason))

        assert_that(edit._toolbar.isVisible()).is_false()
