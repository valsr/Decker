"""Background value shared by the settings schema, the key renderer and the client control."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from decker.common.icon_ref import normalize_icon_value
from decker.common.text_style import is_color

BACKGROUND_TYPES: tuple[str, ...] = ("none", "color", "image")
BACKGROUND_DEFAULT: Mapping[str, Any] = MappingProxyType(
    {"type": "color", "color": "#000000", "image": MappingProxyType({"ref": ""})}
)


def normalize_background(value: Any, defaults: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Complete background dict; a bare colour string is the legacy form. Invalid fields fall back to ``defaults``."""
    base = defaults if defaults is not None else BACKGROUND_DEFAULT
    if isinstance(value, str):
        source: Mapping[str, Any] = {"type": "color", "color": value}
    else:
        source = value if isinstance(value, Mapping) else {}
    kind = source.get("type", base["type"])
    color = source.get("color", base["color"])
    image = source.get("image", base["image"])
    ref = normalize_icon_value(image, {"ref": base["image"]["ref"], "color": "#ffffff"})["ref"]
    return {
        "type": kind if kind in BACKGROUND_TYPES else base["type"],
        "color": color if is_color(color) else base["color"],
        "image": {"ref": ref},
    }
