"""Bottom panel for configuring the selected key's action."""

from collections.abc import Callable
from typing import Any

from PyQt6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

_PAGE_PLACEHOLDER = 0
_PAGE_COUNTER = 1


class ActionConfigPanel(QStackedWidget):
    """Stacked config panel: page 0 = placeholder, page 1 = counter action form."""

    def __init__(self) -> None:
        super().__init__()
        self._save_cb: Callable[[dict[str, Any]], None] | None = None

        placeholder = QLabel("Select a key to configure")
        placeholder.setStyleSheet("color: #8e8e93; font-size: 12px;")
        self.addWidget(placeholder)  # page 0

        self.addWidget(self._build_counter_page())  # page 1

    def show_placeholder(self) -> None:
        """Switch to the placeholder page."""
        self.setCurrentIndex(_PAGE_PLACEHOLDER)

    def show_counter_config(self, settings: dict[str, Any], save_callback: Callable[[dict[str, Any]], None]) -> None:
        """Populate and switch to the counter config form."""
        self._save_cb = save_callback
        self._step_spin.setValue(int(settings.get("step", 1)))
        self._max_spin.setValue(int(settings.get("max", 0)))
        self.setCurrentIndex(_PAGE_COUNTER)

    def _build_counter_page(self) -> QWidget:
        page = QWidget()
        self._step_spin = QSpinBox()
        self._step_spin.setMinimum(1)
        self._step_spin.setMaximum(9999)
        self._step_spin.setValue(1)

        self._max_spin = QSpinBox()
        self._max_spin.setMinimum(0)
        self._max_spin.setMaximum(99999)
        self._max_spin.setValue(0)
        self._max_spin.setSpecialValueText("∞ (no limit)")

        form = QFormLayout()
        form.addRow("Step:", self._step_spin)
        form.addRow("Max count (0 = unlimited):", self._max_spin)

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._on_save)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(save_btn)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addLayout(form)
        layout.addLayout(btn_row)
        layout.addStretch()
        return page

    def _on_save(self) -> None:
        if self._save_cb is not None:
            self._save_cb({"step": self._step_spin.value(), "max": self._max_spin.value()})
