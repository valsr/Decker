"""Button grid matching the active device's key layout."""

import base64
import json
from typing import Any

from PyQt6.QtCore import QByteArray, QEvent, QPoint, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QEnterEvent,
    QFocusEvent,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPixmap,
    QResizeEvent,
)
from PyQt6.QtWidgets import QGridLayout, QPushButton, QToolButton, QVBoxLayout, QWidget

from decker.common.model import KeyInfo

_LONG_PRESS_MS = 500
_EDIT_SIZE = 20  # px, the hover pencil
_EDIT_MARGIN = 4  # px from the key's top-right corner
_MIME_TYPE = "application/x-decker-action"


class KeyButtonWidget(QPushButton):
    """Square button for one key: supports drag-and-drop assignment and long-press detection."""

    action_dropped = pyqtSignal(int, object)
    long_pressed = pyqtSignal(int)
    edit_clicked = pyqtSignal(int)

    def __init__(self, index: int, key_info: KeyInfo) -> None:
        super().__init__()
        self._info = key_info
        self.setFixedSize(self._info.pixel_width, self._info.pixel_height)
        self.index = index
        self._label: str = ""
        self._refresh_text()
        self.setAcceptDrops(True)
        self._long_press_active = False
        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.setInterval(_LONG_PRESS_MS)
        self._long_press_timer.timeout.connect(self._on_long_press_fired)
        self._edit_button = self._build_edit_button()

    def _build_edit_button(self) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("keyEditButton")
        icon = QIcon.fromTheme("document-edit")
        if icon.isNull():
            button.setText("✎")
        else:
            button.setIcon(icon)
        button.setToolTip("Edit this key")
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setFixedSize(_EDIT_SIZE, _EDIT_SIZE)
        button.setAcceptDrops(False)  # a drop on the pencil falls through to the key
        button.clicked.connect(lambda _checked=False: self.edit_clicked.emit(self.index))
        button.hide()
        button.move(self._edit_position())
        return button

    def _edit_position(self) -> QPoint:
        return QPoint(self.width() - _EDIT_SIZE - _EDIT_MARGIN, _EDIT_MARGIN)

    def resizeEvent(self, a0: QResizeEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Keep the pencil in the top-right corner."""
        super().resizeEvent(a0)
        self._edit_button.move(self._edit_position())

    def enterEvent(self, event: QEnterEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Show the edit pencil while the pointer is over the key."""
        super().enterEvent(event)
        self._edit_button.show()
        self._edit_button.raise_()

    def keyPressEvent(self, e: QKeyEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """F2 (or the Menu key) edits the key, so keyboard users can reach what the pencil does for the mouse."""
        if e is not None and e.key() in (Qt.Key.Key_F2, Qt.Key.Key_Menu):
            self.edit_clicked.emit(self.index)
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e: QFocusEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Show the pencil while the key has keyboard focus, so the edit affordance is visible without a pointer."""
        super().focusInEvent(e)
        self._edit_button.show()

    def focusOutEvent(self, e: QFocusEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Hide the pencil again unless the pointer is still on the key."""
        super().focusOutEvent(e)
        if not self.underMouse():
            self._edit_button.hide()

    def leaveEvent(self, a0: QEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Hide the pencil once the pointer is outside the key and its pencil."""
        super().leaveEvent(a0)
        if not self.underMouse():
            self._edit_button.hide()

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

    key_pressed = pyqtSignal(int)
    key_edit_requested = pyqtSignal(int)
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
            button = KeyButtonWidget(index, key)
            button.clicked.connect(lambda _checked=False, i=index: self.key_pressed.emit(i))
            button.edit_clicked.connect(self.key_edit_requested.emit)
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
