"""Bottom panel for configuring the selected key: live preview, appearance rows and action settings."""

import logging
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import Qt, QTimer
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

from decker.client.widgets.key_preview import KeyPreview
from decker.client.widgets.schema_form import AppearanceForm, SchemaForm
from decker.common.appearance_schema import APPEARANCE_SCHEMA
from decker.common.text_style import fold_legacy_title

_PAGE_PLACEHOLDER = 0
_PAGE_FORM = 1
_PREVIEW_DEBOUNCE_MS = 150

_TOP = Qt.AlignmentFlag.AlignTop

PreviewProvider = Callable[[dict[str, Any]], str | None]
SaveCallback = Callable[[dict[str, Any], dict[str, Any]], bool | None]  # False = the save failed


class ActionConfigPanel(QStackedWidget):  # pylint: disable=too-many-instance-attributes
    """Stacked config panel: page 0 = placeholder, page 1 = preview, appearance rows, Save and action settings."""

    def __init__(self) -> None:
        super().__init__()
        self._save_cb: SaveCallback | None = None
        self._loaded: tuple[Any, ...] | None = None
        self._appearance_defaults: dict[str, Any] = {}
        self._preview_provider: PreviewProvider | None = None
        self._dirty = False
        self._baseline: tuple[dict[str, Any], dict[str, Any]] | None = None

        placeholder = QLabel("Hover a key and click ✎ (or focus it and press F2) to configure it")
        placeholder.setProperty("role", "muted")
        self.addWidget(placeholder)  # page 0

        self._header = QLabel()
        self._header.setProperty("role", "title")
        self._preview = KeyPreview()
        self._appearance_form = AppearanceForm()
        self._settings_form = SchemaForm()
        self._save_btn = QPushButton("Save")
        self._save_btn.setProperty("dirty", False)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_DEBOUNCE_MS)
        self._preview_timer.timeout.connect(self._request_preview)
        self.addWidget(self._build_form_page())  # page 1
        self._appearance_form.changed.connect(self._on_edited)
        self._settings_form.changed.connect(self._on_edited)

    @property
    def is_dirty(self) -> bool:
        """Whether the forms differ from the last loaded or saved values."""
        return self._dirty

    def set_preview_provider(self, provider: PreviewProvider | None) -> None:
        """Set how the draft appearance is turned into a base64 key image (None or "" keeps the last picture)."""
        self._preview_provider = provider

    def set_preview_image(self, image_b64: str | None) -> None:
        """Show an image in the preview."""
        self._preview.set_image(image_b64)

    def show_placeholder(self) -> None:
        """Switch to the placeholder page."""
        self._reset_editing()
        self.setCurrentIndex(_PAGE_PLACEHOLDER)

    def forget_loaded(self) -> None:
        """Treat the next values as a different key's, so edits made for the previous key are replaced."""
        self._reset_editing()

    def _reset_editing(self) -> None:
        self._loaded = None
        self._baseline = None
        self._preview_timer.stop()
        self._preview.set_image(None)
        self._refresh_state()

    def show_action_config(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        settings_schema: list[dict[str, Any]],
        settings: dict[str, Any],
        appearance: dict[str, Any],
        appearance_defaults: dict[str, Any],
        save_cb: SaveCallback,
        title: str = "",
    ) -> None:
        """Populate and show the forms; identical values re-sent while shown leave edits in progress alone."""
        self._save_cb = save_cb
        self._header.setText(title)
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
        self._baseline = self._current_values()
        self._refresh_state()
        self._request_preview()

    def _build_form_page(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(self._header)

        rows = QVBoxLayout()
        rows.addWidget(self._appearance_form)
        save_row = QHBoxLayout()
        self._save_btn.clicked.connect(self._on_save)
        save_row.addWidget(self._save_btn)
        save_row.addStretch()
        rows.addLayout(save_row)
        top = QHBoxLayout()
        top.addWidget(self._preview, 0, _TOP)
        top.addLayout(rows, 1)
        layout.addLayout(top)
        layout.addWidget(self._settings_form)
        layout.addStretch()

        self._preview.set_icon_requested.connect(self._browse_icon)
        self._preview.clear_icon_requested.connect(self._clear_icon)

        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        return scroll

    def _icon_edit(self) -> Any:
        field = self._appearance_form._fields.get("icon")  # pylint: disable=protected-access
        return field.widget if field is not None else None

    def _browse_icon(self) -> None:
        if (edit := self._icon_edit()) is not None:
            edit.browse()

    def _clear_icon(self) -> None:
        if (edit := self._icon_edit()) is not None:
            edit.clear_icon()

    def _on_edited(self) -> None:
        self._refresh_state()
        self._preview_timer.start()

    def _refresh_state(self) -> None:
        values = self._current_values()
        dirty = self._baseline is not None and values != self._baseline
        if dirty != self._dirty or self._save_btn.property("dirty") != dirty:
            self._dirty = dirty
            self._save_btn.setProperty("dirty", dirty)
            if (style := self._save_btn.style()) is not None:
                style.unpolish(self._save_btn)
                style.polish(self._save_btn)
        icon = self._appearance_form.values().get("icon")
        self._preview.set_has_icon(isinstance(icon, dict) and bool(icon.get("ref")))

    def _current_values(self) -> tuple[dict[str, Any], dict[str, Any]]:
        return self._settings_form.values(), _resolved(self._appearance_form.values(), self._appearance_defaults)

    def _draft_appearance(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in self._appearance_form.values().items()
            if value != self._appearance_defaults.get(key)
        }

    def _request_preview(self) -> None:
        if self._preview_provider is None:
            return
        try:
            image = self._preview_provider(self._draft_appearance())
        except Exception:  # pylint: disable=broad-except
            logging.debug("Key preview failed", exc_info=True)
            return
        if image:
            self._preview.set_image(image)

    def _on_save(self) -> None:
        if self._save_cb is None:
            return
        settings = self._settings_form.values()
        form_appearance = self._appearance_form.values()
        previous = (self._loaded, self._baseline)
        # Record the saved state first so a synchronous echo of it is recognised as identical and keeps later edits.
        if self._loaded is not None:
            self._loaded = (
                self._loaded[0],
                settings,
                _resolved(form_appearance, self._appearance_defaults),
                self._loaded[3],
            )
        self._baseline = self._current_values()
        saved = self._save_cb(settings, self._draft_appearance())
        if saved is False:
            self._loaded, self._baseline = previous
        self._refresh_state()


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
