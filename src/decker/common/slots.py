"""The slots value of the Switch card: what each of its four gestures shows or runs."""

from collections.abc import Mapping
from typing import Any

SLOT_NAMES: tuple[str, ...] = ("display", "press", "double_press", "long_press")
SWITCH_CARD_ID: str = "com.decker.core.switch"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _card_slot(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    plugin, card = raw.get("plugin"), raw.get("card")
    if not isinstance(plugin, str) or not isinstance(card, str) or card == SWITCH_CARD_ID:
        return None
    settings, appearance = raw.get("settings", {}), raw.get("appearance", {})
    if not isinstance(settings, Mapping) or not isinstance(appearance, Mapping):
        return None
    return {
        "kind": "card",
        "plugin": plugin,
        "card": card,
        "settings": dict(settings),
        "appearance": dict(appearance),
    }


def _action_slot(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    action, settings = raw.get("action"), raw.get("settings", {})
    if not isinstance(action, str) or not isinstance(settings, Mapping):
        return None
    return {"kind": "action", "action": action, "settings": dict(settings)}


def _normalize_slot(name: str, raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    kind = raw.get("kind")
    if kind == "card":
        return _card_slot(raw)
    if kind == "action" and name != "display":
        return _action_slot(raw)
    return None


def normalize_slots(value: Any, default: Any = None) -> dict[str, dict[str, Any] | None]:
    """Complete four-slot dict; each slot is a valid card or action slot, else None (``default`` is unused)."""
    del default
    source = _mapping(value)
    return {name: _normalize_slot(name, source.get(name)) for name in SLOT_NAMES}
