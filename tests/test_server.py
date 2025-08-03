"""Tests for the server and daemon functionality."""

import multiprocessing
import time
import unittest
from unittest.mock import MagicMock, patch

from decker.server import DaemonManager, DeckerService, ServerProcess


class TestDeckerService(unittest.TestCase):
    """Test cases for DeckerService."""

    def setUp(self):
        """Set up test fixtures."""
        self.service = DeckerService()

    def test_init(self):
        """Test service initialization."""
        self.assertIsNone(self.service._application)
        self.assertIsInstance(self.service._last_heartbeat, float)

    def test_heartbeat(self):
        """Test heartbeat functionality."""
        initial_time = self.service._last_heartbeat
        time.sleep(0.1)  # Small delay to ensure time difference

        response = self.service.heartbeat()

        self.assertIsInstance(response, dict)
        self.assertEqual(response["status"], "healthy")
        self.assertGreater(response["timestamp"], initial_time)
        self.assertFalse(response["application_running"])

    @patch("decker.server.Application")
    def test_start_application_success(self, mock_application):
        """Test successful application start."""
        mock_app_instance = MagicMock()
        mock_application.return_value = mock_app_instance

        result = self.service.exposed_start_application()

        self.assertTrue(result)
        mock_application.assert_called_once()
        mock_app_instance.run_threaded.assert_called_once()
        self.assertIsNotNone(self.service._application)

    def test_start_application_already_running(self):
        """Test starting application when already running."""
        # Simulate application already running
        self.service._application = MagicMock()

        result = self.service.exposed_start_application()

        self.assertFalse(result)

    @patch("decker.server.Application")
    def test_stop_application_success(self, mock_application):
        """Test successful application stop."""
        mock_app_instance = MagicMock()
        self.service._application = mock_app_instance

        result = self.service.stop_application()

        self.assertTrue(result)
        mock_app_instance.stop.assert_called_once()
        self.assertIsNone(self.service._application)

    def test_stop_application_not_running(self):
        """Test stopping application when not running."""
        result = self.service.stop_application()
        self.assertFalse(result)

    def test_get_status(self):
        """Test get status functionality."""
        status = self.service.status()

        self.assertIsInstance(status, dict)
        self.assertEqual(status["service_status"], "running")
        self.assertFalse(status["application_running"])
        self.assertIn("last_heartbeat", status)
        self.assertIn("uptime", status)


class TestServerProcess(unittest.TestCase):
    """Test cases for ServerProcess."""

    def setUp(self):
        """Set up test fixtures."""
        self.server_process = ServerProcess(port=18862)  # Use different port for testing

    def tearDown(self):
        """Clean up after tests."""
        if self.server_process.is_running():
            self.server_process.stop()

    def test_init(self):
        """Test server process initialization."""
        self.assertEqual(self.server_process.port, 18862)
        self.assertIsNone(self.server_process.process)

    def test_start_stop_server(self):
        """Test starting and stopping the server process."""
        # Start server
        result = self.server_process.start()
        self.assertTrue(result)
        self.assertTrue(self.server_process.is_running())
        self.assertIsNotNone(self.server_process.get_pid())

        # Stop server
        result = self.server_process.stop()
        self.assertTrue(result)
        self.assertFalse(self.server_process.is_running())
        self.assertIsNone(self.server_process.get_pid())

    def test_start_already_running(self):
        """Test starting server when already running."""
        self.server_process.start()

        # Try to start again
        result = self.server_process.start()
        self.assertFalse(result)

        self.server_process.stop()

    def test_stop_not_running(self):
        """Test stopping server when not running."""
        result = self.server_process.stop()
        self.assertFalse(result)


class TestDaemonManager(unittest.TestCase):
    """Test cases for DaemonManager."""

    def setUp(self):
        """Set up test fixtures."""
        self.daemon_manager = DaemonManager(
            port=18863,  # Use different port for testing
            heartbeat_interval=0.5,  # Faster for testing
            max_failed_heartbeats=2
        )

    def tearDown(self):
        """Clean up after tests."""
        if self.daemon_manager._running:
            self.daemon_manager.stop_daemon()

    def test_init(self):
        """Test daemon manager initialization."""
        self.assertEqual(self.daemon_manager.port, 18863)
        self.assertEqual(self.daemon_manager.heartbeat_interval, 0.5)
        self.assertEqual(self.daemon_manager.max_failed_heartbeats, 2)
        self.assertFalse(self.daemon_manager._running)
        self.assertEqual(self.daemon_manager._failed_heartbeats, 0)

    def test_get_status(self):
        """Test get daemon status."""
        status = self.daemon_manager.get_status()

        self.assertIsInstance(status, dict)
        self.assertFalse(status["daemon_running"])
        self.assertFalse(status["server_running"])
        self.assertIsNone(status["server_pid"])
        self.assertEqual(status["failed_heartbeats"], 0)
        self.assertEqual(status["max_failed_heartbeats"], 2)
        self.assertEqual(status["heartbeat_interval"], 0.5)
        self.assertEqual(status["port"], 18863)

    @patch("decker.server.DaemonManager._monitor_health")
    def test_start_daemon(self, mock_monitor):
        """Test starting the daemon."""
        # Mock the monitoring to avoid infinite loop
        mock_monitor.return_value = None

        # Start daemon in a separate process to avoid blocking
        process = multiprocessing.Process(target=self.daemon_manager.start_daemon)
        process.start()

        # Give it a moment to start
        time.sleep(0.5)

        # Clean up
        process.terminate()
        process.join()

    def test_stop_daemon(self):
        """Test stopping the daemon."""
        result = self.daemon_manager.stop_daemon()
        # Should return True even if not running (graceful handling)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
