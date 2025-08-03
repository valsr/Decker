"""Server and daemon management for the Decker application."""

import logging
import multiprocessing
import signal
import time
from typing import Any

import rpyc
import rpyc.utils.factory
import rpyc.core.protocol
from rpyc.core.service import Service
from rpyc.utils.server import ThreadedServer


from decker.Application import Application


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

    def exposed_start_application(self) -> bool:
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
    def stop_application(self) -> bool:
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
        logging.debug("Heartbeat received: %s", status)
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
            "uptime": time.time() - self._last_heartbeat,
        }


class ServerProcess:
    """Manages the RPyC server process."""

    def __init__(self, port: int = 18861):
        """
        Initialize the server process.

        Args:
            port (int): The port to bind the RPyC server to.
        """
        self.port = port
        self.process: multiprocessing.Process | None = None
        self._server: ThreadedServer | None = None

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
            time.sleep(1)

            if self.process.is_alive():
                logging.info("RPyC server started successfully with PID %d", self.process.pid)
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

    def is_running(self) -> bool:
        """
        Check if the server process is running.

        Returns:
            bool: True if the server process is alive, False otherwise.
        """
        return self.process is not None and self.process.is_alive()

    def get_pid(self) -> int | None:
        """
        Get the process ID of the server.

        Returns:
            int | None: The PID if the server is running, None otherwise.
        """
        if self.process and self.process.is_alive():
            return self.process.pid
        return None

    def _run_server(self):
        """Run the RPyC server in the subprocess."""
        try:
            # Set up signal handlers for graceful shutdown
            def signal_handler(signum: int, _frame: Any):
                logging.info("Received signal %d, shutting down server", signum)
                if self._server:
                    self._server.close()

            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGINT, signal_handler)

            # Create and start the server
            self._server = ThreadedServer(
                DeckerService(),
                port=self.port,
                protocol_config={"allow_public_attrs": True}
            )

            logging.info("RPyC server listening on port %d", self.port)
            self._server.start()
        except Exception as e:
            logging.error("Server process encountered an error: %s", e)


class DaemonManager:
    """Manages the daemon mode with health monitoring and auto-restart capabilities."""

    def __init__(self, port: int = 18861, heartbeat_interval: float = 2.0, max_failed_heartbeats: int = 2):
        """
        Initialize the daemon manager.

        Args:
            port (int): The port for the RPyC server.
            heartbeat_interval (float): Time in seconds between heartbeats.
            max_failed_heartbeats (int): Maximum consecutive failed heartbeats before restart.
        """
        self.port = port
        self.heartbeat_interval = heartbeat_interval
        self.max_failed_heartbeats = max_failed_heartbeats
        self.server_process = ServerProcess(port)
        self._running = False
        self._failed_heartbeats = 0

    def start_daemon(self) -> bool:
        """
        Start the daemon with health monitoring.

        Returns:
            bool: True if the daemon was started successfully, False otherwise.
        """
        logging.info("Starting Decker daemon")

        if not self.server_process.start():
            logging.error("Failed to start server process")
            return False

        self._running = True

        try:
            self._monitor_health()
        except KeyboardInterrupt:
            logging.info("Received interrupt signal, shutting down daemon")
        finally:
            self._shutdown()

        return True

    def stop_daemon(self) -> bool:
        """
        Stop the daemon.

        Returns:
            bool: True if the daemon was stopped successfully, False otherwise.
        """
        logging.info("Stopping Decker daemon")
        self._running = False
        return self.server_process.stop()

    def _monitor_health(self):
        """Monitor the health of the server process and restart if necessary."""
        logging.info("Starting health monitoring (heartbeat interval: %.1fs, max failures: %d)",
                    self.heartbeat_interval, self.max_failed_heartbeats)

        while self._running:
            try:
                # Check if server process is still alive
                if not self.server_process.is_running():
                    logging.warning("Server process died, restarting...")
                    self._restart_server()
                    continue

                # Perform heartbeat check
                if self._check_heartbeat():
                    self._failed_heartbeats = 0
                else:
                    self._failed_heartbeats += 1
                    logging.warning("Heartbeat failed (%d/%d)",
                                  self._failed_heartbeats, self.max_failed_heartbeats)

                    if self._failed_heartbeats >= self.max_failed_heartbeats:
                        logging.error("Maximum failed heartbeats reached, restarting server")
                        self._restart_server()

                time.sleep(self.heartbeat_interval)

            except Exception as e:
                logging.error("Error during health monitoring: %s", e)
                time.sleep(self.heartbeat_interval)

    def _check_heartbeat(self) -> bool:
        """
        Check the heartbeat of the server.

        Returns:
            bool: True if heartbeat is successful, False otherwise.
        """
        try:
            conn: rpyc.core.protocol.Connection = rpyc.utils.factory.connect("localhost", self.port)
            response = conn.root.heartbeat()
            conn.close()

            logging.debug("Heartbeat successful: %s", response)
            return True
        except Exception as e:
            logging.warning("Heartbeat failed: %s", e)
            return False

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

    def _shutdown(self):
        """Perform cleanup during shutdown."""
        logging.info("Shutting down daemon")
        self._running = False
        self.server_process.stop()

    def get_status(self) -> dict[str, Any]:
        """
        Get the current status of the daemon.

        Returns:
            dict[str, Any]: A dictionary containing daemon status information.
        """
        return {
            "daemon_running": self._running,
            "server_running": self.server_process.is_running(),
            "server_pid": self.server_process.get_pid(),
            "failed_heartbeats": self._failed_heartbeats,
            "max_failed_heartbeats": self.max_failed_heartbeats,
            "heartbeat_interval": self.heartbeat_interval,
            "port": self.port,
        }
