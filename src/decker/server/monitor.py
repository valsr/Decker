"""Server monitor — starts, supervises, and auto-restarts the Decker server subprocess."""

import logging
import time
from typing import Any

from decker.common import config
from decker.common.api import API
from decker.server.server import ServerProcess


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
    except (FileNotFoundError, PermissionError, ValueError, OSError):
        pass
    return None


class ServerMonitor:
    """Monitors the server subprocess and restarts it when it becomes unhealthy."""

    def __init__(self) -> None:
        """Initialize the server monitor from configuration."""
        port = config.get_as("server.port", int)
        startup_wait = config.get_as("server.startup_wait", float)
        self._server = ServerProcess(port, startup_wait)
        self._interval: float = config.get_as("server.health_check_interval", float)
        self._max_failed_heartbeats: int = config.get_as("server.max_failed_heartbeats", int)
        self._memory_limit: int = config.get_as("server.memory_limit", int)
        self._failed_heartbeats: int = 0
        self._stop_requested: bool = False

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

    def status(self) -> dict[str, Any]:
        """Return current monitor status."""
        return {
            "pid": self._server.pid,
            "failed_heartbeats": self._failed_heartbeats,
            "max_failed_heartbeats": self._max_failed_heartbeats,
            "monitor_interval": self._interval,
            "memory_limit_bytes": self._memory_limit,
        }

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
            response = API.request("heartbeat")
            if response is not None and response.get("status") == "healthy":
                self._failed_heartbeats = 0
                logging.debug("Heartbeat OK")
                return True
            logging.warning("Unexpected heartbeat response: %s", response)
        except Exception as e:
            logging.warning("Heartbeat failed: %s", e)

        self._failed_heartbeats += 1
        logging.warning("Failed heartbeats: %d/%d", self._failed_heartbeats, self._max_failed_heartbeats)
        return self._failed_heartbeats < self._max_failed_heartbeats

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
