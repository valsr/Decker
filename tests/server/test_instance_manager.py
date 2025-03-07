import os
import sys
import tempfile
import threading
from unittest.mock import MagicMock, mock_open, patch

import pytest
from assertpy import assert_that

from decker_server.server import Server
from decker_server.server.instance_manager import InstanceManager


class TestInstanceManager:
    """Tests for the InstanceManager class."""

    class TestInit:
        """Tests for the InstanceManager's __init__ method."""

        def test_init_sets_default_values(self):
            # Test that constructor sets expected default values.

            instance = InstanceManager()

            assert_that(instance.lock_file).is_none()
            assert_that(instance.lock_file_path).ends_with("decker_server.lock")
            assert_that(instance.is_dev_mode).is_false()
            assert_that(instance.server).is_none()

        def test_init_with_dev_mode(self):
            # Test that constructor sets dev_mode parameter correctly.

            instance = InstanceManager(dev_mode=True)

            assert_that(instance.is_dev_mode).is_true()

    class TestGetServerLock:
        """Tests for the InstanceManager's _get_server_lock method."""

        def test_dev_mode_returns_true(self):
            # Test that dev_mode allows running without lock check.

            instance = InstanceManager(dev_mode=True)

            result = instance._get_server_lock()

            assert_that(result).is_true()

        @patch("decker_server.server.instance_manager.open", new_callable=mock_open)
        @patch("decker_server.server.instance_manager.InstanceManager._lock")
        @patch("decker_server.server.instance_manager.atexit")
        def test_acquires_lock_successfully(self, mock_atexit, mock_lock, mock_open_file):
            # Test successful lock acquisition.

            instance = InstanceManager()

            result = instance._get_server_lock()

            assert_that(result).is_true()
            mock_open_file.assert_called_once_with(instance.lock_file_path, "w")
            mock_lock.assert_called_once()
            mock_atexit.register.assert_called_once_with(instance._cleanup_lock)

        @patch("decker_server.server.instance_manager.open")
        @patch("decker_server.server.instance_manager.sys.exit")
        def test_exits_when_lock_fails(self, mock_exit, mock_open_file):
            # Test behavior when lock acquisition fails.

            mock_open_file.side_effect = IOError("File locked")
            instance = InstanceManager()

            instance._get_server_lock()

            mock_exit.assert_called_once_with(1)

    class TestLock:
        """Tests for the InstanceManager's _lock method."""

        @patch("sys.platform", "win32")
        @patch("decker_server.server.instance_manager.msvcrt", autospec=True)
        def test_lock_on_windows(self, mock_msvcrt):
            # Test Windows-specific locking mechanism.

            instance = InstanceManager()
            instance.lock_file = MagicMock()

            instance._lock()

            mock_msvcrt.lock.assert_called_once()

        @patch("sys.platform", "linux")
        @patch("decker_server.server.instance_manager.fcntl", autospec=True)
        def test_lock_on_unix(self, mock_fcntl):
            # Test Unix-specific locking mechanism.

            instance = InstanceManager()
            instance.lock_file = MagicMock()

            instance._lock()

            mock_fcntl.flock.assert_called_once()

        @patch("sys.platform", "win32")
        @patch("decker_server.server.instance_manager.msvcrt")
        def test_lock_failure(self, mock_msvcrt):
            # Test behavior when lock fails.

            mock_msvcrt.lock.side_effect = IOError("Lock failed")
            instance = InstanceManager()
            instance.lock_file = MagicMock()

            with pytest.raises(IOError):
                instance._lock()

            instance.lock_file.close.assert_called_once()

    class TestCleanupLock:
        """Tests for the InstanceManager's _cleanup_lock method."""

        @patch("sys.platform", "win32")
        @patch("decker_server.server.instance_manager.msvcrt", autospec=True)
        @patch("os.remove")
        def test_cleanup_on_windows(self, mock_remove, mock_msvcrt):
            # Test Windows-specific unlock mechanism.

            instance = InstanceManager()
            instance.lock_file = MagicMock()

            instance._cleanup_lock()

            mock_msvcrt.lock.assert_called_once()
            instance.lock_file.close.assert_called_once()
            mock_remove.assert_called_once_with(instance.lock_file_path)

        @patch("sys.platform", "linux")
        @patch("decker_server.server.instance_manager.fcntl", autospec=True)
        @patch("os.remove")
        def test_cleanup_on_unix(self, mock_remove, mock_fcntl):
            # Test Unix-specific unlock mechanism.

            instance = InstanceManager()
            instance.lock_file = MagicMock()

            instance._cleanup_lock()

            mock_fcntl.flock.assert_called_once()
            instance.lock_file.close.assert_called_once()
            mock_remove.assert_called_once_with(instance.lock_file_path)

    class TestStartServer:
        """Tests for the InstanceManager's start_server method."""

        @patch("decker_server.server.instance_manager.InstanceManager._get_server_lock")
        @patch("decker_server.server.instance_manager.Server")
        @patch("threading.Event")
        def test_start_server_with_lock(self, mock_event, mock_server, mock_get_lock):
            # Test server start behavior when lock is acquired.

            mock_get_lock.return_value = True
            mock_event_instance = MagicMock()
            mock_event.return_value = mock_event_instance
            instance = InstanceManager()

            instance.start_server()

            mock_get_lock.assert_called_once()
            assert_that(instance.server).is_not_none()
            mock_event_instance.wait.assert_called_once()

        @patch("decker_server.server.instance_manager.InstanceManager._get_server_lock")
        @patch("decker_server.server.instance_manager.logging.error")
        def test_start_server_without_lock(self, mock_log_error, mock_get_lock):
            # Test server start behavior when lock acquisition fails.

            mock_get_lock.return_value = False
            instance = InstanceManager()

            instance.start_server()

            mock_get_lock.assert_called_once()
            mock_log_error.assert_called_once()
            assert_that(instance.server).is_none()

    class TestHandleInterrupt:
        """Tests for the InstanceManager's handle_interrupt method."""

        @patch("decker_server.server.instance_manager.time.sleep")
        @patch("decker_server.server.instance_manager.exit")
        def test_handle_interrupt_without_server(self, mock_exit, mock_sleep):
            # Test interrupt handling when server is not running.

            instance = InstanceManager()
            instance.server = None

            instance.handle_interrupt(None, None)

            mock_sleep.assert_called_once_with(1)
            mock_exit.assert_called_once_with(0)

        @patch("decker_server.server.instance_manager.time.sleep")
        @patch("decker_server.server.instance_manager.exit")
        def test_handle_interrupt_with_server(self, mock_exit, mock_sleep):
            # Test interrupt handling when server is running.

            instance = InstanceManager()
            instance.server = MagicMock()
            instance.server.is_alive.return_value = False

            instance.handle_interrupt(None, None)

            instance.server.stop.assert_called_once()
            instance.server.join.assert_called_once_with(timeout=5)
            mock_sleep.assert_called_once_with(1)
            mock_exit.assert_called_once_with(0)

        @patch("decker_server.server.instance_manager.time.sleep")
        @patch("decker_server.server.instance_manager.exit")
        def test_handle_interrupt_with_stuck_server(self, mock_exit, mock_sleep):
            # Test interrupt handling when server thread doesn't terminate normally.

            instance = InstanceManager()
            instance.server = MagicMock()
            instance.server.is_alive.return_value = True

            instance.handle_interrupt(None, None)

            instance.server.stop.assert_called_once()
            instance.server.join.assert_called_once_with(timeout=5)
            instance.server._stop.assert_called_once()
            mock_sleep.assert_called_once_with(1)
            mock_exit.assert_called_once_with(0)
