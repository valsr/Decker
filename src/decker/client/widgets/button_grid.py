"""Button grid matching the active device's key layout."""

import base64
import json
from pathlib import Path
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

from decker.client.action_icons import decode_icon
from decker.common.model import KeyInfo

_LONG_PRESS_MS = 500
_RUN_SIZE = 30  # px, the hover play button
_RUN_ICON_PX = 21  # px, the play-circle drawing inside its 30 px button
_PLAY_ICON = Path(__file__).resolve().parents[2] / "assets" / "play-circle.svg"
_RUN_MARGIN = 4  # px from the key's top-right corner
_MIME_TYPE = "application/x-decker-action"


def _play_icon(color: str) -> QIcon | None:
    """The shipped play-circle drawing filled with ``color`` (rendered at 2x for crisp edges), or None if unusable."""
    try:
        raw = _PLAY_ICON.read_bytes()
    except OSError:
        return None
    pixmap = decode_icon(base64.b64encode(raw).decode("ascii"), color)
    if pixmap is None:
        return None
    size = _RUN_ICON_PX * 2
    return QIcon(
        pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    )


class _RunButton(QToolButton):
    """The play button: a click runs the key, holding it for half a second is a long press (and no click)."""

    long_pressed = pyqtSignal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._held = False
        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.setInterval(_LONG_PRESS_MS)
        self._long_press_timer.timeout.connect(self._on_long_press_fired)

    def mousePressEvent(self, e: QMouseEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Start timing the hold."""
        self._held = False
        self._long_press_timer.start()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """A normal release clicks; the release after a long press does not."""
        self._long_press_timer.stop()
        if self._held:
            self._held = False
            self.setDown(False)
            self.update()
            return
        super().mouseReleaseEvent(e)

    def _on_long_press_fired(self) -> None:
        self._held = True
        self.long_pressed.emit()


class KeyButtonWidget(QPushButton):
    """Square button for one key: a click selects it, its play button runs it, and it accepts action drops."""

    action_dropped = pyqtSignal(int, object)
    long_pressed = pyqtSignal(int)
    edit_clicked = pyqtSignal(int)
    run_clicked = pyqtSignal(int)

    def __init__(self, index: int, key_info: KeyInfo) -> None:
        super().__init__()
        self._info = key_info
        self.setFixedSize(self._info.pixel_width, self._info.pixel_height)
        self.index = index
        self._label: str = ""
        self._refresh_text()
        self.setAcceptDrops(True)
        self.clicked.connect(lambda _checked=False: self.edit_clicked.emit(self.index))
        self._run_button = self._build_run_button()
        self.setProperty("selected", False)

    def set_selected(self, selected: bool) -> None:
        """Mark this key as the one being edited (outlined by the theme)."""
        self.setProperty("selected", selected)
        if (style := self.style()) is not None:
            style.unpolish(self)
            style.polish(self)

    def _build_run_button(self) -> _RunButton:
        button = _RunButton(self)
        button.setObjectName("keyRunButton")
        self._apply_play_icon(button)
        button.setToolTip("Run this key")
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setFixedSize(_RUN_SIZE, _RUN_SIZE)
        button.setAcceptDrops(False)  # a drop on the play button falls through to the key
        button.clicked.connect(lambda _checked=False: self.run_clicked.emit(self.index))
        button.long_pressed.connect(lambda: self.long_pressed.emit(self.index))
        button.hide()
        button.move(self._run_position())
        return button

    def _apply_play_icon(self, button: QToolButton) -> None:
        """Draw the play-circle from the shipped SVG in the palette's text colour; a "▶" glyph if it is unusable."""
        icon = _play_icon(self.palette().buttonText().color().name())
        if icon is None:
            button.setIcon(QIcon())
            button.setText("▶")
        else:
            button.setText("")
            button.setIcon(icon)
            button.setIconSize(QSize(_RUN_ICON_PX, _RUN_ICON_PX))

    def changeEvent(self, e: QEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Redraw the play icon when the theme's palette changes."""
        super().changeEvent(e)
        if e is not None and e.type() == QEvent.Type.PaletteChange and hasattr(self, "_run_button"):
            self._apply_play_icon(self._run_button)

    def _run_position(self) -> QPoint:
        return QPoint(self.width() - _RUN_SIZE - _RUN_MARGIN, _RUN_MARGIN)

    def resizeEvent(self, a0: QResizeEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Keep the play button in the top-right corner."""
        super().resizeEvent(a0)
        self._run_button.move(self._run_position())

    def enterEvent(self, event: QEnterEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Show the play button while the pointer is over the key."""
        super().enterEvent(event)
        self._run_button.show()
        self._run_button.raise_()

    def keyPressEvent(self, e: QKeyEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """F2 (or the Menu key) selects the key for editing, as clicking it does."""
        if e is not None and e.key() in (Qt.Key.Key_F2, Qt.Key.Key_Menu):
            self.edit_clicked.emit(self.index)
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e: QFocusEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Show the play button while the key has keyboard focus, so it is visible without a pointer."""
        super().focusInEvent(e)
        self._run_button.show()

    def focusOutEvent(self, e: QFocusEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Hide the play button again unless the pointer is still on the key."""
        super().focusOutEvent(e)
        if not self.underMouse():
            self._run_button.hide()

    def leaveEvent(self, a0: QEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Hide the play button once the pointer is outside the key and its button."""
        super().leaveEvent(a0)
        if not self.underMouse():
            self._run_button.hide()

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
        self._buttons: dict[int, KeyButtonWidget] = {}
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
        self._buttons = {}

        for index in range(self.key_count):
            key = self._key_info[index]
            row, col = key.row, key.col
            button = KeyButtonWidget(index, key)
            button.run_clicked.connect(self.key_pressed.emit)
            button.edit_clicked.connect(self.key_edit_requested.emit)
            button.long_pressed.connect(self.key_long_pressed.emit)
            button.action_dropped.connect(self.action_dropped.emit)
            self._grid_layout.addWidget(button, row, col)
            self._buttons[index] = button

    def set_selected(self, key_index: int | None) -> None:
        """Outline the key being edited; None (or an unknown index) outlines nothing."""
        for index, button in self._buttons.items():
            button.set_selected(index == key_index)

    def set_key_label(self, key_index: int, label: str) -> None:
        """Update the display label for a single key button."""
        if button := self._buttons.get(key_index):
            button.set_label(label)

    def set_key_image(self, key_index: int, image_b64: str | None) -> None:
        """Update the image for a single key button from a base64-encoded PNG."""
        if button := self._buttons.get(key_index):
            button.set_image(image_b64)
