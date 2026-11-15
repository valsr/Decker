"""Schema of the Decker-drawn key appearance (background and title), shared by server and client."""

from typing import Any

APPEARANCE_SCHEMA: list[dict[str, Any]] = [
    {"section": "Background"},
    {"key": "background", "type": "color", "label": "Background", "default": "#000000"},
    {"section": "Title"},
    {"key": "show_title", "type": "bool", "label": "Show title", "default": True},
    {"key": "title", "type": "text", "label": "Title", "default": ""},
    {
        "key": "title_position",
        "type": "choice",
        "label": "Position",
        "default": "bottom",
        "options": [
            {"label": "Top", "value": "top"},
            {"label": "Middle", "value": "middle"},
            {"label": "Bottom", "value": "bottom"},
        ],
    },
    {"key": "title_font", "type": "font", "label": "Font", "default": "DejaVu Sans"},
    {"key": "title_size", "type": "int", "label": "Size", "default": 12, "min": 4, "max": 48},
    {"key": "title_color", "type": "color", "label": "Color", "default": "#ffffff"},
    {"key": "title_outline", "type": "color", "label": "Outline", "optional": True},
    {"key": "title_outline_width", "type": "int", "label": "Outline width", "default": 1, "min": 1, "max": 6},
]

APPEARANCE_KEYS = frozenset(e["key"] for e in APPEARANCE_SCHEMA if "key" in e)
