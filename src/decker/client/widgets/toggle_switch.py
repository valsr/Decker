"""A pill-shaped on/off switch."""

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPaintEvent
from PyQt6.QtWidgets import QAbstractButton, QWidget

_WIDTH = 38
_HEIGHT = 20


class ToggleSwitch(QAbstractButton):
    """A checkable switch: knob left when off, right when on."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def sizeHint(self) -> QSize:  # noqa: N802  # pylint: disable=invalid-name
        """The fixed pill size."""
        return QSize(_WIDTH, _HEIGHT)

    def paintEvent(self, e: QPaintEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name,unused-argument
        """Draw the track (accent when on) and the knob."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        on = self.isChecked()
        track = palette.highlight().color() if on else palette.mid().color()
        if not self.isEnabled():
            track.setAlpha(110)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(track))
        painter.drawRoundedRect(QRectF(0, 0, _WIDTH, _HEIGHT), _HEIGHT / 2, _HEIGHT / 2)
        knob = _HEIGHT - 6
        x = _WIDTH - knob - 3 if on else 3
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawEllipse(QRectF(x, 3, knob, knob))
        painter.end()
