"""Live preview of a key as it will be drawn, with an icon context menu."""

import base64
import binascii

from PyQt6.QtCore import QByteArray, Qt, pyqtSignal
from PyQt6.QtGui import QContextMenuEvent, QMouseEvent, QPixmap
from PyQt6.QtWidgets import QLabel, QMenu


class KeyPreview(QLabel):
    """A key-sized picture; right click offers Set / Clear icon, double click asks for the icon picker."""

    set_icon_requested = pyqtSignal()
    clear_icon_requested = pyqtSignal()

    def __init__(self, size: int = 72) -> None:
        super().__init__()
        self.setObjectName("keyPreview")
        self.setFixedSize(size, size)
        self.setScaledContents(True)
        self.setToolTip("Double-click to set an icon, right-click for more")
        self._has_icon = False

    def set_image(self, image_b64: str | None) -> None:
        """Show a base64 PNG; None or undecodable data clears the picture."""
        pixmap = QPixmap()
        if image_b64:
            try:
                raw = base64.b64decode(image_b64, validate=True)
            except (binascii.Error, ValueError):
                raw = b""
            pixmap.loadFromData(QByteArray(raw))
        if pixmap.isNull():
            self.clear()
        else:
            self.setPixmap(pixmap)

    def set_has_icon(self, has: bool) -> None:
        """Whether the key has an icon override (enables Clear icon)."""
        self._has_icon = has

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction("Set icon…").triggered.connect(self.set_icon_requested.emit)
        clear = menu.addAction("Clear icon")
        clear.setEnabled(self._has_icon)
        clear.triggered.connect(self.clear_icon_requested.emit)
        return menu

    def contextMenuEvent(self, ev: QContextMenuEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Show the icon menu."""
        if ev is not None:
            self._build_menu().exec(ev.globalPos())

    def mouseDoubleClickEvent(self, a0: QMouseEvent | None) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Open the icon picker."""
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self.set_icon_requested.emit()
