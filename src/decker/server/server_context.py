"""Per-server-process context: bundles all singleton manager instances."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rpyc.utils.server import Server

from decker.server.app_rule_controller import AppRuleController
from decker.server.app_rule_store import AppRuleStore
from decker.server.client_tracker import ClientTracker
from decker.server.device_state_store import DeviceStateStore
from decker.server.devices.manager import DeviceManager
from decker.server.event_bus import EventBus
from decker.server.key_assignments import KeyAssignmentStore
from decker.server.page_controller import PageController
from decker.server.pages import PageStore
from decker.server.plugin_installer import PluginInstaller
from decker.server.plugins import PluginManager
from decker.server.reconfigure import ReconfigurePolicy
from decker.server.repositories import RepositoryStore
from decker.server.update_checker import UpdateChecker

if TYPE_CHECKING:  # the engine and watcher modules arrive in later tasks
    from decker.server.app_rule_engine import AppRuleEngine  # type: ignore[import-not-found]  # isort: skip
    from decker.server.window_watcher import WindowWatcher


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
    reconfigure_policy: ReconfigurePolicy = field(default_factory=lambda: ReconfigurePolicy(None))
    restart_requested: bool = False
    client_tracker: ClientTracker | None = None
    app_rule_store: AppRuleStore | None = None
    app_rule_controller: AppRuleController | None = None
    app_rule_engine: "AppRuleEngine | None" = None
    window_watcher: "WindowWatcher | None" = None
