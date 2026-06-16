"""RPyC service definition for the Decker server."""

import inspect
import json
import logging
import threading
import time
from typing import Any

import rpyc
from rpyc.core.service import Service
from rpyc.utils.server import ThreadPoolServer

from decker.plugin.context import ActionTarget
from decker.server.devices import list_devices
from decker.server.key_assignments import KeyAssignmentStore
from decker.server.plugins import PluginManager

_LONG_PRESS_HOLD_S = 0.6


class DeckerService(Service):
    """RPyC service exposed to clients for controlling the Decker application."""

    _rpyc_server: ThreadPoolServer | None = None
    _plugin_manager: PluginManager | None = None
    _key_assignment_store: KeyAssignmentStore | None = None

    @classmethod
    def configure_server(cls, server: ThreadPoolServer) -> None:
        """Bind the shared ThreadPoolServer instance before clients connect."""
        cls._rpyc_server = server

    @classmethod
    def configure_plugin_manager(cls, plugin_manager: PluginManager) -> None:
        """Bind the shared PluginManager instance before clients connect."""
        cls._plugin_manager = plugin_manager

    @classmethod
    def configure_key_assignment_store(cls, store: KeyAssignmentStore) -> None:
        """Bind the shared KeyAssignmentStore before clients connect."""
        cls._key_assignment_store = store

    def __init__(self) -> None:
        """Initialize the Decker service."""
        super().__init__()
        self._last_heartbeat: float = time.time()

    def on_connect(self, conn: Any) -> None:
        """Handle client connection."""
        logging.info("Client connected to Decker service")

    def on_disconnect(self, conn: Any) -> None:
        """Handle client disconnection."""
        logging.info("Client disconnected from Decker service")

    @rpyc.utils.exposed
    def stop(self) -> bool:
        """Gracefully shut down the server. The monitor exits on detecting a clean shutdown."""
        if self._rpyc_server is None:
            logging.error("Server reference not configured")
            return False

        def _shutdown() -> None:
            time.sleep(0.1)
            self._rpyc_server.close()  # type: ignore[union-attr]

        threading.Thread(target=_shutdown, daemon=True).start()
        logging.info("Server shutdown scheduled")
        return True

    @rpyc.utils.exposed
    def heartbeat(self) -> dict[str, Any]:
        """
        Respond to a health-check ping from the monitor.

        Returns:
            dict[str, Any]: Health status information.
        """
        self._last_heartbeat = time.time()
        return {"status": "healthy", "timestamp": self._last_heartbeat}

    @rpyc.utils.exposed
    def status(self) -> dict[str, Any]:
        """
        Get detailed service status.

        Returns:
            dict[str, Any]: Detailed status information.
        """
        return {"service_status": "running", "last_heartbeat": self._last_heartbeat}

    @rpyc.utils.exposed
    def devices_list(self) -> list[dict[str, Any]]:
        """
        List all connected Stream Deck devices.

        Returns:
            list[dict[str, Any]]: One entry per device with id, type, keys, serial, vendor_id, product_id.
        """
        return list_devices()

    @rpyc.utils.exposed
    def plugins_load_failures(self) -> list[dict[str, str]]:
        """
        List plugins that failed to load at startup.

        Returns:
            list[dict[str, str]]: One entry per failed plugin with plugin_uuid and error.
        """
        if self._plugin_manager is None:
            return []
        return [{"plugin_uuid": f.plugin_uuid, "error": f.error} for f in self._plugin_manager.load_failures()]

    @rpyc.utils.exposed
    def plugins_actions_list(self) -> list[dict[str, str]]:
        """
        List every action declared across all loaded plugin manifests.

        Returns:
            list[dict[str, str]]: One entry per action with plugin_uuid, plugin_name, action_uuid, action_name.
        """
        if self._plugin_manager is None:
            return []
        return self._plugin_manager.list_actions()

    @rpyc.utils.exposed
    def key_assign(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        device_id: str,
        key_index: int,
        plugin_uuid: str,
        action_uuid: str,
        context_id: str,
        settings_json: str = "{}",
    ) -> bool:
        """
        Assign a plugin action to a key slot and activate it.

        Returns:
            bool: True if the action was activated successfully.
        """
        if self._plugin_manager is None or self._key_assignment_store is None:
            return False
        settings: dict[str, Any] = json.loads(settings_json)
        target = ActionTarget(
            plugin_uuid=plugin_uuid,
            action_uuid=action_uuid,
            context_id=context_id,
            device_id=device_id,
            key_index=key_index,
        )
        existing = self._key_assignment_store.get(device_id, key_index)
        if existing is not None:
            self._plugin_manager.deactivate_action(existing.target)
        self._key_assignment_store.assign(device_id, key_index, target, settings)
        if self._plugin_manager._device_runner is not None:  # pylint: disable=protected-access
            self._plugin_manager._device_runner.open_device(device_id)  # pylint: disable=protected-access
        self._plugin_manager.activate_action(target)
        return True

    @rpyc.utils.exposed
    def key_unassign(self, device_id: str, key_index: int) -> bool:
        """
        Remove a plugin action from a key slot and deactivate it.

        Returns:
            bool: True if an assignment existed and was removed.
        """
        if self._plugin_manager is None or self._key_assignment_store is None:
            return False
        assignment = self._key_assignment_store.get(device_id, key_index)
        if assignment is None:
            return False
        self._plugin_manager.deactivate_action(assignment.target)
        self._key_assignment_store.unassign(device_id, key_index)
        return True

    @rpyc.utils.exposed
    def key_update_settings(self, device_id: str, key_index: int, settings_json: str) -> bool:
        """
        Update per-key action settings and notify the plugin via on_settings_changed.

        Returns:
            bool: True if the slot was assigned and settings were persisted.
        """
        if self._plugin_manager is None or self._key_assignment_store is None:
            return False
        settings: dict[str, Any] = json.loads(settings_json)
        updated = self._key_assignment_store.update_settings(device_id, key_index, settings)
        if not updated:
            return False
        assignment = self._key_assignment_store.get(device_id, key_index)
        if assignment is None:
            return False
        self._plugin_manager._settings_store.set_settings(  # pylint: disable=protected-access
            assignment.target.plugin_uuid, assignment.target.action_uuid, assignment.target.context_id, settings
        )
        self._plugin_manager.dispatch_settings_changed(assignment.target)
        return True

    @rpyc.utils.exposed
    def key_get_display_states(self, device_id: str) -> list[dict[str, Any]]:
        """
        Return display labels for all assigned keys on this device, including assignment metadata.

        Returns:
            list[dict[str, Any]]: One entry per assigned key with key_index, label, plugin_uuid,
            action_uuid, context_id, and settings.
        """
        if self._plugin_manager is None or self._key_assignment_store is None:
            return []
        label_map: dict[int, str] = {
            s["key_index"]: s["label"] for s in self._plugin_manager.get_key_display_states(device_id)
        }
        result = []
        for key_index, assignment in self._key_assignment_store.all_for_device(device_id):
            result.append(
                {
                    "key_index": key_index,
                    "label": label_map.get(key_index, ""),
                    "plugin_uuid": assignment.target.plugin_uuid,
                    "action_uuid": assignment.target.action_uuid,
                    "context_id": assignment.target.context_id,
                    "settings": assignment.settings,
                }
            )
        return result

    @rpyc.utils.exposed
    def key_simulate_press(self, device_id: str, key_index: int) -> bool:
        """
        Simulate a short key press (key_down immediately followed by key_up).

        Returns:
            bool: True if an action was assigned to this key.
        """
        return self._simulate_press(device_id, key_index, long_press=False)

    @rpyc.utils.exposed
    def key_simulate_long_press(self, device_id: str, key_index: int) -> bool:
        """
        Simulate a long key press (key_down, hold for 600 ms, then key_up).

        Returns:
            bool: True if an action was assigned to this key.
        """
        return self._simulate_press(device_id, key_index, long_press=True)

    @rpyc.utils.exposed
    def commands(self) -> dict[str, dict[str, str]]:
        """Return metadata for all user-defined exposed commands."""
        result: dict[str, dict[str, str]] = {}
        for attr, method in self.__class__.__dict__.items():
            if not callable(method) or not getattr(method, "__exposed__", False) or attr == "commands":
                continue
            cmd_path = ".".join(attr.split("_"))
            annotations = getattr(method, "__annotations__", {})
            ret = annotations.get("return", type(None))
            params = [p for p in inspect.signature(method).parameters if p != "self"]
            result[cmd_path] = {
                "description": (inspect.getdoc(method) or "").split("\n", maxsplit=1)[0],
                "return_type": getattr(ret, "__name__", str(ret)),
                "params": ", ".join(params),
            }
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _simulate_press(self, device_id: str, key_index: int, long_press: bool) -> bool:
        if self._plugin_manager is None or self._key_assignment_store is None:
            return False
        assignment = self._key_assignment_store.get(device_id, key_index)
        if assignment is None:
            return False
        target = assignment.target
        self._plugin_manager.dispatch_key_down(target)
        if long_press:
            time.sleep(_LONG_PRESS_HOLD_S)
        self._plugin_manager.dispatch_key_up(target)
        return True
