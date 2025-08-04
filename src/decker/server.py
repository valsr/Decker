"""Server and daemon management for the Decker application."""

from copy import deepcopy
import logging
import multiprocessing
import signal
import time
from typing import Any

import rpyc
import rpyc.utils.factory
import rpyc.core.protocol
from rpyc.core.service import Service
from rpyc.utils.server import ThreadPoolServer

from decker.Application import Application
from decker.api import API


class DeckerService(Service):
    """RPyC service for the Decker application providing health monitoring capabilities."""

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
                # Run the application in a separate thread to avoid blocking
                self._application.run_threaded()
                logging.info("Decker application started successfully")
                return True
            else:
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
            else:
                logging.warning("No application is currently running")
                return False
        except Exception as e:
            logging.error("Failed to stop application: %s", e)
            return False

    @rpyc.utils.exposed
    def heartbeat(self) -> dict[str, Any]:
        """
        Handle heartbeat requests for health monitoring.

        Returns:
            dict[str, Any]: A dictionary containing health status information.
        """
        self._last_heartbeat = time.time()
        status = {
            "status": "healthy",
            "timestamp": self._last_heartbeat,
            "application_running": self._application is not None,
        }
        # TODO derive status from status method
        return status

    @rpyc.utils.exposed
    def status(self) -> dict[str, Any]:
        """
        Get the current status of the service and application.

        Returns:
            dict[str, Any]: A dictionary containing detailed status information.
        """
        return {
            "service_status": "running",
            "application_running": self._application is not None,
            "last_heartbeat": self._last_heartbeat,
        }


class ServerProcess:
    """Manages the RPyC server process."""

    def __init__(self, port: int = 18861, startup_wait: float = 5.0):
        """
        Initialize the server process.

        Args:
            port (int): The port to bind the RPyC server to.
        """
        self.port = port
        self.process: multiprocessing.Process | None = None
        self._server: ThreadPoolServer | None = None
        self._startup_wait: float = startup_wait  # Time to wait for server startup

    def start(self) -> bool:
        """
        Start the RPyC server process.

        Returns:
            bool: True if the server was started successfully, False otherwise.
        """
        if self.process is not None and self.process.is_alive():
            logging.warning("Server process is already running")
            return False

        try:
            logging.info("Starting RPyC server on port %d", self.port)
            self.process = multiprocessing.Process(target=self._run_server, daemon=False)
            self.process.start()

            # Give the server a moment to start
            time.sleep(self._startup_wait)

            if self.process.is_alive():
                if not API.request("start"):
                    logging.error("Failed to start Decker service application")
                    self.stop() # Clean up if failed to start
                    return False
                return True
            else:
                logging.error("Failed to start RPyC server")
                return False
        except Exception as e:
            logging.error("Failed to start server process: %s", e)
            return False

    def stop(self) -> bool:
        """
        Stop the RPyC server process.

        Returns:
            bool: True if the server was stopped successfully, False otherwise.
        """
        if self.process is None:
            logging.warning("No server process to stop")
            return False

        try:
            logging.info("Stopping RPyC server")
            self.process.terminate()
            self.process.join(timeout=5)

            if self.process.is_alive():
                logging.warning("Server process did not terminate gracefully, forcing shutdown")
                self.process.kill()
                self.process.join()

            logging.info("RPyC server stopped successfully")
            self.process = None
            return True
        except Exception as e:
            logging.error("Failed to stop server process: %s", e)
            return False

    @property
    def is_running(self) -> bool:
        """
        Check if the server process is running.

        Returns:
            bool: True if the server process is alive, False otherwise.
        """
        return self.process is not None and self.process.is_alive()

    @property
    def pid(self) -> int | None:
        """
        Get the process ID of the server.

        Returns:
            int | None: The PID if the server is running, None otherwise.
        """
        if self.process and self.process.is_alive():
            return self.process.pid
        return None

    def _server_signal_handler(self, signum: int, _: Any):
        """Handle signals for graceful shutdown."""
        if not self._server:
            return

        logging.info("Received signal %d, shutting down server", signum)
        API.request("stop")
        self._server.close()

    def _run_server(self):
        """Run the RPyC server in the subprocess."""
        try:
            signal.signal(signal.SIGTERM, self._server_signal_handler)
            signal.signal(signal.SIGINT, self._server_signal_handler)

            # Create and start the server
            self._server = ThreadPoolServer(
                DeckerService(),
                port=self.port,
                protocol_config={"allow_public_attrs": True}
            )

            logging.info("RPyC server listening on port %d", self.port)
            self._server.start()
        except Exception as e:
            logging.error("Server process encountered an error: %s", e)


