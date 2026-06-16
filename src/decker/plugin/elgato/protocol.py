"""Elgato Stream Deck SDK WebSocket JSON event (de)serialization."""

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ElgatoEvent:
    """One event exchanged with an Elgato plugin process over its WebSocket connection."""

    event: str
    context: str | None = None
    action: str | None = None
    payload: dict[str, Any] | None = None


def serialize(event: ElgatoEvent) -> str:
    """Encode an ElgatoEvent as the JSON string sent over the WebSocket connection."""
    data: dict[str, Any] = {"event": event.event}
    if event.context is not None:
        data["context"] = event.context
    if event.action is not None:
        data["action"] = event.action
    if event.payload is not None:
        data["payload"] = event.payload
    return json.dumps(data)


def deserialize(raw: str) -> ElgatoEvent:
    """Decode a JSON string received over the WebSocket connection into an ElgatoEvent.

    Raises ValueError if the JSON is malformed or missing the required 'event' field.
    """
    data = json.loads(raw)
    if not isinstance(data, dict) or "event" not in data:
        raise ValueError(f"Elgato event missing 'event' field: {raw!r}")
    return ElgatoEvent(
        event=data["event"],
        context=data.get("context"),
        action=data.get("action"),
        payload=data.get("payload"),
    )
