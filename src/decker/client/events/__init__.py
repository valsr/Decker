"""Application events flowing through the EventManager."""

from dataclasses import dataclass
from typing import Any

from decker.client.view_name import ViewName
from decker.common.model import DeviceHardwareInfo, DevicePages


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
class OpenUrlRequestedEvent:
    """A plugin asked the client to open a URL in the user's browser."""

    plugin_id: str
    url: str


@dataclass(frozen=True)
class ActionListUpdatedEvent:
    """The set of plugin actions known to the server has changed."""

    actions: list[dict[str, Any]]


@dataclass(frozen=True)
class KeyDisplayStatesUpdatedEvent:
    """The display label for one or more assigned keys on the active device has changed."""

    device_id: str
    states: list[dict[str, Any]]


@dataclass(frozen=True)
class PagesUpdatedEvent:
    """The active device's pages, default page or active (on-device) page changed."""

    pages: DevicePages


@dataclass(frozen=True)
class PluginInstallProgressEvent:
    """A plugin install job reported a progress message."""

    job_id: str
    message: str


@dataclass(frozen=True)
class PluginInstallFinishedEvent:
    """A plugin install job finished, successfully or not."""

    job_id: str
    ok: bool
    plugin_id: str
    version: str
    previous_version: str
    message: str


@dataclass(frozen=True)
class PluginsChangedEvent:
    """The set of installed plugins changed on the server."""


@dataclass(frozen=True)
class PluginUpdatesAvailableEvent:
    """Installed plugins have updates, or repository plugins are missing from this machine."""

    updates: list[dict[str, Any]]
    missing: list[dict[str, Any]]


@dataclass(frozen=True)
class RepositoriesCheckFinishedEvent:
    """A repository check started with `repositories_check` finished; carries the repositories' status."""

    repositories: list[dict[str, Any]]


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
    | OpenUrlRequestedEvent
    | ActionListUpdatedEvent
    | KeyDisplayStatesUpdatedEvent
    | PagesUpdatedEvent
    | PluginInstallProgressEvent
    | PluginInstallFinishedEvent
    | PluginsChangedEvent
    | PluginUpdatesAvailableEvent
    | RepositoriesCheckFinishedEvent
    | ViewActivatedEvent
    | ViewDeactivatedEvent
)
