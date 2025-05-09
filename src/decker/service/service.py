"""Manages Decker Servers."""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Any
import rpyc

from decker import platform, theme
from enum import Enum

FILE_LOCK = os.path.join(tempfile.gettempdir(), "decker_service.lock")

class ServiceManager:

    def __init__(self, device_id: str):
        self.device_id: str = device_id
        self.api: ApiService | None = None # User-facing service that handles client connections
        self.device: DeviceService | None = None # Device-facing service that handles device connections
        self._lock_file: Any = None
        self._state: ServiceState = ServiceState.STOPPED
        self._failure: Any = None

    @property
    def status(self) -> ServiceState:
        """Returns the current status of the server/service/manager."""
        return self._state

    @property
    def failure(self) -> Any:
        """Returns the failure reason if the server/service/manager is in a failed state."""
        return self._failure

    def start(self):
        """Starts the server and service instance if no other instance are running."""
        if self._state.is_running_state():
            logging.warning(theme.warning("Server is already running."))
            return

        if not self._acquire_lock_file():
            logging.error(theme.error(f"Failed to acquire server lock {FILE_LOCK}."))
            self._state = ServiceState.FAILED
            return

        self._state = ServiceState.BUSY
        try:
            self._start_server()
            self._start_service()
            self._state = ServiceState.OK
            logging.info(theme.primary("Server started successfully"))

        except Exception as e:
            self._set_to_failure_state(e)

    def _get_server_state(self) -> ServiceState:
        """Returns the current state of the server."""
        if self.device is None:
            return ServiceState.STOPPED
        return self.device.status

    def _start_server(self):
        """Starts the server instance."""
        if self.device is not None:
            logging.warning(theme.warning("Server is already running."))
            return

        logging.info(theme.primary("Starting server"))
        self.device = DeviceService(self.device_id)
        self.device.start()

    def _start_service(self):
        """Starts the service instance."""
        if self.api is not None:
            logging.warning(theme.warning("Service is already running."))
            return

        if self.device is None:
            raise RuntimeError("Server is not running. Cannot start service.")

        logging.info(theme.primary("Starting service"))
        self.api = ApiService(self.device)
        self.api.start()

    def _set_to_failure_state(self, failure: Any):
        """Sets the server/service/manager to a failure state."""
        self._state = ServiceState.FAILED
        self._failure = failure
        logging.error(theme.error(f"Server failed: {failure}"))
        self.stop()

    def stop(self):
        if self.api is not None:
            try:
                logging.info(theme.primary("Stopping service"))
                self.api.stop()
                self.api = None
            except Exception as e:
                logging.warning(theme.warning(f"Failed to stop service: {e}"))

        if self.device is not None:
            try:
                logging.info(theme.primary("Stopping server"))
                self.device.stop()
                self.device = None
            except Exception as e:
                logging.warning(theme.warning(f"Failed to stop server: {e}"))

        try:
            self._release_file_lock()
        except Exception as e:
            logging.error(theme.error(f"Failed to release lock file: {e}"))
            self._state = ServiceState.FAILED
            self._failure = e
            return

        logging.info(theme.primary("Server stopped successfully"))
        if self._state is not ServiceState.FAILED:
            self._state = ServiceState.STOPPED

    def _acquire_lock_file(self):
        """
        Ensures only a single instance of the application runs unless dev_mode is enabled.

        Args:
            dev_mode: If True, allows multiple instances to run simultaneously.

        Returns:
            bool: True if this is the only instance or dev_mode is enabled, exits otherwise.
        """
        try:
            logging.debug("Acquired lock file")
            self._lock_file = open(FILE_LOCK, "w", encoding="UTF-8")
            platform.lock_file(self._lock_file)
            return True

        except (IOError, OSError):
            logging.error(theme.error("Another instance of the application is already running."))
            if self._lock_file:
                self._lock_file.close()
            return False

    def _release_file_lock(self):
        """Release the lock file and remove it when the application exits."""
        if self._lock_file is None:
            return

        try:
            logging.debug("Unlocking lock file")
            platform.unlock_file(self._lock_file)
            self._lock_file.close()
            os.remove(FILE_LOCK)
            self._lock_file = None
        except Exception as e:
            logging.warning("Error cleaning up lock file %s: %s", FILE_LOCK, e)


class DeviceService:
    """Server class to manage the server instance."""

    def __init__(self, device_id: str):
        self.device_id = device_id
        self._server = None
        self._status = ServiceState.STOPPED
        self._failure = None

    @property
    def status(self) -> ServiceState:
        """Returns the current status of the server."""
        return self._status

    @property
    def failure(self) -> Any:
        """Returns the failure reason if the server is in a failed state."""
        return self._failure

    def start(self):
        # TODO - Implement server start logic
        self._status = ServiceState.OK

    def stop(self):
        # TODO - Implement server stop logic
        pass


@rpyc.service
class ApiService(rpyc.Service):
    def __init__(self, server: DeviceService):
        self._server = server
        self._device_id = server.device_id
        self._state = ServiceState.STOPPED
        super().__init__()

    def on_connect(self, conn):
        logging.info("Connection established")

    def on_disconnect(self, conn):
        logging.info("Connection closed")

    @rpyc.exposed
    def get_answer(self):
        return 42

    @property
    def state(self):
        """Returns the current state of the server."""
        return self._state

    def start(self):
        self._state = ServiceState.OK

    def stop(self):
        self._state = ServiceState.STOPPED


class ServiceState(Enum):
    """Enum representing the possible states of a server/service/manager."""

    STOPPED = "stopped" # stopped, not running (ready to be started)
    OK = "ok" # running, ready to accept connections/requests
    BUSY = "busy" # busy and unable to accept connections/requests
    FAILED = "failed" # failed (during operation) and unable to recover, unable to accept connections/requests

    def is_running_state(self) -> bool:
        """Check if the state is a running state."""
        return self in [self.OK, self.BUSY]
