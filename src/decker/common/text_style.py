"""Text style value shared by the settings schema, the key renderer and the client control."""

import re
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

POSITIONS: tuple[str, ...] = ("top", "middle", "bottom")
SIZE_RANGE: tuple[int, int] = (4, 48)
OUTLINE_WIDTH_RANGE: tuple[int, int] = (1, 6)

TEXT_STYLE_DEFAULTS: Mapping[str, Any] = MappingProxyType(
    {
        "text": "",
        "visible": True,
        "font": "DejaVu Sans",
        "size": 12,
        "bold": False,
        "italic": False,
        "underline": False,
        "strike": False,
        "position": "bottom",
        "color": "#ffffff",
        "outline": None,
        "outline_width": 1,
    }
)

_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")
_LEGACY_FIELDS: dict[str, str] = {
    "title": "text",
    "show_title": "visible",
    "title_position": "position",
    "title_font": "font",
    "title_size": "size",
    "title_color": "color",
    "title_outline": "outline",
    "title_outline_width": "outline_width",
}
LEGACY_TITLE_KEYS: frozenset[str] = frozenset(_LEGACY_FIELDS) - {"title"}


def _is_int_in(value: Any, bounds: tuple[int, int]) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and bounds[0] <= value <= bounds[1]


def _is_color(value: Any) -> bool:
    return isinstance(value, str) and _COLOR_PATTERN.match(value) is not None


def _is_outline(value: Any) -> bool:
    return value is None or value == "" or _is_color(value)


_VALIDATORS: dict[str, Callable[[Any], bool]] = {
    "text": lambda v: isinstance(v, str),
    "visible": lambda v: isinstance(v, bool),
    "font": lambda v: isinstance(v, str),
    "size": lambda v: _is_int_in(v, SIZE_RANGE),
    "bold": lambda v: isinstance(v, bool),
    "italic": lambda v: isinstance(v, bool),
    "underline": lambda v: isinstance(v, bool),
    "strike": lambda v: isinstance(v, bool),
    "position": lambda v: v in POSITIONS,
    "color": _is_color,
    "outline": _is_outline,
    "outline_width": lambda v: _is_int_in(v, OUTLINE_WIDTH_RANGE),
}


def normalize_text_style(value: Any, defaults: Mapping[str, Any] = TEXT_STYLE_DEFAULTS) -> dict[str, Any]:
    """Complete text style dict: each invalid or missing field falls back to ``defaults``; unknown keys are dropped."""
    source: Mapping[str, Any] = value if isinstance(value, Mapping) else {}
    result: dict[str, Any] = {}
    for name, valid in _VALIDATORS.items():
        raw = source.get(name, defaults[name])
        result[name] = raw if valid(raw) else defaults[name]
    if result["outline"] == "":
        result["outline"] = None
    return result


def fold_legacy_title(values: Mapping[str, Any]) -> dict[str, Any]:
    """Copy of ``values`` with the flat ``title_*``/``show_title`` keys folded into a partial nested ``title`` dict."""
    result = {k: v for k, v in values.items() if k not in _LEGACY_FIELDS}
    nested: dict[str, Any] = {}
    for legacy, name in _LEGACY_FIELDS.items():
        if legacy in values and not (legacy == "title" and isinstance(values[legacy], Mapping)):
            nested[name] = values[legacy]
    if isinstance(values.get("title"), Mapping):
        nested.update(values["title"])
    if nested:
        result["title"] = nested
    return result
