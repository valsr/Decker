"""Frameless popup listing connected devices, anchored above the device-switcher button."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QFrame, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from decker.common.model import DeviceHardwareInfo


class DeviceSwitcherPopup(QFrame):
    """Lists connected devices; selecting one emits device_selected and closes.

    Esc or a click outside the popup dismisses it without emitting anything.
    """

    device_selected = pyqtSignal(object)  # DeviceHardwareInfo

    def __init__(self, devices: list[DeviceHardwareInfo], parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setFrameShape(QFrame.Shape.Box)
        self._devices = devices

        self._list = QListWidget()
        for device in devices:
            serial = device.serial or ""
            label = f"{device.type}  ·  {serial}"
            item = QListWidgetItem(label)
            item.setData(1, device.id)
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
        device_id = item.data(1)
        device = next((d for d in self._devices if d.id == device_id), None)
        if device is not None:
            self.device_selected.emit(device)
        self.close()

    def keyPressEvent(self, event: QKeyEvent | None) -> None:  # pylint: disable=invalid-name
        """Close the popup on Escape without emitting device_selected."""
        if event is not None and event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
