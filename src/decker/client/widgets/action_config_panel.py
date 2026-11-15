"""Bottom panel for configuring the selected key's action."""

from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIntValidator
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from decker.client.widgets.color_button import ColorButton

_PAGE_PLACEHOLDER = 0
_PAGE_COUNTER = 1

# Mirrors the counter plugin's defaults (the client does not import plugin code).
COUNTER_DEFAULTS: dict[str, Any] = {
    "step": 1,
    "double_step": None,
    "max": 0,
    "background": "#1f618d",
    "title": "",
    "title_position": "bottom",
    "title_font": "DejaVu Sans",
    "title_size": 12,
    "title_color": "#ffffff",
    "title_outline": "",
    "title_outline_width": 1,
}
_POSITIONS = (("Top", "top"), ("Middle", "middle"), ("Bottom", "bottom"))
_STEP_LIMIT = 9999


class ActionConfigPanel(QStackedWidget):  # pylint: disable=too-many-instance-attributes
    """Stacked config panel: page 0 = placeholder, page 1 = counter action form."""

    def __init__(self) -> None:
        super().__init__()
        self._save_cb: Callable[[dict[str, Any]], None] | None = None
        self._loaded_settings: dict[str, Any] | None = None

        placeholder = QLabel("Select a key to configure")
        placeholder.setProperty("role", "muted")
        self.addWidget(placeholder)  # page 0

        # Counter form widgets (laid out by _build_counter_page)
        self._step_spin = _spin(1, _STEP_LIMIT, 1)
        self._double_step_edit = QLineEdit()
        self._double_step_edit.setValidator(QIntValidator(-_STEP_LIMIT, _STEP_LIMIT))
        self._double_step_edit.setPlaceholderText("None (presses register immediately)")
        self._max_spin = _spin(0, 99999, 0)
        self._max_spin.setSpecialValueText("∞ (no limit)")

        self._background_btn = ColorButton(COUNTER_DEFAULTS["background"])
        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("No title")
        self._position_combo = QComboBox()
        for label, value in _POSITIONS:
            self._position_combo.addItem(label, value)
        self._font_combo = QFontComboBox()
        self._title_size_spin = _spin(4, 48, COUNTER_DEFAULTS["title_size"])
        self._title_size_spin.setSuffix(" px")
        self._title_color_btn = ColorButton(COUNTER_DEFAULTS["title_color"])
        self._outline_check = QCheckBox("Outline")
        self._outline_color_btn = ColorButton("#000000")
        self._outline_width_spin = _spin(1, 6, COUNTER_DEFAULTS["title_outline_width"])
        self._outline_width_spin.setSuffix(" px")
        self._outline_check.toggled.connect(self._outline_color_btn.setEnabled)
        self._outline_check.toggled.connect(self._outline_width_spin.setEnabled)
        self._outline_check.setChecked(False)
        self._outline_color_btn.setEnabled(False)
        self._outline_width_spin.setEnabled(False)

        self.addWidget(self._build_counter_page())  # page 1

    def show_placeholder(self) -> None:
        """Switch to the placeholder page."""
        self._loaded_settings = None
        self.setCurrentIndex(_PAGE_PLACEHOLDER)

    def show_counter_config(self, settings: dict[str, Any], save_callback: Callable[[dict[str, Any]], None]) -> None:
        """Populate and switch to the counter config form.

        If the form already shows these exact settings it is left alone, so edits in progress survive
        the frequent refreshes caused by the counter changing.
        """
        self._save_cb = save_callback
        if self.currentIndex() == _PAGE_COUNTER and settings == self._loaded_settings:
            return
        self._loaded_settings = dict(settings)
        values = {**COUNTER_DEFAULTS, **settings}
        self._step_spin.setValue(_as_int(values["step"], 1))
        double_step = values.get("double_step")
        self._double_step_edit.setText("" if double_step in (None, "") else str(_as_int(double_step, 0)))
        self._max_spin.setValue(_as_int(values["max"], 0))
        self._background_btn.set_color(str(values["background"]))
        self._title_edit.setText(str(values["title"] or ""))
        self._position_combo.setCurrentIndex(max(0, self._position_combo.findData(values["title_position"])))
        self._font_combo.setCurrentFont(QFont(str(values["title_font"])))
        self._title_size_spin.setValue(_as_int(values["title_size"], 12))
        self._title_color_btn.set_color(str(values["title_color"]))
        outline = str(values["title_outline"] or "")
        self._outline_check.setChecked(bool(outline))
        self._outline_color_btn.set_color(outline or "#000000")
        self._outline_width_spin.setValue(_as_int(values["title_outline_width"], 1))
        self.setCurrentIndex(_PAGE_COUNTER)

    def counter_settings(self) -> dict[str, Any]:
        """The settings currently entered in the counter form."""
        double_text = self._double_step_edit.text().strip()
        return {
            "step": self._step_spin.value(),
            "double_step": int(double_text) if double_text else None,
            "max": self._max_spin.value(),
            "background": self._background_btn.color,
            "title": self._title_edit.text(),
            "title_position": self._position_combo.currentData(),
            "title_font": self._font_combo.currentFont().family(),
            "title_size": self._title_size_spin.value(),
            "title_color": self._title_color_btn.color,
            "title_outline": self._outline_color_btn.color if self._outline_check.isChecked() else "",
            "title_outline_width": self._outline_width_spin.value(),
        }

    def _build_counter_page(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        form = QFormLayout()
        form.addRow(_section("Counting"))
        self._add_counting_rows(form)
        form.addRow(_section("Appearance"))
        self._add_appearance_rows(form)
        layout.addLayout(form)

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._on_save)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        return scroll

    def _add_counting_rows(self, form: QFormLayout) -> None:
        form.addRow("Step:", self._step_spin)
        form.addRow("Double press step:", self._double_step_edit)
        form.addRow("Max count (0 = unlimited):", self._max_spin)

    def _add_appearance_rows(self, form: QFormLayout) -> None:
        font_row = QHBoxLayout()
        font_row.addWidget(self._font_combo, 1)
        font_row.addWidget(self._title_size_spin)
        outline_row = QHBoxLayout()
        outline_row.addWidget(self._outline_check)
        outline_row.addWidget(self._outline_color_btn)
        outline_row.addWidget(self._outline_width_spin)
        outline_row.addStretch()

        form.addRow("Background:", self._background_btn)
        form.addRow("Title:", self._title_edit)
        form.addRow("Title position:", self._position_combo)
        form.addRow("Title font:", font_row)
        form.addRow("Title colour:", self._title_color_btn)
        form.addRow("Title outline:", outline_row)

    def _on_save(self) -> None:
        if self._save_cb is not None:
            settings = self.counter_settings()
            self._loaded_settings = settings
            self._save_cb(settings)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _spin(minimum: int, maximum: int, value: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    return spin


def _section(title: str) -> QLabel:
    label = QLabel(title)
    label.setProperty("role", "title")
    label.setAlignment(Qt.AlignmentFlag.AlignLeft)
    return label
