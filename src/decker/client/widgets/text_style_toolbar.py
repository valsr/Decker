"""Single-row formatting toolbar for the text style control."""

from collections.abc import Mapping
from typing import Any

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import (
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFontComboBox,
    QFrame,
    QHBoxLayout,
    QSpinBox,
    QToolButton,
    QWidget,
)

from decker.client.widgets.color_tool_button import ColorToolButton
from decker.common.text_style import (
    OUTLINE_WIDTH_RANGE,
    POSITIONS,
    SIZE_RANGE,
    normalize_text_style,
)

_ICON = 18
_POSITION_NAMES = {"top": "Top", "middle": "Middle", "bottom": "Bottom"}


def _glyph_icon(glyph: str) -> QIcon:
    pixmap = QPixmap(_ICON, _ICON)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setPen(Qt.GlobalColor.gray)
    painter.drawText(QRect(0, 0, _ICON, _ICON), Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()
    return QIcon(pixmap)


def _position_icon(position: str) -> QIcon:
    pixmap = QPixmap(_ICON, _ICON)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setPen(Qt.GlobalColor.gray)
    painter.drawRect(1, 1, _ICON - 3, _ICON - 3)
    band = {"top": 3, "middle": 7, "bottom": 11}[position]
    painter.fillRect(4, band, _ICON - 8, 3, Qt.GlobalColor.gray)
    painter.end()
    return QIcon(pixmap)


def _toggle(text: str, tooltip: str, font: QFont | None = None) -> QToolButton:
    button = QToolButton()
    button.setText(text)
    button.setToolTip(tooltip)
    button.setCheckable(True)
    if font is not None:
        button.setFont(font)
    return button


def _step_button(text: str, spin: QSpinBox) -> QToolButton:
    button = QToolButton()
    button.setText(text)
    button.setAutoRepeat(True)
    button.clicked.connect(spin.stepDown if text == "–" else spin.stepUp)
    return button


def _separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line


def _spin(bounds: tuple[int, int], suffix: str) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(*bounds)
    spin.setSuffix(suffix)
    spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return spin


class TextStyleToolbar(QFrame):  # pylint: disable=too-many-instance-attributes
    """Row: font, size, B/I/U/S, position, colour, outline, outline width, visible."""

    style_changed = pyqtSignal()
    picker_opened = pyqtSignal()
    picker_closed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._loading = False
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(6, 4, 6, 4)
        self._build_font_group()
        self._build_style_group()
        self._build_position_group()
        self._build_color_group()
        self._visible = _toggle("", "Show text")
        self._visible.setIcon(QIcon.fromTheme("view-visible", _glyph_icon("◉")))
        self._visible.setChecked(True)
        self._visible.toggled.connect(self._changed)
        self._row.addWidget(self._visible)
        self._add_shortcuts()
        self.set_style({})

    def style_value(self) -> dict[str, Any]:
        """The current style (every field of the text style value except ``text``)."""
        outline = self._outline.color
        value = {
            "font": self._font.currentFont().family(),
            "size": self._size.value(),
            "bold": self._bold.isChecked(),
            "italic": self._italic.isChecked(),
            "underline": self._underline.isChecked(),
            "strike": self._strike.isChecked(),
            "position": next((p for p, b in self._positions.items() if b.isChecked()), "bottom"),
            "color": self._color.color,
            "outline": outline,
            "outline_width": self._width.value(),
            "visible": self._visible.isChecked(),
        }
        return value

    def set_style(self, value: Mapping[str, Any]) -> None:
        """Show ``value`` without emitting ``style_changed``; invalid fields fall back to the defaults."""
        style = normalize_text_style(value)
        self._loading = True
        try:
            self._font.setCurrentFont(QFont(style["font"]))
            self._size.setValue(style["size"])
            self._bold.setChecked(style["bold"])
            self._italic.setChecked(style["italic"])
            self._underline.setChecked(style["underline"])
            self._strike.setChecked(style["strike"])
            self._positions[style["position"]].setChecked(True)
            self._color.set_color(style["color"])
            self._outline.set_color(style["outline"])
            self._width.setValue(style["outline_width"])
            self._visible.setChecked(style["visible"])
            self._sync_outline_enabled(style["outline"] is not None)
        finally:
            self._loading = False

    def _changed(self, *_args: Any) -> None:
        if not self._loading:
            self.style_changed.emit()

    def _build_font_group(self) -> None:
        self._font = QFontComboBox()
        self._font.setMinimumWidth(130)
        self._font.currentFontChanged.connect(self._changed)
        self._size = _spin(SIZE_RANGE, " pt")
        self._size.valueChanged.connect(self._changed)
        self._size_minus = _step_button("–", self._size)
        self._size_plus = _step_button("+", self._size)
        for widget in (self._font, self._size_minus, self._size, self._size_plus):
            self._row.addWidget(widget)
        self._row.addWidget(_separator())

    def _build_style_group(self) -> None:
        bold, italic, under, strike = QFont(), QFont(), QFont(), QFont()
        bold.setBold(True)
        italic.setItalic(True)
        under.setUnderline(True)
        strike.setStrikeOut(True)
        self._bold = _toggle("B", "Bold (Ctrl+B)", bold)
        self._italic = _toggle("I", "Italic (Ctrl+I)", italic)
        self._underline = _toggle("U", "Underline (Ctrl+U)", under)
        self._strike = _toggle("S", "Strikethrough", strike)
        for button in (self._bold, self._italic, self._underline, self._strike):
            button.toggled.connect(self._changed)
            self._row.addWidget(button)
        self._row.addWidget(_separator())

    def _build_position_group(self) -> None:
        self._positions: dict[str, QToolButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for position in POSITIONS:
            button = _toggle("", _POSITION_NAMES[position])
            button.setIcon(_position_icon(position))
            button.clicked.connect(self._changed)
            group.addButton(button)
            self._positions[position] = button
            self._row.addWidget(button)
        self._positions["bottom"].setChecked(True)
        self._row.addWidget(_separator())

    def _build_color_group(self) -> None:
        self._color = ColorToolButton("T")
        self._color.setToolTip("Text colour")
        self._outline = ColorToolButton("A", allow_none=True)
        self._width = _spin(OUTLINE_WIDTH_RANGE, " px")
        self._width_minus = _step_button("–", self._width)
        self._width_plus = _step_button("+", self._width)
        self._color.color_changed.connect(self._changed)
        self._outline.color_changed.connect(self._on_outline_changed)
        self._width.valueChanged.connect(self._changed)
        for button in (self._color, self._outline):
            button.picker_opened.connect(self.picker_opened)
            button.picker_closed.connect(self.picker_closed)
        for widget in (self._color, self._outline, self._width_minus, self._width, self._width_plus):
            self._row.addWidget(widget)
        self._row.addWidget(_separator())

    def _on_outline_changed(self, color: Any) -> None:
        self._sync_outline_enabled(color is not None)
        self._changed()

    def _sync_outline_enabled(self, enabled: bool) -> None:
        for widget in (self._width, self._width_minus, self._width_plus):
            widget.setEnabled(enabled)

    def _add_shortcuts(self) -> None:
        buttons: dict[str, QToolButton] = {"Ctrl+B": self._bold, "Ctrl+I": self._italic, "Ctrl+U": self._underline}
        for key, button in buttons.items():
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(button.toggle)
