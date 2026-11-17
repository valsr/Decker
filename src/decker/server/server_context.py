"""Per-server-process context: bundles all singleton manager instances."""

from dataclasses import dataclass

from rpyc.utils.server import Server

from decker.server.device_state_store import DeviceStateStore
from decker.server.devices.manager import DeviceManager
from decker.server.event_bus import EventBus
from decker.server.key_assignments import KeyAssignmentStore
from decker.server.page_controller import PageController
from decker.server.pages import PageStore
from decker.server.plugin_installer import PluginInstaller
from decker.server.plugins import PluginManager
from decker.server.repositories import RepositoryStore
from decker.server.update_checker import UpdateChecker


@dataclass
class ServerContext:
    """Holds every singleton manager for one running server process."""

    device_manager: DeviceManager
    plugin_manager: PluginManager
    key_assignment_store: KeyAssignmentStore
    device_state_store: DeviceStateStore
    page_store: PageStore
    page_controller: PageController
    event_bus: EventBus
    server: Server | None = None
    plugin_installer: PluginInstaller | None = None
    repository_store: RepositoryStore | None = None
    update_checker: UpdateChecker | None = None
