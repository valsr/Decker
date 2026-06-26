"""Button grid matching the active device's key layout."""

import base64
import json
from typing import Any

from PyQt6.QtCore import QByteArray, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QMouseEvent, QPixmap
from PyQt6.QtWidgets import QGridLayout, QPushButton, QVBoxLayout, QWidget

from decker.common.model import KeyInfo

_LONG_PRESS_MS = 500
_MIME_TYPE = "application/x-decker-action"


class KeyButtonWidget(QPushButton):
    """Square button for one key: supports drag-and-drop assignment and long-press detection."""

    action_dropped = pyqtSignal(int, object)
    long_pressed = pyqtSignal(int)

    def __init__(self, index: int, width: int, height: int) -> None:
        super().__init__()
        self.setFixedSize(width, height)
        self.index = index
        self._label: str = str(index + 1)
        self._refresh_text()
        self.setAcceptDrops(True)
        self._long_press_active = False
        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.setInterval(_LONG_PRESS_MS)
        self._long_press_timer.timeout.connect(self._on_long_press_fired)

    def set_label(self, label: str) -> None:
        """Update the display label (shows label if set, otherwise key number)."""
        self._label = label
        if not self.icon().isNull():
            return  # image takes precedence; label shown as overlay only if no image
        self._refresh_text()

    def set_image(self, image_b64: str | None) -> None:
        """Set or clear the key image from a base64-encoded PNG."""
        if not image_b64:
            self.setIcon(QIcon())
            self.setIconSize(QSize(0, 0))
            self._refresh_text()
            return
        raw = base64.b64decode(image_b64)
        pixmap = QPixmap()
        pixmap.loadFromData(QByteArray(raw))
        self.setIcon(QIcon(pixmap))
        self.setIconSize(QSize(68, 68))
        self.setText("")

    # ------------------------------------------------------------------
    # Long-press override
    # ------------------------------------------------------------------

    def mousePressEvent(self, e: QMouseEvent | None) -> None:
        self._long_press_active = False
        self._long_press_timer.start()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent | None) -> None:
        self._long_press_timer.stop()
        if self._long_press_active:
            self._long_press_active = False
            self.setDown(False)
            self.update()
            return
        super().mouseReleaseEvent(e)

    def _on_long_press_fired(self) -> None:
        self._long_press_active = True
        self.long_pressed.emit(self.index)

    # ------------------------------------------------------------------
    # Drag-and-drop target
    # ------------------------------------------------------------------

    def dragEnterEvent(self, a0: Any) -> None:
        if a0.mimeData().hasFormat(_MIME_TYPE):
            a0.acceptProposedAction()

    def dropEvent(self, a0: Any) -> None:
        raw: bytes = bytes(a0.mimeData().data(_MIME_TYPE))
        try:
            data: dict[str, Any] = json.loads(raw.decode())
        except (ValueError, UnicodeDecodeError):
            return
        self.action_dropped.emit(self.index, data)
        a0.acceptProposedAction()

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _refresh_text(self) -> None:
        self.setText(self._label or str(self.index + 1))


class ButtonGridWidget(QWidget):
    """Renders a placeholder key grid sized from the active device's key count."""

    key_selected = pyqtSignal(int)
    key_long_pressed = pyqtSignal(int)
    action_dropped = pyqtSignal(int, object)

    def __init__(self) -> None:
        super().__init__()
        self._grid_layout = QGridLayout()
        self._grid_layout.setSpacing(4)
        self._key_info: list[KeyInfo] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.addLayout(self._grid_layout)
        outer.addStretch()

    @property
    def key_count(self) -> int:
        """The number of keys currently rendered."""
        return len(self._key_info)

    def build(self, key_information: list[KeyInfo]):
        self._key_info = key_information

        # clear existing widgets
        while (item := self._grid_layout.takeAt(0)) is not None:
            if widget := item.widget():
                widget.deleteLater()
        self._buttons: dict[int, KeyButtonWidget] = {}

        for index in range(self.key_count):
            key = self._key_info[index]
            row, col = key.row, key.col
            button = KeyButtonWidget(index, key.pixel_width, key.pixel_height)
            button.clicked.connect(lambda _checked=False, i=index: self.key_selected.emit(i))
            button.long_pressed.connect(self.key_long_pressed.emit)
            button.action_dropped.connect(self.action_dropped.emit)
            self._grid_layout.addWidget(button, row, col)
            self._buttons[index] = button

    def set_key_label(self, key_index: int, label: str) -> None:
        """Update the display label for a single key button."""
        if button := self._buttons.get(key_index):
            button.set_label(label)

    def set_key_image(self, key_index: int, image_b64: str | None) -> None:
        """Update the image for a single key button from a base64-encoded PNG."""
        if button := self._buttons.get(key_index):
            button.set_image(image_b64)
