"""Reusable text field whose formatting toolbar appears below it while the field is being edited."""

from typing import Any

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

from decker.client.widgets.text_style_toolbar import TextStyleToolbar
from decker.common.text_style import normalize_text_style


class TextStyleEdit(QWidget):
    """A text input; entering it reveals the styling toolbar underneath, leaving both hides it again."""

    value_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._line = QLineEdit()
        self._toolbar = TextStyleToolbar(self)
        self._toolbar.hide()
        layout.addWidget(self._line)
        layout.addWidget(self._toolbar)
        self._picker_open = False
        self._toolbar.picker_opened.connect(lambda: self._set_picker_open(True))
        self._toolbar.picker_closed.connect(lambda: self._set_picker_open(False))
        self._line.textEdited.connect(lambda _text: self.value_changed.emit())
        self._toolbar.style_changed.connect(self.value_changed)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.focusChanged.connect(self._on_focus_changed)

    def value(self) -> dict[str, Any]:
        """The complete, normalised text style value including the text."""
        return normalize_text_style({**self._toolbar.style_value(), "text": self._line.text()})

    def set_value(self, value: Any) -> None:
        """Show ``value`` (normalised) without emitting ``value_changed``."""
        style = normalize_text_style(value)
        self._line.setText(style["text"])
        self._toolbar.set_style(style)

    def _inside(self, widget: QWidget | None) -> bool:
        return widget is not None and (widget is self._line or self.isAncestorOf(widget))

    def _set_picker_open(self, opened: bool) -> None:
        self._picker_open = opened
        if not opened and not self._inside(QApplication.focusWidget()):
            self._toolbar.setVisible(False)

    def _on_focus_changed(self, _old: QWidget | None, new: QWidget | None) -> None:
        if self._inside(new):
            self._toolbar.setVisible(True)
        elif not self._picker_open:
            self._toolbar.setVisible(False)
