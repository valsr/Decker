"""RPyC service definition for the Decker server."""

import inspect
import logging
import time
from typing import Any

import rpyc
from rpyc.core.service import Service

from decker.server.application import Application


class DeckerService(Service):
    """RPyC service exposed to clients for controlling the Decker application."""

    def __init__(self):
        """Initialize the Decker service."""
        super().__init__()
        self._application: Application | None = None
        self._last_heartbeat = time.time()

    def on_connect(self, conn: Any):
        """Handle client connection."""
        logging.info("Client connected to Decker service")

    def on_disconnect(self, conn: Any):
        """Handle client disconnection."""
        logging.info("Client disconnected from Decker service")

    @rpyc.utils.exposed
    def start(self) -> bool:
        """
        Start the Decker application.

        Returns:
            bool: True if the application was started successfully, False otherwise.
        """
        try:
            if self._application is None:
                logging.info("Starting Decker application")
                self._application = Application()
                self._application.run_threaded()
                logging.info("Decker application started successfully")
                return True
            logging.warning("Application is already running")
            return False
        except Exception as e:
            logging.error("Failed to start application: %s", e)
            return False

    @rpyc.utils.exposed
    def stop(self) -> bool:
        """
        Stop the Decker application.

        Returns:
            bool: True if the application was stopped successfully, False otherwise.
        """
        try:
            if self._application is not None:
                logging.info("Stopping Decker application")
                self._application.stop()
                self._application = None
                logging.info("Decker application stopped successfully")
                return True
            logging.warning("No application is currently running")
            return False
        except Exception as e:
            logging.error("Failed to stop application: %s", e)
            return False

    @rpyc.utils.exposed
    def heartbeat(self) -> dict[str, Any]:
        """
        Respond to a health-check ping from the monitor.

        Returns:
            dict[str, Any]: Health status information.
        """
        self._last_heartbeat = time.time()
        return {
            "status": "healthy",
            "timestamp": self._last_heartbeat,
            "application_running": self._application is not None,
        }

    @rpyc.utils.exposed
    def status(self) -> dict[str, Any]:
        """
        Get detailed service and application status.

        Returns:
            dict[str, Any]: Detailed status information.
        """
        return {
            "service_status": "running",
            "application_running": self._application is not None,
            "last_heartbeat": self._last_heartbeat,
        }

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
