"""Toolbar-style colour button: a glyph with a colour bar, an RGBA picker and an optional "None" entry."""

import re

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QColorDialog, QMenu, QToolButton, QWidget

_HEX_PATTERN = re.compile(r"^#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})?$")
_ICON_SIZE = 22
_BAR_HEIGHT = 4


def hex_to_qcolor(value: str) -> QColor | None:
    """Parse ``#rrggbb`` or ``#rrggbbaa`` (alpha last, unlike Qt's own ``#aarrggbb``); None if malformed."""
    match = _HEX_PATTERN.match(value)
    if match is None:
        return None
    red, green, blue, alpha = match.groups()
    return QColor(int(red, 16), int(green, 16), int(blue, 16), int(alpha, 16) if alpha else 255)


def qcolor_to_hex(color: QColor) -> str:
    """``#rrggbb`` when opaque, otherwise ``#rrggbbaa``."""
    base = f"#{color.red():02x}{color.green():02x}{color.blue():02x}"
    return base if color.alpha() == 255 else f"{base}{color.alpha():02x}"


class ColorToolButton(QToolButton):
    """A glyph over a colour bar; the main part opens an RGBA picker and the arrow menu offers "None"."""

    color_changed = pyqtSignal(object)
    picker_opened = pyqtSignal()
    picker_closed = pyqtSignal()

    def __init__(self, icon_text: str, allow_none: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon_text = icon_text
        self._allow_none = allow_none
        self._color: QColor | None = None if allow_none else QColor("#000000")
        self.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        menu = QMenu(self)
        menu.addAction("Pick colour…", self._pick)
        if allow_none:
            menu.addAction("None", self._clear)
        self.setMenu(menu)
        self.clicked.connect(self._pick)
        self._refresh()

    @property
    def color(self) -> str | None:
        """The current colour as ``#rrggbb``/``#rrggbbaa``, or None."""
        return None if self._color is None else qcolor_to_hex(self._color)

    def set_color(self, color: str | None) -> None:
        """Set the colour without emitting; invalid values are ignored and None only applies when allowed."""
        if color is None:
            if not self._allow_none:
                return
            self._color = None
        else:
            parsed = hex_to_qcolor(color)
            if parsed is None:
                return
            self._color = parsed
        self._refresh()

    def _pick(self) -> None:
        initial = self._color if self._color is not None else QColor("#ffffff")
        self.picker_opened.emit()
        try:
            chosen = QColorDialog.getColor(
                initial, self, "Choose colour", QColorDialog.ColorDialogOption.ShowAlphaChannel
            )
            if chosen.isValid() and chosen != self._color:
                self._color = chosen
                self._refresh()
                self.color_changed.emit(self.color)
        finally:
            self.picker_closed.emit()

    def _clear(self) -> None:
        if self._color is not None:
            self._color = None
            self._refresh()
            self.color_changed.emit(None)

    def _refresh(self) -> None:
        pixmap = QPixmap(_ICON_SIZE, _ICON_SIZE)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        font = QFont(self.font())
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self.palette().buttonText().color())
        painter.drawText(
            QRect(0, 0, _ICON_SIZE, _ICON_SIZE - _BAR_HEIGHT), Qt.AlignmentFlag.AlignCenter, self._icon_text
        )
        if self._color is not None:
            painter.fillRect(0, _ICON_SIZE - _BAR_HEIGHT, _ICON_SIZE, _BAR_HEIGHT, self._color)
        painter.end()
        self.setIcon(QIcon(pixmap))
        self.setToolTip(self.color or "None")
