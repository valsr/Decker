"""Reusable text field with an inset cog that opens a floating formatting toolbar."""

from typing import Any

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QGuiApplication, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QWidget

from decker.client.widgets.text_style_toolbar import TextStyleToolbar
from decker.common.text_style import normalize_text_style

_COG_SIZE = 16


def _cog_icon() -> QIcon:
    theme = QIcon.fromTheme("configure")
    if not theme.isNull():
        return theme
    pixmap = QPixmap(_COG_SIZE, _COG_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setPen(Qt.GlobalColor.gray)
    painter.drawText(QRect(0, 0, _COG_SIZE, _COG_SIZE), Qt.AlignmentFlag.AlignCenter, "⚙")
    painter.end()
    return QIcon(pixmap)


class TextStyleEdit(QWidget):
    """A single text input with a cog at its end; the cog toggles the styling popup."""

    value_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._line = QLineEdit()
        layout.addWidget(self._line)
        self._cog = QAction(_cog_icon(), "Text style", self._line)
        self._cog.setCheckable(True)
        self._line.addAction(self._cog, QLineEdit.ActionPosition.TrailingPosition)
        self._toolbar = TextStyleToolbar(self)
        self._cog.triggered.connect(self._toggle_popup)
        self._toolbar.closed.connect(lambda: self._cog.setChecked(False))
        self._line.textEdited.connect(lambda _text: self.value_changed.emit())
        self._toolbar.style_changed.connect(self.value_changed)

    def value(self) -> dict[str, Any]:
        """The complete, normalised text style value including the text."""
        return normalize_text_style({**self._toolbar.style_value(), "text": self._line.text()})

    def set_value(self, value: Any) -> None:
        """Show ``value`` (normalised) without emitting ``value_changed``."""
        style = normalize_text_style(value)
        self._line.setText(style["text"])
        self._toolbar.set_style(style)

    def _toggle_popup(self, checked: bool) -> None:
        if checked:
            self._open_popup()
        else:
            self._toolbar.close()

    def _open_popup(self) -> None:
        self._toolbar.adjustSize()
        self._toolbar.move(self._popup_position())
        self._toolbar.show()

    def _available_geometry(self) -> QRect:
        screen = self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 800)

    def _popup_position(self) -> QPoint:
        size = self._toolbar.sizeHint()
        screen = self._available_geometry()
        left = self.mapToGlobal(self.rect().bottomLeft())
        right_edge = self.mapToGlobal(self.rect().bottomRight()).x()
        x = max(screen.left(), min(right_edge - size.width() + 1, screen.right() - size.width() + 1))
        y = left.y()
        if y + size.height() > screen.bottom() + 1:
            y = self.mapToGlobal(self.rect().topLeft()).y() - size.height()
        return QPoint(x, max(screen.top(), y))
