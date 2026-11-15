"""Push button that shows a colour swatch and opens a colour picker when clicked."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import QColorDialog, QPushButton, QWidget

_SWATCH_SIZE = 14


class ColorButton(QPushButton):
    """Shows the current colour as a swatch plus its #rrggbb name; clicking picks a new one."""

    color_changed = pyqtSignal(str)

    def __init__(self, color: str = "#000000", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self.clicked.connect(self._pick)
        self._refresh()

    @property
    def color(self) -> str:
        """The current colour as #rrggbb."""
        return self._color.name()

    def set_color(self, color: str) -> None:
        """Set the colour; invalid names are ignored."""
        candidate = QColor(color)
        if candidate.isValid():
            self._color = candidate
            self._refresh()

    def _pick(self) -> None:
        chosen = QColorDialog.getColor(self._color, self, "Choose colour")
        if chosen.isValid() and chosen != self._color:
            self._color = chosen
            self._refresh()
            self.color_changed.emit(self.color)

    def _refresh(self) -> None:
        swatch = QPixmap(_SWATCH_SIZE, _SWATCH_SIZE)
        swatch.fill(self._color)
        self.setIcon(QIcon(swatch))
        self.setText(self._color.name())