class ServerManager:
    """Manages the server with health monitoring and auto-restart capabilities."""

    def __init__(self, port: int = 18861, min_monitor_interval: float = 5.0, max_failed_heartbeats: int = 2):
        """
        Initialize the server manager.

        Args:
            port (int): The port for the RPyC server.
            min_monitor_interval (float): Minimum time in seconds between health checks.
            max_failed_heartbeats (int): Maximum consecutive failed heartbeats before restart.
        """
        self.port = port
        self.monitor_interval = min_monitor_interval
        self.max_failed_heartbeats = max_failed_heartbeats
        self.server_process = ServerProcess(port)
        self._failed_heartbeats = 0

    def start(self) -> bool:
        """
        Start the server with health monitoring.

        Returns:
            bool: True if the server was started successfully, False otherwise.
        """
        logging.info("Starting Decker server")

        if not self.server_process.start():
            logging.error("Failed to start server process")
            return False

        try:
            self._monitor()
        except KeyboardInterrupt:
            logging.info("Received interrupt signal, shutting down daemon")
        finally:
            self.stop()

        return True

    def stop(self) -> bool:
        """
        Stop the server.

        Returns:
            bool: True if the server was stopped successfully, False otherwise.
        """
        logging.info("Stopping Decker server")
        return self.server_process.stop()

    def _monitor(self):
        """Monitor the health of the server process and restart if necessary."""
        logging.info("Starting health monitoring (heartbeat interval: %.1fs, max failures: %d)",
                    self.monitor_interval, self.max_failed_heartbeats)

        while True:
            try:
                # Check if server process is still alive
                if not self.server_process.is_running:
                    logging.warning("Server process died, restarting...")
                    self._restart_server()
                    continue

                # Perform heartbeat check (application status)
                self._check_heartbeat()

                # TODO: Perform soft/hard memory monitoring

                # Sleep for the specified interval before the next check
                time.sleep(self.monitor_interval)

            except Exception as e:
                logging.error("Error during health monitoring: %s", e)
                time.sleep(self.monitor_interval)

    def _check_heartbeat(self):
        """
        Check server heartbeat.
        """
        try:
            logging.debug("Sending heartbeat to server on port %d", self.port)
            response = API.request("heartbeat")
            if response is None:
                logging.warning("No response from server, assuming unhealthy")
                self._failed_heartbeats += 1
                return

            if response.get("status") != "healthy":
                logging.warning("Unhealthy server response: %s", response)
                self._failed_heartbeats += 1
            # if response.get("application_status") != "running":
            #     logging.warning("Application is not running, restarting server")
            #     self._restart_server()
        except Exception as e:
            logging.warning("Heartbeat failed: %s", e)
            self._failed_heartbeats += 1

        if self._failed_heartbeats >= self.max_failed_heartbeats:
            logging.error("Maximum failed heartbeats reached, restarting server")
            self._restart_server()

    def _restart_server(self) -> bool:
        """
        Restart the server process.

        Returns:
            bool: True if restart was successful, False otherwise.
        """
        logging.info("Restarting server process")

        # Stop the current server
        self.server_process.stop()

        # Reset failed heartbeat counter
        self._failed_heartbeats = 0

        # Start a new server
        if self.server_process.start():
            logging.info("Server restarted successfully")
            return True
        else:
            logging.error("Failed to restart server")
            return False

    def status(self) -> dict[str, Any]:
        """
        Get the current status of the server.

        Returns:
            dict[str, Any]: A dictionary containing server status information.
        """
        return {
            "pid": self.server_process.pid,
            "failed_heartbeats": self._failed_heartbeats,
            "max_failed_heartbeats": self.max_failed_heartbeats,
            "heartbeat_interval": self.monitor_interval,
            "port": self.port,
        }
