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

from decker.client.widgets.schema_form import InlineSchemaForm, SchemaForm
from decker.common.appearance_schema import APPEARANCE_SCHEMA
from decker.common.text_style import fold_legacy_title

_PAGE_PLACEHOLDER = 0
_PAGE_FORM = 1


class ActionConfigPanel(QStackedWidget):
    """Stacked config panel: page 0 = placeholder, page 1 = Appearance + action settings forms."""

    def __init__(self) -> None:
        super().__init__()
        self._save_cb: Callable[[dict[str, Any], dict[str, Any]], None] | None = None
        self._loaded: tuple[Any, ...] | None = None
        self._appearance_defaults: dict[str, Any] = {}

        placeholder = QLabel("Hover a key and click ✎ (or focus it and press F2) to configure it")
        placeholder.setProperty("role", "muted")
        self.addWidget(placeholder)  # page 0

        self._appearance_form = InlineSchemaForm()
        self._settings_form = SchemaForm()
        self.addWidget(self._build_form_page())  # page 1

    def show_placeholder(self) -> None:
        """Switch to the placeholder page."""
        self._loaded = None
        self.setCurrentIndex(_PAGE_PLACEHOLDER)

    def forget_loaded(self) -> None:
        """Treat the next values as a different key's, so edits made for the previous key are replaced."""
        self._loaded = None

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
        appearance_defaults = fold_legacy_title(appearance_defaults)
        self._appearance_defaults = appearance_defaults
        appearance = _merged(appearance, appearance_defaults)
        loaded = (
            settings_schema,
            dict(settings),
            _resolved(appearance, appearance_defaults),
            dict(appearance_defaults),
        )
        if self.currentIndex() == _PAGE_FORM and loaded == self._loaded:
            return
        self._loaded = loaded
        self._appearance_form.set_schema(APPEARANCE_SCHEMA, appearance)
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
        form_appearance = self._appearance_form.values()
        appearance = {
            key: value for key, value in form_appearance.items() if value != self._appearance_defaults.get(key)
        }
        # Record the saved state so the server's echo is recognised as identical and keeps later edits.
        if self._loaded is not None:
            self._loaded = (
                self._loaded[0],
                settings,
                _resolved(form_appearance, self._appearance_defaults),
                self._loaded[3],
            )
        self._save_cb(settings, appearance)


def _merged(appearance: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Stored appearance with legacy title keys folded in and the title merged field-wise over the defaults."""
    folded = fold_legacy_title(appearance)
    merged = {**defaults, **folded}
    if "title" in merged:
        merged["title"] = {**defaults.get("title", {}), **folded.get("title", {})}
    return merged


def _resolved(appearance: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Appearance with defaults applied; None means "unset" and is dropped so shapes compare equal."""
    return {k: v for k, v in {**defaults, **appearance}.items() if v is not None}
