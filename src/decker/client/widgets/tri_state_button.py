"""A segmented control of mutually exclusive icon buttons (none | colour | image), combo-box shaped for callers."""

from typing import Any

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QConicalGradient, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QButtonGroup, QHBoxLayout, QToolButton, QWidget

_ICON = 18


def _canvas() -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(_ICON, _ICON)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pixmap, painter


def cross_icon() -> QIcon:
    """A cross: nothing."""
    pixmap, painter = _canvas()
    painter.setPen(QPen(QColor(150, 150, 150), 2))
    painter.drawLine(QPointF(4, 4), QPointF(_ICON - 4, _ICON - 4))
    painter.drawLine(QPointF(_ICON - 4, 4), QPointF(4, _ICON - 4))
    painter.end()
    return QIcon(pixmap)


def colour_wheel_icon() -> QIcon:
    """A colour wheel: a solid colour."""
    pixmap, painter = _canvas()
    wheel = QConicalGradient(_ICON / 2, _ICON / 2, 90)
    for stop in range(7):
        wheel.setColorAt(stop / 6, QColor.fromHsvF((1 - stop / 6) % 1.0 if stop < 6 else 0.0, 0.9, 1.0))
    painter.setBrush(QBrush(wheel))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QRectF(2, 2, _ICON - 4, _ICON - 4))
    painter.end()
    return QIcon(pixmap)


def image_icon() -> QIcon:
    """A framed landscape: an image."""
    pixmap, painter = _canvas()
    painter.setPen(QPen(QColor(150, 150, 150), 1.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(QRectF(2, 3, _ICON - 4, _ICON - 6))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor(150, 150, 150)))
    painter.drawPolygon(QPolygonF([QPointF(4, _ICON - 5), QPointF(8, 8), QPointF(11, 12), QPointF(13, 10), QPointF(15, _ICON - 5)]))
    painter.end()
    return QIcon(pixmap)


class TriStateButton(QWidget):
    """Icon buttons side by side, exactly one pressed; ``currentData`` is the pressed one's value."""

    currentIndexChanged = pyqtSignal(int)  # noqa: N815  # pylint: disable=invalid-name

    def __init__(self, entries: list[tuple[str, str, QIcon]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: list[str] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        for index, (data, tooltip, icon) in enumerate(entries):
            button = QToolButton()
            button.setIcon(icon)
            button.setToolTip(tooltip)
            button.setCheckable(True)
            button.setAutoRaise(False)
            self._group.addButton(button, index)
            row.addWidget(button)
            self._data.append(data)
        self._index = 0
        self._group.button(0).setChecked(True)  # type: ignore[union-attr]
        self._group.idClicked.connect(self.setCurrentIndex)

    def findData(self, data: Any) -> int:  # noqa: N802  # pylint: disable=invalid-name
        """The position of ``data``, or -1."""
        return self._data.index(data) if data in self._data else -1

    def currentData(self) -> str:  # noqa: N802  # pylint: disable=invalid-name
        """The value of the pressed button."""
        return self._data[self._index]

    def currentIndex(self) -> int:  # noqa: N802  # pylint: disable=invalid-name
        """The position of the pressed button."""
        return self._index

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Press the button at ``index``; emits ``currentIndexChanged`` when that changes it."""
        if not 0 <= index < len(self._data):
            return
        button = self._group.button(index)
        if button is not None:
            button.setChecked(True)
        if index != self._index:
            self._index = index
            self.currentIndexChanged.emit(index)
