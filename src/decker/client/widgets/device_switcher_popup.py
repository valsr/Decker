"""Frameless popup listing connected devices, anchored above the device-switcher button."""

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QFrame, QListWidget, QListWidgetItem, QVBoxLayout, QWidget


class DeviceSwitcherPopup(QFrame):
    """Lists connected devices; selecting one emits device_selected and closes.

    Esc or a click outside the popup dismisses it without emitting anything.
    """

    device_selected = pyqtSignal(str)

    def __init__(self, devices: list[dict[str, Any]], parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setFrameShape(QFrame.Shape.Box)

        self._list = QListWidget()
        for device in devices:
            serial = str(device.get("serial") or "")
            device_type = str(device.get("type", "Stream Deck"))
            item = QListWidgetItem(f"{device_type}  ·  {serial}")
            item.setData(1, serial)
            self._list.addItem(item)
        self._list.itemClicked.connect(self._on_item_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._list)

    def show_above(self, anchor: QWidget) -> None:
        """Position the popup directly above anchor (in global coordinates) and show it."""
        self.adjustSize()
        top_left = anchor.mapToGlobal(anchor.rect().topLeft())
        top_left.setY(top_left.y() - self.height())
        self.move(top_left)
        self.show()

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self.device_selected.emit(str(item.data(1)))
        self.close()

    def keyPressEvent(self, event: QKeyEvent | None) -> None:  # pylint: disable=invalid-name
        """Close the popup on Escape without emitting device_selected."""
        if event is not None and event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
