"""Connecting overlay — frosted-glass panel shown while disconnected from the server."""

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPaintEvent, QPixmap
from PyQt6.QtWidgets import (
    QGraphicsBlurEffect,
    QGraphicsScene,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from decker.client.views.base import BaseView

_BLUR_RADIUS = 18.0


def _grab_blurred(widget: QWidget, radius: float = _BLUR_RADIUS) -> QPixmap:
    source = widget.grab()
    scene = QGraphicsScene()
    item = scene.addPixmap(source)
    if item is not None:
        effect = QGraphicsBlurEffect()
        effect.setBlurRadius(radius)
        item.setGraphicsEffect(effect)
    scene.setSceneRect(0, 0, source.width(), source.height())
    result = QPixmap(source.size())
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    scene.render(painter)
    painter.end()
    return result


class ConnectingOverlay(BaseView):
    """Frosted-glass overlay that sits on top of the main view stack while reconnecting.

    Not added to the QStackedWidget — shown as a floating child of the stack widget.
    The underlying view (dashboard) remains rendered and is captured/blurred as the backdrop.
    """

    def __init__(self, host: str, port: int, on_settings: Callable[[], None]) -> None:
        super().__init__()
        self._blurred_bg: QPixmap | None = None
        self.setAutoFillBackground(False)
        self.hide()

        self._label = QLabel(f"Connecting to server ({host}:{port})")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setObjectName("connecting-label")

        self._settings_btn = QPushButton("Settings")
        self._settings_btn.clicked.connect(on_settings)
        self._settings_btn.setObjectName("connecting-settings-btn")
        self._settings_btn.setFixedWidth(120)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        layout.addWidget(self._label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(16)
        layout.addWidget(self._settings_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()

    def on_activate(self) -> None:
        """Capture and blur the background, then display the overlay."""
        parent = self.parentWidget()
        if parent is not None:
            self._blurred_bg = _grab_blurred(parent)
            self.resize(parent.size())
            self.move(0, 0)
        self.raise_()
        self.show()
        self.update()

    def on_deactivate(self) -> None:
        """Hide the overlay and discard the cached background."""
        self.hide()
        self._blurred_bg = None

    def paintEvent(self, event: QPaintEvent | None) -> None:
        painter = QPainter(self)
        if self._blurred_bg is not None:
            painter.drawPixmap(0, 0, self._blurred_bg)
        painter.fillRect(self.rect(), QColor(20, 20, 30, 160))
        painter.end()


# Alias kept so that any test or import still referring to ConnectingView doesn't break.
ConnectingView = ConnectingOverlay
