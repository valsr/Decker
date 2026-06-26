"""Manages the Decker RPyC server subprocess."""

import logging
import multiprocessing
import signal
import sys
from typing import Any

from rpyc.utils.server import ThreadPoolServer

import decker.common.logging
from decker.asset.iconpack import IconPackManager
from decker.common import paths as decker_paths
from decker.common.context import ServerAppContext
from decker.common.manager import Manager
from decker.server.device_state_store import DeviceStateStore
from decker.server.devices.manager import DeviceManager
from decker.server.key_assignments import KeyAssignmentStore
from decker.server.plugins import PluginManager
from decker.server.server_context import ServerContext
from decker.server.service import DeckerService


class ServerProcess:
    """Spawns and owns the RPyC server subprocess."""

    def __init__(self, port: int, startup_wait: float, app_context: ServerAppContext) -> None:
        """Initialize the server process."""
        self.port = port
        self._startup_wait = startup_wait
        self._process: multiprocessing.Process | None = None
        self._context: ServerContext | None = None
        self._app_context = app_context

    def start(self) -> bool:
        """Spawn the RPyC server subprocess.

        Returns:
            bool: True if the process started and is alive, False otherwise.
        """
        if self._process is not None and self._process.is_alive():
            logging.warning("Server process is already running")
            return False

        try:
            logging.info("Starting RPyC server on port %d", self.port)
            self._process = multiprocessing.Process(target=self._run_server, daemon=False)
            self._process.start()
            self._process.join(timeout=self._startup_wait)

            if self._process.is_alive():
                logging.info("RPyC server process started (pid %d)", self._process.pid)
                return True

            logging.error("Server process exited immediately after spawn")
            return False
        except Exception as e:
            logging.error("Failed to start server process: %s", e)
            return False

    def stop(self) -> bool:
        """Terminate the RPyC server subprocess.

        Returns:
            bool: True if stopped successfully, False an issue occurred and the process couldn't be stopped.
        """
        if self._process is None:
            logging.warning("No server process to stop")
            return True

        if not self._process.is_alive():
            self._process = None
            return True

        try:
            logging.info("Stopping RPyC server (pid %d)", self._process.pid or -1)
            self._process.terminate()
            self._process.join(timeout=5)

            if self._process.is_alive():
                logging.warning("Server process did not terminate gracefully, killing")
                self._process.kill()
                self._process.join()

            logging.info("RPyC server stopped")
            self._process = None
            return True
        except Exception as e:
            logging.error("Failed to stop server process: %s", e)
            return False

    def _try_destroy_manager(self, manager: Manager) -> None:
        """Call destroy() on a manager, catching and logging any exception."""
        try:
            manager.destroy()
        except Exception as e:  # pylint: disable=broad-except
            logging.error("Error destroying %s: %s", type(manager).__name__, e)

    @property
    def is_running(self) -> bool:
        """True if the server subprocess is alive."""
        return self._process is not None and self._process.is_alive()

    @property
    def pid(self) -> int | None:
        """PID of the server subprocess, or None if not running."""
        if self._process and self._process.is_alive():
            return self._process.pid
        return None

    @property
    def exit_code(self) -> int | None:
        """Exit code of the subprocess, or None if still running or not started."""
        if self._process is not None and not self._process.is_alive():
            return self._process.exitcode
        return None

    @property
    def exited_cleanly(self) -> bool:
        """True when the subprocess stopped with exit code 0 (intentional stop)."""
        return self.exit_code == 0

    # ------------------------------------------------------------------
    # Child-process internals
    # ------------------------------------------------------------------

    def _on_hardware_key_event(self, device_id: str, key_index: int, pressed: bool) -> None:
        """Route a hardware key event to the plugin whose action is assigned to this key."""
        if self._context is None:
            return
        assignment = self._context.key_assignment_store.get(device_id, key_index)
        if assignment is None:
            return
        if pressed:
            self._context.plugin_manager.dispatch_key_down(assignment.target)
        else:
            self._context.plugin_manager.dispatch_key_up(assignment.target)

    def _replay_assignments(self, device_id_filter: str | None = None) -> None:
        """Re-activate all persisted key assignments and reopen their devices.

        If device_id_filter is given, only replay assignments for that device.
        """
        if self._context is None:
            return
        all_ids = {info.id for info in self._context.device_manager.list_devices() if info.id is not None}
        device_ids = {device_id_filter} & all_ids if device_id_filter else all_ids
        pm = self._context.plugin_manager
        dm = self._context.device_manager
        ks = self._context.key_assignment_store
        for device_id in device_ids:
            for _key_index, assignment in ks.all_for_device(device_id):
                dm.open_device(device_id)
                pm._settings_store.set_settings(  # pylint: disable=protected-access
                    assignment.target.plugin_uuid,
                    assignment.target.action_uuid,
                    assignment.target.context_id,
                    assignment.settings,
                )
                pm.activate_action(assignment.target)

    def _restore_device_state(self, device_id_filter: str | None = None) -> None:
        """Push cached key images back to connected devices.

        If device_id_filter is given, only restore state for that device.
        Labels are already in DeviceState memory after open_device() calls restore_from_store().
        Images need to be explicitly re-pushed to the hardware after a server restart.
        """
        if self._context is None:
            return
        dm = self._context.device_manager
        for info in dm.list_devices():
            if info.id is None:
                continue
            device_id = info.id
            if device_id_filter and device_id != device_id_filter:
                continue
            device = dm.open_device(device_id)
            if device is None:
                continue
            device_state = dm.get_device_state(device_id)
            if device_state is None:
                continue
            for key_index, image in device_state.get_all_images():
                device.set_image_bytes(key_index, image)

    def _resolve_target_device(self, target: str) -> str | None:
        """Find a connected device matching the given ID or USB path.

        Returns the device ID if found, or None if no match.
        """
        if self._context is None:
            return None
        for info in self._context.device_manager.list_devices():
            if info.id == target or info.path == target:
                return info.id
        return None

    def _signal_handler(self, signum: int, _: Any) -> None:
        """Graceful shutdown: close the RPyC server."""
        logging.info("Received signal %d, shutting down", signum)
        if self._context and self._context.server:
            self._context.server.close()

    def _run_server(self) -> None:
        """Entry point for the server subprocess. Runs RPyC in the main thread."""
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        # Re-apply prefix configuration in the subprocess (safe with fork; required with spawn).
        decker_paths.configure(self._app_context.prefix)

        self.server_id = f"{self.pid or 'unknown'}"
        decker.common.logging.configure(
            self._app_context.verbosity, server_id=self.server_id, log_others=self._app_context.log_others
        )

        icon_pack_manager = IconPackManager()
        state_store = DeviceStateStore()
        key_store = KeyAssignmentStore()
        device_manager = DeviceManager(on_key_event=self._on_hardware_key_event)
        plugin_manager = PluginManager()

        self._context = ServerContext(
            device_manager=device_manager,
            plugin_manager=plugin_manager,
            icon_pack_manager=icon_pack_manager,
            key_assignment_store=key_store,
            device_state_store=state_store,
            server=None,
        )

        ctx = self._context
        assert ctx is not None
        for manager in [icon_pack_manager, state_store, key_store, device_manager, plugin_manager]:
            manager.create(ctx)

        # Resolve the target device (if --device was passed).
        matched_device_id: str | None = None
        if self._app_context.target_device is not None:
            matched_device_id = self._resolve_target_device(self._app_context.target_device)
            if matched_device_id is None:
                logging.error("Device not found: %s", self._app_context.target_device)
                for manager in [plugin_manager, device_manager, key_store, state_store, icon_pack_manager]:
                    self._try_destroy_manager(manager)
                sys.exit(1)

        # Reset device state if requested.
        if self._app_context.reset_device_data:
            if matched_device_id is not None:
                state_store.delete_all_key_state_for_device(matched_device_id)
            else:
                state_store.delete_all_key_state()

        self._replay_assignments(device_id_filter=matched_device_id)
        self._restore_device_state(device_id_filter=matched_device_id)

        server = ThreadPoolServer(
            DeckerService,
            port=self.port,
            protocol_config={"allow_public_attrs": True},
        )
        self._context.server = server
        DeckerService.configure_context(self._context)
        logging.info("RPyC server listening on port %d", self.port)
        try:
            server.start()
        finally:
            for manager in [plugin_manager, device_manager, key_store, state_store, icon_pack_manager]:
                self._try_destroy_manager(manager)
        # Normal return -> subprocess exits with code 0 (intentional stop)
