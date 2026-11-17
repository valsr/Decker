"""Push button that shows a colour swatch and opens a colour picker (optionally with an alpha channel) when clicked."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QColorDialog, QPushButton, QWidget

from decker.client.widgets.color_tool_button import hex_to_qcolor, qcolor_to_hex

_SWATCH_SIZE = 14


class ColorButton(QPushButton):
    """Shows the current colour as a swatch plus its name; clicking picks a new one (RGBA when ``alpha``)."""

    color_changed = pyqtSignal(str)

    def __init__(self, color: str = "#000000", parent: QWidget | None = None, alpha: bool = False) -> None:
        super().__init__(parent)
        self._alpha = alpha
        self._show_name = True
        self._color = self._parse(color) or QColor("#000000")
        self.clicked.connect(self._pick)
        self._refresh()

    @property
    def color(self) -> str:
        """The current colour: ``#rrggbb``, or ``#rrggbbaa`` when alpha is enabled and the colour is translucent."""
        return qcolor_to_hex(self._color) if self._alpha else self._color.name()

    def set_color(self, color: str) -> None:
        """Set the colour; invalid names (and translucent ones without alpha) are ignored."""
        candidate = self._parse(color)
        if candidate is not None:
            self._color = candidate
            self._refresh()

    def set_show_name(self, show: bool) -> None:
        """Show the colour name next to the swatch, or just the swatch (the name stays in the tooltip)."""
        self._show_name = show
        self._refresh()

    def _parse(self, color: str) -> QColor | None:
        candidate = hex_to_qcolor(color) or QColor(color)
        if not candidate.isValid() or (not self._alpha and candidate.alpha() != 255):
            return None
        return candidate

    def _pick(self) -> None:
        if self._alpha:
            chosen = QColorDialog.getColor(
                self._color, self, "Choose colour", QColorDialog.ColorDialogOption.ShowAlphaChannel
            )
        else:
            chosen = QColorDialog.getColor(self._color, self, "Choose colour")
        if chosen.isValid() and chosen != self._color:
            self._color = chosen
            self._refresh()
            self.color_changed.emit(self.color)

    def _refresh(self) -> None:
        swatch = QPixmap(_SWATCH_SIZE, _SWATCH_SIZE)
        swatch.fill(Qt.GlobalColor.white)
        painter = QPainter(swatch)
        half = _SWATCH_SIZE // 2
        painter.fillRect(0, 0, half, half, Qt.GlobalColor.lightGray)  # checker so translucent colours read as such
        painter.fillRect(half, half, half, half, Qt.GlobalColor.lightGray)
        painter.fillRect(0, 0, _SWATCH_SIZE, _SWATCH_SIZE, self._color)
        painter.end()
        self.setIcon(QIcon(swatch))
        self.setText(self.color if self._show_name else "")
        self.setToolTip(self.color)
