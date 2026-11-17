"""Form generated from a settings schema (the JSON list produced by ``schema_to_json``)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIntValidator
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QWidget,
)

from decker.client.widgets.color_button import ColorButton
from decker.client.widgets.text_style_edit import TextStyleEdit

_INT_LIMIT = 999_999_999
_DEFAULT_COLOR = "#000000"


@dataclass
class _Field:
    """A rendered schema entry: the outer widget plus how to read and write its value."""

    widget: QWidget
    get: Callable[[], Any]
    set: Callable[[Any], None]


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_field(entry: dict[str, Any]) -> _Field:
    default = _as_int(entry.get("default"), 0)
    if entry.get("optional"):
        edit = QLineEdit()
        edit.setValidator(QIntValidator(-_INT_LIMIT, _INT_LIMIT))

        def set_optional(value: Any) -> None:
            edit.setText("" if value in (None, "") else str(_as_int(value, 0)))

        return _Field(edit, lambda: int(edit.text()) if edit.text().strip() else None, set_optional)
    spin = QSpinBox()
    spin.setRange(_as_int(entry.get("min"), -_INT_LIMIT), _as_int(entry.get("max"), _INT_LIMIT))
    if entry.get("special_value"):
        spin.setSpecialValueText(str(entry["special_value"]))
    return _Field(spin, spin.value, lambda v: spin.setValue(_as_int(v, default)))


def _float_field(entry: dict[str, Any]) -> _Field:
    default = _as_float(entry.get("default"), 0.0)
    spin = QDoubleSpinBox()
    spin.setRange(_as_float(entry.get("min"), -1e9), _as_float(entry.get("max"), 1e9))
    spin.setDecimals(_as_int(entry.get("decimals"), 2))
    if entry.get("step"):
        spin.setSingleStep(_as_float(entry["step"], 1.0))
    if entry.get("special_value"):
        spin.setSpecialValueText(str(entry["special_value"]))
    return _Field(spin, spin.value, lambda v: spin.setValue(_as_float(v, default)))


def _text_field(entry: dict[str, Any]) -> _Field:
    if entry.get("multiline"):
        box = QPlainTextEdit()
        if entry.get("placeholder"):
            box.setPlaceholderText(str(entry["placeholder"]))
        return _Field(box, box.toPlainText, lambda v: box.setPlainText(str(v or "")))
    edit = QLineEdit()
    if entry.get("placeholder"):
        edit.setPlaceholderText(str(entry["placeholder"]))
    return _Field(edit, edit.text, lambda v: edit.setText(str(v or "")))


def _bool_field(_entry: dict[str, Any]) -> _Field:
    check = QCheckBox()
    return _Field(check, check.isChecked, lambda v: check.setChecked(bool(v)))


def _choice_field(entry: dict[str, Any]) -> _Field:
    combo = QComboBox()
    for option in entry.get("options") or []:
        combo.addItem(str(option["label"]), option["value"])

    def set_value(value: Any) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    return _Field(combo, combo.currentData, set_value)


def _color_field(entry: dict[str, Any]) -> _Field:
    button = ColorButton(_DEFAULT_COLOR, alpha=bool(entry.get("alpha")))
    if not entry.get("optional"):
        return _Field(button, lambda: button.color, lambda v: button.set_color(str(v or _DEFAULT_COLOR)))
    check = QCheckBox()
    container = QWidget()
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(check)
    row.addWidget(button)
    row.addStretch()
    check.toggled.connect(button.setEnabled)

    def set_value(value: Any) -> None:
        check.setChecked(bool(value))
        button.setEnabled(bool(value))
        button.set_color(str(value or _DEFAULT_COLOR))

    return _Field(container, lambda: button.color if check.isChecked() else None, set_value)


def _font_field(_entry: dict[str, Any]) -> _Field:
    combo = QFontComboBox()
    return _Field(combo, lambda: combo.currentFont().family(), lambda v: combo.setCurrentFont(QFont(str(v))))


def _text_style_field(_entry: dict[str, Any]) -> _Field:
    edit = TextStyleEdit()
    return _Field(edit, edit.value, edit.set_value)


_BUILDERS: dict[str, Callable[[dict[str, Any]], _Field]] = {
    "int": _int_field,
    "float": _float_field,
    "text": _text_field,
    "bool": _bool_field,
    "choice": _choice_field,
    "color": _color_field,
    "font": _font_field,
    "icon": _text_field,
    "text_style": _text_style_field,
}


def _build_field(entry: dict[str, Any], values: dict[str, Any]) -> _Field | None:
    """The filled widget for a schema field, or None for an unknown type."""
    builder = _BUILDERS.get(str(entry.get("type")))
    if builder is None:
        return None
    field = builder(entry)
    field.set(values.get(entry["key"], entry.get("default")))
    if entry.get("help"):
        field.widget.setToolTip(str(entry["help"]))
    return field


class SchemaForm(QWidget):
    """Renders a settings schema as a form and reads the entered values back."""

    def __init__(self) -> None:
        super().__init__()
        self._layout = QFormLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._fields: dict[str, _Field] = {}

    def set_schema(self, schema: list[dict[str, Any]], values: dict[str, Any]) -> None:
        """Rebuild the form for ``schema`` and fill it from ``values`` (missing keys use schema defaults)."""
        while self._layout.rowCount():
            self._layout.removeRow(0)
        self._fields = {}
        for entry in schema:
            if "section" in entry:
                self._layout.addRow(_section(str(entry["section"])))
                continue
            field = _build_field(entry, values)
            if field is None:
                continue
            self._fields[entry["key"]] = field
            label = entry.get("label", entry["key"])
            self._layout.addRow(f"{label}:", field.widget)

    def values(self) -> dict[str, Any]:
        """The values currently entered, keyed by schema key."""
        return {key: field.get() for key, field in self._fields.items()}


class InlineSchemaForm(QWidget):
    """Renders schema fields side by side in one row as ``Label: [widget]``; sections are ignored."""

    def __init__(self) -> None:
        super().__init__()
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._fields: dict[str, _Field] = {}

    def set_schema(self, schema: list[dict[str, Any]], values: dict[str, Any]) -> None:
        """Rebuild the row for ``schema``; the text style field takes the spare width."""
        while self._row.count():
            item = self._row.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._fields = {}
        for entry in schema:
            field = None if "section" in entry else _build_field(entry, values)
            if field is None:
                continue
            self._fields[entry["key"]] = field
            label = entry.get("label", entry["key"])
            self._row.addWidget(QLabel(f"{label}:"))
            self._row.addWidget(field.widget, 1 if entry.get("type") == "text_style" else 0)

    def values(self) -> dict[str, Any]:
        """The values currently entered, keyed by schema key."""
        return {key: field.get() for key, field in self._fields.items()}


def _section(title: str) -> QLabel:
    label = QLabel(title)
    label.setProperty("role", "title")
    label.setAlignment(Qt.AlignmentFlag.AlignLeft)
    return label
