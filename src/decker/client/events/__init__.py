"""Application events flowing through the EventManager."""

from dataclasses import dataclass
from typing import Any

from decker.client.view_name import ViewName
from decker.common.model import DeviceHardwareInfo


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

    devices: list[DeviceHardwareInfo]


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


@dataclass(frozen=True)
class KeyDisplayStatesUpdatedEvent:
    """The display label for one or more assigned keys on the active device has changed."""

    device_id: str
    states: list[dict[str, Any]]


@dataclass(frozen=True)
class ViewActivatedEvent:
    """A view became the active view in the main window."""

    view_name: ViewName


@dataclass(frozen=True)
class ViewDeactivatedEvent:
    """A view was replaced as the active view in the main window."""

    view_name: ViewName


AppEvent = (
    ServerConnectedEvent
    | ServerDisconnectedEvent
    | DeviceListUpdatedEvent
    | KeyEvent
    | PluginLoadFailedEvent
    | ActionListUpdatedEvent
    | KeyDisplayStatesUpdatedEvent
    | ViewActivatedEvent
    | ViewDeactivatedEvent
)
