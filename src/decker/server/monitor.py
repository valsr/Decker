"""Server monitor — starts, supervises, and auto-restarts the Decker server subprocess."""

import logging
import math
import random
import time
from dataclasses import dataclass

from decker.common import config
from decker.common.api import API
from decker.common.context import ServerAppContext
from decker.common.model import DeviceHardwareInfo
from decker.server.server import ServerProcess
from decker.server.service import DeckerServiceStatus, DeckerStatusEnum


def _read_rss_bytes(pid: int) -> int | None:
    """Read a process's RSS memory from /proc/<pid>/status (Linux only).

    Returns:
        int | None: RSS in bytes, or None if the file could not be read.
    """
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    # "VmRSS:   123456 kB"
                    return int(line.split()[1]) * 1024
    except (FileNotFoundError, PermissionError, ValueError, OSError) as e:
        logging.warning("Could not read RSS for pid %d - %s", pid, type(e).__name__)
    return None


@dataclass
class ServerStatus:
    """Structured status information about the server process."""

    pid: int | None
    failed_heartbeats: int
    max_failed_heartbeats: int
    monitor_interval: float
    memory_limit_bytes: int


class ServerMonitor:
    """Monitors the server subprocess and restarts it when it becomes unhealthy."""

    def __init__(self, context: ServerAppContext) -> None:
        """Initialize the server monitor from configuration."""
        port = config.get_as("server.port", int)
        startup_wait = config.get_as("server.startup_wait", float)
        self._server = ServerProcess(port, startup_wait, context)
        self._interval: float = config.get_as("server.health_check_interval", float)
        self._max_failed_heartbeats: int = config.get_as("server.max_failed_heartbeats", int)
        self._memory_limit: int = config.get_as("server.memory_limit", int)
        self._failed_heartbeats: int = 0
        self._stop_requested: bool = False
        self._context = context

    def start(self) -> bool:
        """
        Start the server then enter the monitoring loop.

        Returns:
            bool: True after a clean shutdown, False if the server could not be started.
        """
        logging.info("Starting Decker server monitor")

        if not self._server.start():
            logging.error("Failed to start server process")
            return False

        try:
            self._monitor()
        except KeyboardInterrupt:
            logging.info("Received interrupt, shutting down monitor")
        finally:
            self.stop()

        return True

    def stop(self) -> bool:
        """Stop the server subprocess."""
        logging.info("Stopping Decker server monitor")
        return self._server.stop()

    def status(self) -> ServerStatus:
        """Return current monitor status."""
        return ServerStatus(
            pid=self._server.pid if self._server else None,
            failed_heartbeats=self._failed_heartbeats,
            max_failed_heartbeats=self._max_failed_heartbeats,
            monitor_interval=self._interval,
            memory_limit_bytes=self._memory_limit,
        )

    # ------------------------------------------------------------------
    # Internal monitoring loop
    # ------------------------------------------------------------------

    def _monitor(self) -> None:
        """Main health-check loop. Runs until interrupted or a clean server stop."""
        logging.info(
            "Monitor active (interval=%.1fs, max_heartbeat_fails=%d, memory_limit=%.0f MiB)",
            self._interval,
            self._max_failed_heartbeats,
            self._memory_limit / (1024 * 1024),
        )
        while True:
            try:
                self._check_once()
            except Exception as e:
                logging.error("Unexpected error in monitor loop: %s", e)
            if self._stop_requested:
                break
            time.sleep(self._interval)

    def _check_once(self) -> None:
        """Run a single round of health checks and restart if needed."""
        if not self._server.is_running:
            if self._server.exited_cleanly:
                logging.info("Server stopped cleanly, shutting down monitor")
                self._stop_requested = True
                return
            logging.warning("Server process died unexpectedly, restarting")
            self._restart_server()
            return

        if not self._heartbeat_ok():
            self._restart_server()
            return

        if not self._memory_ok():
            self._restart_server()

    def _heartbeat_ok(self) -> bool:
        """Send a heartbeat and return True while the server is still within its failure budget."""
        try:
            response = API.request_as(DeckerServiceStatus, "heartbeat")
            logging.debug("Heartbeat response: %s", response)
            if response is not None and response.service_status == DeckerStatusEnum.HEALTHY:
                self._failed_heartbeats = 0
                logging.debug("Heartbeat OK")
                # TODO: DEMO-ONLY: Remove this log and return False if the service status is unhealthy, to test auto-restart.
                self._do_demo()
                return True
        except Exception as e:
            logging.warning("Heartbeat failed: %s", e)

        self._failed_heartbeats += 1
        logging.warning("Failed heartbeats: %d/%d", self._failed_heartbeats, self._max_failed_heartbeats)
        return self._failed_heartbeats < self._max_failed_heartbeats

    def _do_demo(self) -> None:
        """DEMO-ONLY:"""
        try:
            logging.info("DEMO: Send a draw command to a random button")
            # first find the device IDs so we can target a real button (instead of "random"), but ignore any errors since this is just a demo
            devices: list[DeviceHardwareInfo] = API.request_as(
                list[DeviceHardwareInfo], "devices_list"
            )  # ignore errors and response since this is just a demo

            if not devices:
                logging.warning("DEMO: No devices found, skipping draw command")
                return

            device = devices[0]

            if not device.id:
                logging.warning("DEMO: No device_id found in first device, skipping draw command")
                return

            # Generate a simple image (red square) and send it to the first key of the first device, ignoring any errors since this is just a demo
            from PIL import Image

            button = random.randint(0, device.num_keys)
            button_def = device.keys[button]
            img = Image.new("RGB", (button_def.pixel_width, button_def.pixel_height), (255, 0, 0))
            img_bytes = img.tobytes()
            logging.debug("Button dimensions: %d x %d", button_def.pixel_width, button_def.pixel_height)
            API.request("set_image", device.id, button, img_bytes)
            logging.info("DEMO: Draw command sent to device %s key %s", device.id, button)
        except Exception as e:
            logging.warning("DEMO command failed: %s", e)

    def _memory_ok(self) -> bool:
        """Return False if the server's RSS exceeds the configured limit."""
        pid = self._server.pid
        if pid is None:
            return True

        rss = _read_rss_bytes(pid)
        if rss is None:
            return True

        rss_mib = rss / (1024 * 1024)
        limit_mib = self._memory_limit / (1024 * 1024)
        logging.debug("Server RSS: %.1f MiB (limit %.0f MiB)", rss_mib, limit_mib)

        if rss > self._memory_limit:
            logging.error("Server RSS %.1f MiB exceeds limit %.0f MiB, restarting", rss_mib, limit_mib)
            return False
        return True

    def _restart_server(self) -> None:
        """Stop the server, reset state, and start it again."""
        logging.info("Restarting server process")
        self._server.stop()
        self._failed_heartbeats = 0

        if not self._server.start():
            logging.error("Failed to restart server — will retry on next cycle")
