"""Pixmaps for plugin actions: the icon the server sent, or a generated letter tile."""

import base64
import binascii
import zlib

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap

# Muted tile colours that keep white text readable (WCAG AA); chosen per action so tiles stay stable.
_PLACEHOLDER_COLORS = ("#3b6ea8", "#7a4fa0", "#2f7d68", "#a8532f", "#8a6d1f", "#4f5b70")


def action_pixmap(action: dict[str, str], size: int) -> QPixmap:
    """Return the action's icon scaled to size×size, or a letter tile if it has no usable icon."""
    pixmap = decode_icon(action.get("icon_b64", ""))
    if pixmap is None:
        return placeholder_pixmap(action.get("action_name", ""), size)
    return pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


def decode_icon(icon_b64: str) -> QPixmap | None:
    """Decode a base64 image (PNG, JPEG, SVG, …); None if it is empty or not a readable image."""
    if not icon_b64:
        return None
    try:
        data = base64.b64decode(icon_b64, validate=True)
    except (binascii.Error, ValueError):
        return None
    pixmap = QPixmap()
    if not pixmap.loadFromData(QByteArray(data)) or pixmap.isNull():
        return None
    return pixmap


def placeholder_pixmap(name: str, size: int) -> QPixmap:
    """A rounded tile showing the first letter of name, coloured consistently per name."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    color = QColor(_PLACEHOLDER_COLORS[zlib.crc32(name.encode()) % len(_PLACEHOLDER_COLORS)])
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    rect = QRectF(0, 0, size, size)
    painter.drawRoundedRect(rect, size * 0.18, size * 0.18)
    font = QFont()
    font.setBold(True)
    font.setPixelSize(max(1, int(size * 0.5)))
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, (name.strip()[:1] or "?").upper())
    painter.end()
    return pixmap
