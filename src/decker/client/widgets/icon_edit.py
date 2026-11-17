"""Settings control for an icon: preview, name, Browse…, clear and a fill colour."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget

from decker.client.action_icons import decode_icon, placeholder_pixmap
from decker.client.context import AppContext
from decker.client.icon_picker import IconBrowserDialog, RpcCaller
from decker.client.widgets.color_button import ColorButton
from decker.common.icon_ref import make_icon_ref, normalize_icon_value, parse_icon_ref

_PREVIEW_SIZE = 24


def _app_rpc() -> RpcCaller | None:
    return AppContext.get().connection_manager


class IconEdit(QWidget):
    """One row: a 24 px preview, the icon's name, **Browse…**, a clear button and the fill colour swatch."""

    value_changed = pyqtSignal()

    def __init__(self, rpc: Callable[[], RpcCaller | None] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rpc = rpc or _app_rpc
        self._ref = ""
        self._color = "#ffffff"
        self._raw: dict[str, str] = {}
        self._preview = QLabel()
        self._preview.setFixedSize(_PREVIEW_SIZE, _PREVIEW_SIZE)
        self._name = QLabel()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        self._clear = QToolButton()
        self._clear.setText("✕")
        self._clear.setToolTip("Remove the icon")
        self._clear.clicked.connect(self._on_clear)
        self._colour = ColorButton(self._color, alpha=True)
        self._colour.set_show_name(False)
        self._colour.setToolTip("Icon fill colour")
        self._colour.color_changed.connect(self._on_colour_changed)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._preview)
        row.addWidget(self._name, 1)
        row.addWidget(browse)
        row.addWidget(self._clear)
        row.addWidget(self._colour)
        self._refresh()

    def value(self) -> dict[str, Any]:
        """The icon value: ``{"ref": "", or "pack:<pack id>/<path>", "color": "#rrggbb[aa]"}``."""
        return {"ref": self._ref, "color": self._color}

    def set_value(self, value: Any) -> None:
        """Show ``value`` (normalised) without emitting ``value_changed``."""
        normalized = normalize_icon_value(value)
        self._ref, self._color = normalized["ref"], normalized["color"]
        self._colour.set_color(self._color)
        self._refresh()

    def _browse(self) -> None:
        dialog = IconBrowserDialog(self, self._rpc(), tint=self._color)
        dialog.icon_chosen.connect(self._on_icon_chosen)
        dialog.exec()

    def _on_icon_chosen(self, pack_id: str, path: str) -> None:
        self._ref = make_icon_ref(pack_id, path)
        self._refresh()
        self.value_changed.emit()

    def _on_clear(self) -> None:
        self._ref = ""
        self._refresh()
        self.value_changed.emit()

    def _on_colour_changed(self, color: str) -> None:
        self._color = color
        self._refresh()
        self.value_changed.emit()

    def _refresh(self) -> None:
        parsed = parse_icon_ref(self._ref)
        self._name.setText(Path(parsed[1]).stem if parsed is not None else "No icon")
        self._clear.setEnabled(parsed is not None)
        self._preview.setPixmap(self._preview_pixmap(parsed))

    def _preview_pixmap(self, parsed: tuple[str, str] | None) -> QPixmap:
        if parsed is None:
            blank = QPixmap(_PREVIEW_SIZE, _PREVIEW_SIZE)
            blank.fill(Qt.GlobalColor.transparent)
            return blank
        raw = self._raw_icon(parsed)
        pixmap = decode_icon(raw, self._color) if raw else None
        if pixmap is None:
            return placeholder_pixmap(parsed[1], _PREVIEW_SIZE)
        return pixmap.scaled(
            _PREVIEW_SIZE,
            _PREVIEW_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _raw_icon(self, parsed: tuple[str, str]) -> str | None:
        ref = make_icon_ref(*parsed)
        if ref not in self._raw:
            rpc = self._rpc()
            raw = rpc.call("iconpack_icon", *parsed) if rpc is not None else None
            if not isinstance(raw, str) or not raw:
                return None  # not cached: retry once the server answers
            self._raw[ref] = raw
        return self._raw[ref]
