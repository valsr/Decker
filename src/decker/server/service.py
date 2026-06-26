"""RPyC service definition for the Decker server."""

import base64
import inspect
import json
import logging
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from rpyc.core.service import Service
from rpyc.utils import exposed

from decker.common.model import DeviceHardwareInfo, KeyState
from decker.common.utils import api_response
from decker.plugin.context import ActionTarget

if TYPE_CHECKING:
    from decker.server.server_context import ServerContext

_LONG_PRESS_HOLD_S = 0.6


class DeckerStatusEnum(StrEnum):
    """Status values for the Decker service."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


@dataclass
class DeckerServiceStatus:
    """Structured status information for the DeckerService."""

    service_status: DeckerStatusEnum
    last_heartbeat: float


class DeckerService(Service):
    """RPyC service exposed to clients for controlling the Decker application."""

    _context: "ServerContext | None" = None

    @classmethod
    def configure_context(cls, context: "ServerContext") -> None:
        """Bind the ServerContext singleton before clients connect."""
        cls._context = context

    def __init__(self) -> None:
        """Initialize the Decker service."""
        super().__init__()
        self._last_heartbeat: float = time.time()

    def on_connect(self, conn: Any) -> None:
        """Handle client connection — register for server-push events."""
        logging.info("Client connected to Decker service")
        if self._context is not None:
            self._context.event_bus.register(conn)

    def on_disconnect(self, conn: Any) -> None:
        """Handle client disconnection — stop pushing events to this client."""
        logging.info("Client disconnected from Decker service")
        if self._context is not None:
            self._context.event_bus.unregister(conn)

    @exposed
    def stop(self) -> bool:
        """Gracefully shut down the server. The monitor exits on detecting a clean shutdown."""
        if self._context is None:
            logging.warning("No context configured, cannot stop")
            return False

        if self._context.server is None:
            logging.error("Server reference not configured")
            return False

        def _shutdown() -> None:
            time.sleep(0.1)
            self._context.server.close()  # type: ignore[union-attr]

        threading.Thread(target=_shutdown, daemon=True).start()
        logging.info("Server shutdown scheduled")
        return True

    @exposed
    def heartbeat(self) -> str:
        """Respond to a health-check ping from the monitor."""
        self._last_heartbeat = time.time()
        return self.status()  # pyright: ignore[reportReturnType] - @api_response converts the str

    @exposed
    @api_response
    def status(self) -> DeckerServiceStatus:
        """Return service status as a JSON string."""
        return DeckerServiceStatus(service_status=DeckerStatusEnum.HEALTHY, last_heartbeat=self._last_heartbeat)

    @exposed
    @api_response
    def devices_list(self) -> list[DeviceHardwareInfo]:
        """List all connected Stream Deck devices as a JSON string."""
        if self._context is None or self._context.device_manager is None:
            logging.warning("Context or DeviceManager not initialized")
            return []

        return self._context.device_manager.list_devices()

    @exposed
    @api_response
    def plugins_load_failures(self) -> list:
        """List plugins that failed to load at startup as a JSON string."""
        if self._context is None:
            return []
        return [{"plugin_uuid": f.plugin_uuid, "error": f.error} for f in self._context.plugin_manager.load_failures()]

    @exposed
    @api_response
    def plugins_actions_list(self) -> list:
        """List every action declared across all loaded plugin manifests as a JSON string."""
        if self._context is None:
            return []
        return self._context.plugin_manager.list_actions()

    @exposed
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
        if self._context is None:
            return False
        settings: dict[str, Any] = json.loads(settings_json)
        target = ActionTarget(
            plugin_uuid=plugin_uuid,
            action_uuid=action_uuid,
            context_id=context_id,
            device_id=device_id,
            key_index=key_index,
        )
        key_store = self._context.key_assignment_store
        pm = self._context.plugin_manager
        dm = self._context.device_manager
        existing = key_store.get(device_id, key_index)
        if existing is not None:
            pm.deactivate_action(existing.target)
        key_store.assign(device_id, key_index, target, settings)
        dm.open_device(device_id)
        pm.activate_action(target)
        return True

    @exposed
    def key_unassign(self, device_id: str, key_index: int) -> bool:
        """
        Remove a plugin action from a key slot and deactivate it.

        Returns:
            bool: True if an assignment existed and was removed.
        """
        if self._context is None:
            return False
        key_store = self._context.key_assignment_store
        assignment = key_store.get(device_id, key_index)
        if assignment is None:
            return False
        self._context.plugin_manager.deactivate_action(assignment.target)
        key_store.unassign(device_id, key_index)
        self._context.device_manager.clear_key_state(device_id, key_index)
        return True

    @exposed
    def key_update_settings(self, device_id: str, key_index: int, settings_json: str) -> bool:
        """
        Update per-key action settings and notify the plugin via on_settings_changed.

        Returns:
            bool: True if the slot was assigned and settings were persisted.
        """
        if self._context is None:
            return False
        settings: dict[str, Any] = json.loads(settings_json)
        key_store = self._context.key_assignment_store
        updated = key_store.update_settings(device_id, key_index, settings)
        if not updated:
            return False
        assignment = key_store.get(device_id, key_index)
        if assignment is None:
            return False
        self._context.plugin_manager._settings_store.set_settings(  # pylint: disable=protected-access
            assignment.target.plugin_uuid, assignment.target.action_uuid, assignment.target.context_id, settings
        )
        self._context.plugin_manager.dispatch_settings_changed(assignment.target)
        return True

    @exposed
    @api_response
    def key_get_states(self, device_id: str) -> list[KeyState]:
        """Return full runtime state for every key on the device.

        Covers all keys (not just assigned ones). Unassigned keys have None for plugin fields
        and None for image_b64 if no image has been pushed yet.
        """
        if self._context is None:
            return []
        dm = self._context.device_manager
        device = dm.open_device(device_id)
        if device is None:
            return []
        hw_info = device.get_hw_info()
        key_store = self._context.key_assignment_store
        device_state = dm.get_device_state(device_id)
        result: list[KeyState] = []
        for key_index, key_info in enumerate(hw_info.keys):
            assignment = key_store.get(device_id, key_index)
            per_key = device_state.get_key_state(key_index) if device_state is not None else None
            raw_image = per_key.image if per_key is not None else None
            image_b64 = base64.b64encode(raw_image).decode("ascii") if raw_image else None
            result.append(
                KeyState(
                    key_index=key_index,
                    row=key_info.row,
                    col=key_info.col,
                    state=per_key.press_state if per_key is not None else device.get_key_state(key_index),
                    image_b64=image_b64,
                    label=per_key.label if per_key is not None else "",
                    plugin_uuid=assignment.target.plugin_uuid if assignment else None,
                    action_uuid=assignment.target.action_uuid if assignment else None,
                    context_id=assignment.target.context_id if assignment else None,
                    settings=assignment.settings if assignment else {},
                )
            )
        return result

    @exposed
    def key_simulate_press(self, device_id: str, key_index: int) -> bool:
        """
        Simulate a short key press (key_down immediately followed by key_up).

        Returns:
            bool: True if an action was assigned to this key.
        """
        return self._simulate_press(device_id, key_index, long_press=False)

    @exposed
    def key_simulate_long_press(self, device_id: str, key_index: int) -> bool:
        """
        Simulate a long key press (key_down, hold for 600 ms, then key_up).

        Returns:
            bool: True if an action was assigned to this key.
        """
        return self._simulate_press(device_id, key_index, long_press=True)

    @exposed
    @api_response
    def commands(self) -> dict:
        """Return metadata for all user-defined exposed commands as a JSON string."""
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

    @exposed
    def set_image(self, device_id: str, key_index: int, image_bytes: bytes) -> bool:
        """
        Set the image on a key from raw bytes of a PNG file.

        Returns:
            bool: True if the image was sent to an open device, False if the device is not open.
        """
        logging.info(
            "Received set_image command for device %s key %d with %d bytes", device_id, key_index, len(image_bytes)
        )
        if self._context is None or self._context.device_manager is None:
            logging.warning("Context not initialized")
            return False
        device = self._context.device_manager.open_device(device_id)
        if device is None:
            logging.warning("DeckerService.set_image: device %s not open", device_id)
            return False

        device.set_image_bytes(key_index, image_bytes)
        return True

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _simulate_press(self, device_id: str, key_index: int, long_press: bool) -> bool:
        if self._context is None:
            return False
        key_store = self._context.key_assignment_store
        assignment = key_store.get(device_id, key_index)
        if assignment is None:
            return False
        target = assignment.target
        self._context.plugin_manager.dispatch_key_down(target)
        if long_press:
            time.sleep(_LONG_PRESS_HOLD_S)
        self._context.plugin_manager.dispatch_key_up(target)
        return True
