"""Per-server-process context: bundles all singleton manager instances."""

from dataclasses import dataclass

from rpyc.utils.server import ThreadPoolServer

from decker.asset.iconpack import IconPackManager
from decker.server.device_state_store import DeviceStateStore
from decker.server.devices.manager import DeviceManager
from decker.server.event_bus import EventBus
from decker.server.key_assignments import KeyAssignmentStore
from decker.server.plugins import PluginManager


@dataclass
class ServerContext:
    """Holds every singleton manager for one running server process."""

    device_manager: DeviceManager
    plugin_manager: PluginManager
    icon_pack_manager: IconPackManager
    key_assignment_store: KeyAssignmentStore
    device_state_store: DeviceStateStore
    event_bus: EventBus
    server: ThreadPoolServer | None = None
