import json
from typing import Any

from assertpy import assert_that
from PyQt6.QtCore import QByteArray, QMimeData, QPointF, Qt
from PyQt6.QtGui import QDragEnterEvent, QDropEvent

from decker.client.widgets.slots_edit import SlotsEdit, _SlotButton
from decker.common.slots import SWITCH_CARD_ID

_CARDS = [{"plugin_uuid": "p", "card_uuid": "c", "card_name": "Clock"}]
_ACTIONS = [{"action_uuid": "http", "action_name": "HTTP Request"}]
_CARD = {"plugin_uuid": "p", "plugin_name": "P", "card_uuid": "c", "card_name": "Clock"}
_ACTION = {"plugin_uuid": "core", "card_uuid": "run", "preset_action": "http"}


def _edit() -> SlotsEdit:
    return SlotsEdit(catalog=lambda: (_CARDS, _ACTIONS))


def _mime(payload: dict[str, Any]) -> QMimeData:
    mime = QMimeData()
    mime.setData("application/x-decker-card", QByteArray(json.dumps(payload).encode()))
    return mime


def _drop(button: _SlotButton, payload: dict[str, Any]) -> None:
    mime = _mime(payload)  # the event does not own it
    event = QDropEvent(
        QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    )
    button.dropEvent(event)


def _enter_accepted(button: _SlotButton, payload: dict[str, Any]) -> bool:
    mime = _mime(payload)  # the event does not own it
    event = QDragEnterEvent(
        QPointF(5, 5).toPoint(),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    event.ignore()
    button.dragEnterEvent(event)
    return event.isAccepted()


class TestSlotsEdit:  # pylint: disable=protected-access
    def test_drop_card_fills_slot_and_emits_changed(self, qapp):  # pylint: disable=unused-argument
        edit = _edit()
        changes: list[int] = []
        edit.changed.connect(lambda: changes.append(1))

        _drop(edit._buttons["press"], _CARD)

        assert_that(edit.slot_value("press")).is_equal_to(
            {"kind": "card", "plugin": "p", "card": "c", "settings": {}, "appearance": {}}
        )
        assert_that(changes).is_length(1)
        assert_that(edit._buttons["press"].item_text()).is_equal_to("Clock")

    def test_drop_preset_action_fills_action_slot(self, qapp):  # pylint: disable=unused-argument
        edit = _edit()

        _drop(edit._buttons["long_press"], _ACTION)

        assert_that(edit.slot_value("long_press")).is_equal_to({"kind": "action", "action": "http", "settings": {}})
        assert_that(edit._buttons["long_press"].item_text()).is_equal_to("HTTP Request")

    def test_display_rejects_action_drop(self, qapp):  # pylint: disable=unused-argument
        edit = _edit()
        button = edit._buttons["display"]

        _drop(button, _ACTION)

        assert_that(_enter_accepted(button, _ACTION)).is_false()
        assert_that(_enter_accepted(button, _CARD)).is_true()
        assert_that(edit.slot_value("display")).is_none()

    def test_switch_card_drop_rejected(self, qapp):  # pylint: disable=unused-argument
        edit = _edit()
        payload = {**_CARD, "card_uuid": SWITCH_CARD_ID}

        for name, button in edit._buttons.items():
            _drop(button, payload)
            assert_that(_enter_accepted(button, payload)).is_false()
            assert_that(edit.slot_value(name)).is_none()

    def test_clear_badge_empties_slot(self, qapp):  # pylint: disable=unused-argument
        edit = _edit()
        _drop(edit._buttons["press"], _CARD)
        changes: list[int] = []
        edit.changed.connect(lambda: changes.append(1))

        edit._buttons["press"].clear_button.click()

        assert_that(edit.slot_value("press")).is_none()
        assert_that(changes).is_length(1)

    def test_click_selects_slot_and_emits_selected_changed(self, qapp):  # pylint: disable=unused-argument
        edit = _edit()
        selected: list[str] = []
        edit.selected_changed.connect(selected.append)

        edit._buttons["double_press"].clicked.emit("double_press")

        assert_that(edit.selected_slot()).is_equal_to("double_press")
        assert_that(selected).is_equal_to(["double_press"])

    def test_unknown_items_show_fallback_label(self, qapp):  # pylint: disable=unused-argument
        edit = _edit()
        edit.set_value({"press": {"kind": "card", "plugin": "x", "card": "gone", "settings": {}, "appearance": {}}})

        assert_that(edit._buttons["press"].item_text()).contains("missing card")

    def test_set_value_does_not_emit_changed(self, qapp):  # pylint: disable=unused-argument
        edit = _edit()
        changes: list[int] = []
        edit.changed.connect(lambda: changes.append(1))

        edit.set_value({"press": {"kind": "action", "action": "http", "settings": {"a": 1}}})

        assert_that(changes).is_empty()
        assert_that(edit.value()["press"]).is_equal_to({"kind": "action", "action": "http", "settings": {"a": 1}})
