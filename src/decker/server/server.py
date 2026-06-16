"""Manages the Decker RPyC server subprocess."""

import logging
import multiprocessing
import signal
from typing import Any

from rpyc.utils.server import ThreadPoolServer

from decker.asset.iconpack import IconPackManager
from decker.asset.paths import ensure_asset_dirs
from decker.common.db import migrate_legacy_db
from decker.server.device_runner import DeviceRunner
from decker.server.key_assignments import KeyAssignmentStore
from decker.server.plugins import PluginManager
from decker.server.service import DeckerService


class ServerProcess:
    """Spawns and owns the RPyC server subprocess."""

    def __init__(self, port: int = 18861, startup_wait: float = 5.0) -> None:
        """Initialize the server process."""
        self.port = port
        self._startup_wait = startup_wait
        self._process: multiprocessing.Process | None = None
        self._server: ThreadPoolServer | None = None
        self._plugin_manager: PluginManager | None = None

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
            bool: True if stopped successfully, False if there was nothing to stop.
        """
        if self._process is None:
            logging.warning("No server process to stop")
            return False

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
        if self._plugin_manager is None:
            return
        from decker.server.key_assignments import (
            KeyAssignmentStore,  # pylint: disable=import-outside-toplevel
        )

        store = DeckerService._key_assignment_store  # pylint: disable=protected-access
        if store is None:
            return
        assignment = store.get(device_id, key_index)
        if assignment is None:
            return
        if pressed:
            self._plugin_manager.dispatch_key_down(assignment.target)
        else:
            self._plugin_manager.dispatch_key_up(assignment.target)

    def _replay_assignments(self, key_store: Any) -> None:
        """Re-activate all persisted key assignments and reopen their devices."""
        if self._plugin_manager is None:
            return
        from decker.server.devices import (
            list_devices,  # pylint: disable=import-outside-toplevel
        )

        device_ids = {d["id"] for d in list_devices() if d.get("id")}
        for device_id in device_ids:
            for _key_index, assignment in key_store.all_for_device(device_id):
                if self._plugin_manager._device_runner is not None:  # pylint: disable=protected-access
                    self._plugin_manager._device_runner.open_device(device_id)  # pylint: disable=protected-access
                self._plugin_manager._settings_store.set_settings(  # pylint: disable=protected-access
                    assignment.target.plugin_uuid,
                    assignment.target.action_uuid,
                    assignment.target.context_id,
                    assignment.settings,
                )
                self._plugin_manager.activate_action(assignment.target)

    def _signal_handler(self, signum: int, _: Any) -> None:
        """Graceful shutdown: close the RPyC server."""
        logging.info("Received signal %d, shutting down", signum)
        if self._server:
            self._server.close()

    def _run_server(self) -> None:
        """Entry point for the server subprocess. Runs RPyC in the main thread."""
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        migrate_legacy_db()
        ensure_asset_dirs()
        IconPackManager().discover_manual_dropins()

        key_store = KeyAssignmentStore()
        self._plugin_manager = PluginManager()
        device_runner = DeviceRunner(on_key_event=self._on_hardware_key_event)
        self._plugin_manager.set_device_runner(device_runner)
        self._plugin_manager.start()
        self._replay_assignments(key_store)

        self._server = ThreadPoolServer(
            DeckerService,
            port=self.port,
            protocol_config={"allow_public_attrs": True},
        )
        DeckerService.configure_server(self._server)
        DeckerService.configure_plugin_manager(self._plugin_manager)
        DeckerService.configure_key_assignment_store(key_store)
        logging.info("RPyC server listening on port %d", self.port)
        try:
            self._server.start()  # blocks until close() is called
        finally:
            self._plugin_manager.stop()
            key_store.close()
        # Normal return → subprocess exits with code 0 (intentional stop)
