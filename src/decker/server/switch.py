"""Decide what each gesture on a Switch card does and which slot's card it currently shows."""

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from decker.plugin.gestures import Gesture

_GESTURE_SLOTS: dict[Gesture, str] = {
    Gesture.PRESS: "press",
    Gesture.DOUBLE_PRESS: "double_press",
    Gesture.LONG_PRESS: "long_press",
}


@dataclass(frozen=True)
class SwitchOutcome:
    """What a gesture asks for: run an action, or show a slot (None means no change)."""

    action: tuple[str, dict[str, Any]] | None = None
    show: str | None = None


def _is_card(slot: Any) -> bool:
    return isinstance(slot, Mapping) and slot.get("kind") == "card"


class SwitchController:
    """Remembers, in memory, which slot each Switch context shows, and maps gestures to outcomes."""

    def __init__(self) -> None:
        self._shown: dict[str, str] = {}
        self._lock = threading.Lock()

    def gestures(self, slots: Mapping[str, Any]) -> frozenset[Gesture]:
        """The gestures whose slot is filled."""
        return frozenset(gesture for gesture, name in _GESTURE_SLOTS.items() if slots.get(name) is not None)

    def shown_slot(self, context_id: str, slots: Mapping[str, Any]) -> str | None:
        """The slot whose card is shown, or None when there is none."""
        with self._lock:
            return self._shown_locked(context_id, slots)

    def handle(self, context_id: str, slots: Mapping[str, Any], gesture: Gesture) -> SwitchOutcome:
        """Decide what a gesture does, remembering a newly shown card slot."""
        name = _GESTURE_SLOTS[gesture]
        slot = slots.get(name)
        if slot is None:
            return SwitchOutcome()
        if slot.get("kind") == "action":
            return SwitchOutcome(action=(slot["action"], dict(slot["settings"])))
        with self._lock:
            shown = self._shown_locked(context_id, slots)
            if shown is not None and slots.get(shown) == slot:
                return SwitchOutcome()
            self._shown[context_id] = name
        return SwitchOutcome(show=name)

    def forget(self, context_id: str) -> None:
        """Drop the remembered slot of a context."""
        with self._lock:
            self._shown.pop(context_id, None)

    def _shown_locked(self, context_id: str, slots: Mapping[str, Any]) -> str | None:
        remembered = self._shown.get(context_id)
        for name in (remembered, "display", "press"):
            if name is not None and _is_card(slots.get(name)):
                return name
        return None
