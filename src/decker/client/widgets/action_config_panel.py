"""Bottom panel for configuring the selected key's action, generated from schemas."""

from collections.abc import Callable
from typing import Any

from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from decker.client.widgets.schema_form import SchemaForm
from decker.common.appearance_schema import APPEARANCE_SCHEMA

_PAGE_PLACEHOLDER = 0
_PAGE_FORM = 1


class ActionConfigPanel(QStackedWidget):
    """Stacked config panel: page 0 = placeholder, page 1 = Appearance + action settings forms."""

    def __init__(self) -> None:
        super().__init__()
        self._save_cb: Callable[[dict[str, Any], dict[str, Any]], None] | None = None
        self._loaded: tuple[Any, ...] | None = None
        self._appearance_defaults: dict[str, Any] = {}

        placeholder = QLabel("Select a key to configure")
        placeholder.setProperty("role", "muted")
        self.addWidget(placeholder)  # page 0

        self._appearance_form = SchemaForm()
        self._settings_form = SchemaForm()
        self.addWidget(self._build_form_page())  # page 1

    def show_placeholder(self) -> None:
        """Switch to the placeholder page."""
        self._loaded = None
        self.setCurrentIndex(_PAGE_PLACEHOLDER)

    def show_action_config(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        settings_schema: list[dict[str, Any]],
        settings: dict[str, Any],
        appearance: dict[str, Any],
        appearance_defaults: dict[str, Any],
        save_cb: Callable[[dict[str, Any], dict[str, Any]], None],
    ) -> None:
        """Populate and show the forms; identical values re-sent while shown leave edits in progress alone."""
        self._save_cb = save_cb
        self._appearance_defaults = dict(appearance_defaults)
        loaded = (settings_schema, dict(settings), dict(appearance), dict(appearance_defaults))
        if self.currentIndex() == _PAGE_FORM and loaded == self._loaded:
            return
        self._loaded = loaded
        self._appearance_form.set_schema(APPEARANCE_SCHEMA, {**appearance_defaults, **appearance})
        self._settings_form.set_schema(settings_schema, settings)
        self.setCurrentIndex(_PAGE_FORM)

    def _build_form_page(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(self._appearance_form)
        layout.addWidget(self._settings_form)

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

    def _on_save(self) -> None:
        if self._save_cb is None:
            return
        settings = self._settings_form.values()
        appearance = {
            key: value
            for key, value in self._appearance_form.values().items()
            if value != self._appearance_defaults.get(key)
        }
        self._save_cb(settings, appearance)
