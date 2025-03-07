import atexit
import logging
import os
import signal
import sys
import tempfile
import threading
import time
from typing import Any

from decker_server import theme
from decker_server.server import Server


class InstanceManager:
    """
    Utility class to ensure only one instance of the application runs at a time.

    This prevents multiple instances from interfering with each other by using
    file locking mechanisms that work across different platforms.
    """

    def __init__(self, dev_mode: bool = False):
        self.lock_file: Any = None
        self.lock_file_path = os.path.join(tempfile.gettempdir(), "decker_server.lock")
        self.is_dev_mode = dev_mode
        self.server: Server | None = None

    def start_server(self):
        if not self._get_server_lock():
            logging.error(theme.error("Failed to acquire server lock."))
            return

        logging.info(theme.primary("Starting server"))
        signal.signal(signal.SIGINT, self.handle_interrupt)

        self.server = Server()
        self.server.start()
        forever = threading.Event()
        forever.wait()

    def handle_interrupt(self, signal, frame):
        if self.server is not None:
            self.server.stop()
            self.server.join(timeout=5)
            if self.server.is_alive():
                logging.warning(theme.warning("Forcing thread termination"))
                self.server._stop()  # type: ignore
        time.sleep(1)
        logging.info(theme.primary("Exiting"))
        exit(0)

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
            self.lock_file = open(self.lock_file_path, "w")
            self._lock()

            # Register cleanup to ensure lock file is removed on exit
            atexit.register(self._cleanup_lock)
            return True

        except (IOError, OSError):
            print("Another instance of the application is already running.")
            print("Use --dev flag to allow multiple instances for development.")
            sys.exit(1)

    def _lock(self):
        """Unix-specific file locking implementation."""
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.lock(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            self.lock_file.close()
            raise

    def _cleanup_lock(self):
        """Release the lock file and remove it when the application exits."""
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.lock(self.lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.lock_file, fcntl.LOCK_UN)

            self.lock_file.close()
            os.remove(self.lock_file_path)
        except:
            pass  # Ignore errors during cleanup
