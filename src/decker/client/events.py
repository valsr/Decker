"""Application events pushed onto the EventHub by background workers."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ServerConnectedEvent:
    """The client established (or re-established) a connection to the server."""

    host: str
    port: int


@dataclass(frozen=True)
class ServerDisconnectedEvent:
    """The client lost its connection to the server, or a connection attempt failed."""

    reason: str


@dataclass(frozen=True)
class DeviceListUpdatedEvent:
    """The set of devices known to the server has changed."""

    devices: list[dict[str, Any]]


@dataclass(frozen=True)
class KeyEvent:
    """A physical key on a Stream Deck device was pressed or released."""

    device_id: str
    key_index: int
    pressed: bool


@dataclass(frozen=True)
class PluginLoadFailedEvent:
    """A plugin failed to load on the server and was skipped."""

    plugin_uuid: str
    error: str


@dataclass(frozen=True)
class ActionListUpdatedEvent:
    """The set of plugin actions known to the server has changed."""

    actions: list[dict[str, str]]


AppEvent = (
    ServerConnectedEvent
    | ServerDisconnectedEvent
    | DeviceListUpdatedEvent
    | KeyEvent
    | PluginLoadFailedEvent
    | ActionListUpdatedEvent
)
