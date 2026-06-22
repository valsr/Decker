"""Manages the Decker RPyC server subprocess."""

import logging
import multiprocessing
import signal
from typing import Any

from rpyc.utils.server import ThreadPoolServer

from decker.asset.iconpack import IconPackManager
from decker.common.manager import Manager
from decker.server.device_manager import DeviceManager
from decker.server.devices import list_devices
from decker.server.key_assignments import KeyAssignmentStore
from decker.server.plugins import PluginManager
from decker.server.server_context import ServerContext
from decker.server.service import DeckerService


class ServerProcess:
    """Spawns and owns the RPyC server subprocess."""

    def __init__(self, port: int, startup_wait: float) -> None:
        """Initialize the server process."""
        self.port = port
        self._startup_wait = startup_wait
        self._process: multiprocessing.Process | None = None
        self._context: ServerContext | None = None

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

    def _replay_assignments(self) -> None:
        """Re-activate all persisted key assignments and reopen their devices."""
        if self._context is None:
            return
        device_ids = {info.id for info in list_devices() if info.id is not None}
        pm = self._context.plugin_manager
        dm = self._context.device_manager
        ks = self._context.key_assignment_store
        for device_id in device_ids:
            for _key_index, assignment in ks.all_for_device(device_id):
                dm.get_device(device_id)
                pm._settings_store.set_settings(  # pylint: disable=protected-access
                    assignment.target.plugin_uuid,
                    assignment.target.action_uuid,
                    assignment.target.context_id,
                    assignment.settings,
                )
                pm.activate_action(assignment.target)

    def _signal_handler(self, signum: int, _: Any) -> None:
        """Graceful shutdown: close the RPyC server."""
        logging.info("Received signal %d, shutting down", signum)
        if self._context and self._context.server:
            self._context.server.close()

    def _run_server(self) -> None:
        """Entry point for the server subprocess. Runs RPyC in the main thread."""
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        icon_pack_manager = IconPackManager()
        key_store = KeyAssignmentStore()
        device_manager = DeviceManager(on_key_event=self._on_hardware_key_event)
        plugin_manager = PluginManager()

        self._context = ServerContext(
            device_manager=device_manager,
            plugin_manager=plugin_manager,
            icon_pack_manager=icon_pack_manager,
            key_assignment_store=key_store,
            server=None,  # set after server creation
        )

        # Create managers in order of dependencies (managers can depend on previously created ones via the context)
        ctx = self._context
        assert ctx is not None
        for manager in [icon_pack_manager, key_store, device_manager, plugin_manager]:
            manager.create(ctx)

        self._replay_assignments()

        server = ThreadPoolServer(
            DeckerService,
            port=self.port,
            protocol_config={"allow_public_attrs": True},
        )
        self._context.server = server  # circular reference, but should be fine since they have the same lifecycle
        DeckerService.configure_context(self._context)
        logging.info("RPyC server listening on port %d", self.port)
        try:
            server.start()  # blocks until close() is called
        finally:
            for manager in [plugin_manager, device_manager, key_store, icon_pack_manager]:
                self._try_destroy_manager(manager)
        # Normal return -> subprocess exits with code 0 (intentional stop)
