"""RPyC service definition for the Decker server."""

import inspect
import logging
import threading
import time
from typing import Any

import rpyc
from rpyc.core.service import Service
from rpyc.utils.server import ThreadPoolServer

from decker.server.devices import list_devices


class DeckerService(Service):
    """RPyC service exposed to clients for controlling the Decker application."""

    _rpyc_server: ThreadPoolServer | None = None

    @classmethod
    def configure_server(cls, server: ThreadPoolServer) -> None:
        """Bind the shared ThreadPoolServer instance before clients connect."""
        cls._rpyc_server = server

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
            time.sleep(0.1)  # let the RPC response be delivered first
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
        return {
            "status": "healthy",
            "timestamp": self._last_heartbeat,
        }

    @rpyc.utils.exposed
    def status(self) -> dict[str, Any]:
        """
        Get detailed service status.

        Returns:
            dict[str, Any]: Detailed status information.
        """
        return {
            "service_status": "running",
            "last_heartbeat": self._last_heartbeat,
        }

    @rpyc.utils.exposed
    def devices_list(self) -> list[dict[str, Any]]:
        """
        List all connected Stream Deck devices.

        Returns:
            list[dict[str, Any]]: One entry per device with id, type, keys, serial, vendor_id, product_id.
        """
        return list_devices()

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
