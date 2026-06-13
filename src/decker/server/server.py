"""Manages the Decker RPyC server subprocess."""

import logging
import multiprocessing
import signal
from typing import Any

from rpyc.utils.server import ThreadPoolServer

from decker.server.service import DeckerService


class ServerProcess:
    """Spawns and owns the RPyC server subprocess."""

    def __init__(self, port: int = 18861, startup_wait: float = 5.0) -> None:
        """Initialize the server process."""
        self.port = port
        self._startup_wait = startup_wait
        self._process: multiprocessing.Process | None = None
        self._server: ThreadPoolServer | None = None

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

    def _signal_handler(self, signum: int, _: Any) -> None:
        """Graceful shutdown: close the RPyC server."""
        logging.info("Received signal %d, shutting down", signum)
        if self._server:
            self._server.close()

    def _run_server(self) -> None:
        """Entry point for the server subprocess. Runs RPyC in the main thread."""
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        self._server = ThreadPoolServer(
            DeckerService,
            port=self.port,
            protocol_config={"allow_public_attrs": True},
        )
        DeckerService.configure_server(self._server)
        logging.info("RPyC server listening on port %d", self.port)
        self._server.start()  # blocks until close() is called
        # Normal return → subprocess exits with code 0 (intentional stop)
