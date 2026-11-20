"""Settings control for a key background: none, a solid colour or an image from the image library."""

from typing import Any

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QWidget

from decker.client.widgets.color_button import ColorButton
from decker.client.widgets.icon_edit import IconEdit
from decker.common.background import normalize_background

_MODES: tuple[tuple[str, str], ...] = (("none", "None"), ("color", "Solid colour"), ("image", "Image"))


class BackgroundEdit(QWidget):
    """A mode combo plus the control for the chosen mode; the other mode's colour or image is kept."""

    value_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mode = QComboBox()
        for data, label in _MODES:
            self._mode.addItem(label, data)
        self._colour = ColorButton("#000000", alpha=True)
        self._colour.set_show_name(False)
        self._colour.setToolTip("Background colour")
        self._image = IconEdit()
        self._image.set_show_colour(False)
        self._image.set_tint_thumbnail(False)  # the server draws backgrounds untinted
        self._image.set_texts("No image (shows black)", "Remove the background image")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._mode)
        row.addWidget(self._colour)
        row.addWidget(self._image)
        self._apply_mode()
        self._mode.currentIndexChanged.connect(self._on_mode_changed)
        self._colour.color_changed.connect(lambda _color: self.value_changed.emit())
        self._image.value_changed.connect(self.value_changed.emit)

    def value(self) -> dict[str, Any]:
        """The background: ``{"type": "none"|"color"|"image", "color": "#rrggbb[aa]", "image": {"ref": ...}}``."""
        return {
            "type": str(self._mode.currentData()),
            "color": self._colour.color,
            "image": {"ref": self._image.value()["ref"]},
        }

    def set_value(self, value: Any) -> None:
        """Show ``value`` (normalised; a bare colour string is the legacy form) without emitting ``value_changed``."""
        normalized = normalize_background(value)
        self._mode.blockSignals(True)
        self._mode.setCurrentIndex(max(self._mode.findData(normalized["type"]), 0))
        self._mode.blockSignals(False)
        self._colour.set_color(normalized["color"])
        self._image.set_value(normalized["image"])
        self._apply_mode()

    def _on_mode_changed(self, _index: int) -> None:
        self._apply_mode()
        self.value_changed.emit()

    def _apply_mode(self) -> None:
        mode = self._mode.currentData()
        self._colour.setVisible(mode == "color")
        self._image.setVisible(mode == "image")
