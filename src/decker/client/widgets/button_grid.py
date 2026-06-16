"""Button grid matching the active device's key layout."""

import json
import math
from typing import Any

from PyQt6.QtCore import QByteArray, QMimeData, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QDrag, QMouseEvent
from PyQt6.QtWidgets import QGridLayout, QPushButton, QVBoxLayout, QWidget

# (rows, cols) for known Stream Deck key counts; unknown counts fall back to a near-square grid.
_KNOWN_LAYOUTS: dict[int, tuple[int, int]] = {
    6: (2, 3),
    8: (2, 4),
    15: (3, 5),
    32: (4, 8),
}

_LONG_PRESS_MS = 500
_MIME_TYPE = "application/x-decker-action"


def grid_dimensions_for_key_count(key_count: int) -> tuple[int, int]:
    """Return (rows, cols) for key_count, using known Stream Deck layouts where possible."""
    if key_count <= 0:
        return (0, 0)
    if key_count in _KNOWN_LAYOUTS:
        return _KNOWN_LAYOUTS[key_count]
    cols = math.ceil(math.sqrt(key_count))
    rows = math.ceil(key_count / cols)
    return (rows, cols)


class KeyButtonWidget(QPushButton):
    """Square button for one key: supports drag-and-drop assignment and long-press detection."""

    action_dropped = pyqtSignal(int, object)
    long_pressed = pyqtSignal(int)

    def __init__(self, index: int) -> None:
        super().__init__()
        self.setFixedSize(72, 72)
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
        self._refresh_text()

    # ------------------------------------------------------------------
    # Long-press override
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        self._long_press_active = False
        self._long_press_timer.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        self._long_press_timer.stop()
        if self._long_press_active:
            self._long_press_active = False
            self.setDown(False)
            self.update()
            return
        super().mouseReleaseEvent(event)

    def _on_long_press_fired(self) -> None:
        self._long_press_active = True
        self.long_pressed.emit(self.index)

    # ------------------------------------------------------------------
    # Drag-and-drop target
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: Any) -> None:
        if event.mimeData().hasFormat(_MIME_TYPE):
            event.acceptProposedAction()

    def dropEvent(self, event: Any) -> None:
        raw: bytes = bytes(event.mimeData().data(_MIME_TYPE))
        try:
            data: dict[str, Any] = json.loads(raw.decode())
        except (ValueError, UnicodeDecodeError):
            return
        self.action_dropped.emit(self.index, data)
        event.acceptProposedAction()

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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.addLayout(self._grid_layout)
        outer.addStretch()
        self._key_count = 0
        self._buttons: dict[int, KeyButtonWidget] = {}

    @property
    def key_count(self) -> int:
        """The number of keys currently rendered."""
        return self._key_count

    def set_key_count(self, key_count: int) -> None:
        """Rebuild the grid for a device with key_count keys."""
        self._key_count = key_count
        self._buttons.clear()
        while (item := self._grid_layout.takeAt(0)) is not None:
            if widget := item.widget():
                widget.deleteLater()

        _, cols = grid_dimensions_for_key_count(key_count)
        for index in range(key_count):
            row, col = divmod(index, cols) if cols else (0, 0)
            button = KeyButtonWidget(index)
            button.clicked.connect(lambda _checked=False, i=index: self.key_selected.emit(i))
            button.long_pressed.connect(self.key_long_pressed.emit)
            button.action_dropped.connect(self.action_dropped.emit)
            self._grid_layout.addWidget(button, row, col)
            self._buttons[index] = button

    def set_key_label(self, key_index: int, label: str) -> None:
        """Update the display label for a single key button."""
        if button := self._buttons.get(key_index):
            button.set_label(label)
