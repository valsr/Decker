"""Schema of the Decker-drawn key appearance (title and RGBA background), shared by server and client."""

from typing import Any

from decker.common.text_style import LEGACY_TITLE_KEYS

APPEARANCE_SCHEMA: list[dict[str, Any]] = [
    {"key": "title", "type": "text_style", "label": "Title"},
    {"key": "background", "type": "color", "label": "Background", "default": "#000000", "alpha": True},
]

# The flat title_* / show_title keys predate the nested title; they stay accepted and are folded on read.
APPEARANCE_KEYS = frozenset(e["key"] for e in APPEARANCE_SCHEMA if "key" in e) | LEGACY_TITLE_KEYS
