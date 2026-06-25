from assertpy import assert_that
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent

from decker.client.widgets.device_switcher_popup import DeviceSwitcherPopup

_DEVICES = [
    {"id": "aabbccdd", "type": "Stream Deck", "serial": "ABC123"},
    {"id": "11223344", "type": "Stream Deck XL", "serial": "XYZ999"},
]


class TestDeviceSwitcherPopup:
    def test_lists_all_devices(self, qapp):  # pylint: disable=unused-argument
        popup = DeviceSwitcherPopup(_DEVICES)
        assert_that(popup._list.count()).is_equal_to(2)  # pylint: disable=protected-access

    def test_item_text_includes_type_and_serial(self, qapp):  # pylint: disable=unused-argument
        popup = DeviceSwitcherPopup(_DEVICES)
        item = popup._list.item(0)  # pylint: disable=protected-access
        assert item is not None
        assert_that(item.text()).contains("Stream Deck").contains("ABC123")

    def test_clicking_item_emits_device_selected_with_id(self, qapp):  # pylint: disable=unused-argument
        popup = DeviceSwitcherPopup(_DEVICES)
        received: list[str] = []
        popup.device_selected.connect(received.append)

        item = popup._list.item(1)  # pylint: disable=protected-access
        assert item is not None
        popup._on_item_clicked(item)  # pylint: disable=protected-access

        assert_that(received).is_equal_to(["11223344"])

    def test_escape_key_closes_without_emitting(self, qapp):  # pylint: disable=unused-argument
        popup = DeviceSwitcherPopup(_DEVICES)
        received: list[str] = []
        popup.device_selected.connect(received.append)
        popup.show()

        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        popup.keyPressEvent(event)

        assert_that(received).is_empty()
        assert_that(popup.isVisible()).is_false()

    def test_non_escape_key_does_not_close(self, qapp):  # pylint: disable=unused-argument
        popup = DeviceSwitcherPopup(_DEVICES)
        popup.show()

        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)
        popup.keyPressEvent(event)

        assert_that(popup.isVisible()).is_true()

    def test_empty_device_list(self, qapp):  # pylint: disable=unused-argument
        popup = DeviceSwitcherPopup([])
        assert_that(popup._list.count()).is_equal_to(0)  # pylint: disable=protected-access
