"""InstanceManager for Decker Server."""

import atexit
import logging
import os
import signal
import sys
import tempfile
import threading
import time
from typing import Any

from decker_server import platform, theme
from decker_server.server import Server


class InstanceManager:
    """
    InstanceManager for Decker Server.

    This class manages the server instance lifecycle and ensures that only one
    instance of the application runs at a time, preventing multiple instances from
    interfering with each other by using file locking mechanisms that work across
    different platforms.

    Attributes:
        lock_file (Any): File handle for the lock file.
        lock_file_path (str): Path to the lock file in the temporary directory.
        is_dev_mode (bool): Flag indicating whether development mode is enabled.
        server (Server | None): Reference to the server instance when running.

    Methods:
        start_server(): Acquires a lock and starts the server if successful.
        stop_server(): Stops the running server and cleans up resources.

    Example:
        ```
        manager = InstanceManager(dev_mode=False)
        manager.start_server()  # Starts server if no other instance is running
        # Later...
        manager.stop_server()  # Gracefully shutdown
        ```
    """

    def __init__(self, dev_mode: bool = False):
        self.lock_file: Any = None
        self.lock_file_path = os.path.join(tempfile.gettempdir(), "decker_server.lock")
        self.is_dev_mode = dev_mode
        self.server: Server | None = None

    def start_server(self):
        """Starts the server instance if no other instance is running."""
        if not self._get_server_lock():
            logging.error(theme.error("Failed to acquire server lock."))
            return

        logging.info(theme.primary("Starting server"))
        signal.signal(signal.SIGINT, self._handle_interrupt)

        self.server = Server()
        self.server.start()
        forever = threading.Event()
        forever.wait()

    def stop_server(self):
        """Stops the running server instance and cleans up resources."""
        if self.server is not None:
            logging.info(theme.primary("Stopping server"))
            self.server.stop()
            self.server.join(timeout=5)
            if self.server.is_alive():
                logging.warning(theme.warning("Forcing thread termination"))
                self.server._stop()  # type: ignore [attr-defined] # pylint: disable=protected-access
            self.server = None
        logging.info(theme.primary("Server stopped"))
        self._cleanup_lock()

    def _handle_interrupt(self, _, __):
        self.stop_server()
        time.sleep(1)
        logging.info(theme.primary("Exiting"))
        sys.exit(0)

    def _get_server_lock(self):
        """
        Ensures only a single instance of the application runs unless dev_mode is enabled.

        Args:
            dev_mode: If True, allows multiple instances to run simultaneously.

        Returns:
            bool: True if this is the only instance or dev_mode is enabled, exits otherwise.
        """
        if self.is_dev_mode:
            return True  # In dev mode, allow multiple instances

        try:
            self.lock_file = open(self.lock_file_path, "w", encoding="UTF-8")
            platform.lock_file(self.lock_file)
            logging.debug("Acquired lock file")

            # Register cleanup to ensure lock file is removed on exit
            atexit.register(self._cleanup_lock)
            return True

        except (IOError, OSError):
            print("Another instance of the application is already running.")
            print("Use --dev flag to allow multiple instances for development.")
            if self.lock_file:
                self.lock_file.close()
            return False

    def _cleanup_lock(self):
        """Release the lock file and remove it when the application exits."""
        if self.lock_file is None:
            return

        try:
            platform.unlock_file(self.lock_file)
            self.lock_file.close()
            logging.debug("Lock file removed")
            os.remove(self.lock_file_path)
        except Exception as e:
            logging.warning("Error cleaning up lock file: %s", e)
