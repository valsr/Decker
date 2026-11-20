"""Reusable text field with an inset cog that opens a floating formatting toolbar."""

from typing import Any

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, Qt, pyqtSignal
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
        self._reopen_after_picker = False
        self._toolbar.picker_opened.connect(self._on_picker_opened)
        self._toolbar.picker_closed.connect(self._on_picker_closed)
        self._cog.triggered.connect(self._toggle_popup)
        self._toolbar.closed.connect(lambda: self._cog.setChecked(False))
        self._line.textEdited.connect(lambda _text: self.value_changed.emit())
        self._line.installEventFilter(self)
        self._toolbar.style_changed.connect(self.value_changed)

    def value(self) -> dict[str, Any]:
        """The complete, normalised text style value including the text."""
        return normalize_text_style({**self._toolbar.style_value(), "text": self._line.text()})

    def set_value(self, value: Any) -> None:
        """Show ``value`` (normalised) without emitting ``value_changed``."""
        style = normalize_text_style(value)
        self._line.setText(style["text"])
        self._toolbar.set_style(style)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:  # noqa: N802  # pylint: disable=invalid-name
        """Entering the field (click or Tab) opens the styling popup; focus coming back from it does not."""
        if a0 is self._line and a1 is not None and a1.type() == QEvent.Type.FocusIn:
            reason = a1.reason()  # type: ignore[attr-defined]
            if reason in (
                Qt.FocusReason.MouseFocusReason,
                Qt.FocusReason.TabFocusReason,
                Qt.FocusReason.BacktabFocusReason,
            ):
                self._cog.setChecked(True)
                self._open_popup()
        return super().eventFilter(a0, a1)

    def _on_picker_opened(self) -> None:
        self._reopen_after_picker = self._toolbar.isVisible()
        self._toolbar.hide()  # a popup holds the mouse grab and would swallow the dialog's clicks

    def _on_picker_closed(self) -> None:
        # A Popup window closes when the modal colour dialog takes focus; bring it back so editing can continue.
        if self._reopen_after_picker:
            self._reopen_after_picker = False
            self._cog.setChecked(True)
            self._open_popup()

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
