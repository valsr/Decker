from unittest.mock import MagicMock, patch

from assertpy import assert_that

from decker.service.service import ServiceManager


class TestInstanceManager:
    """Tests for the InstanceManager class."""

    class TestInit:
        """Tests for the InstanceManager's __init__ method."""

        def test_init_sets_default_values(self):
            # Act
            instance = ServiceManager()

            # Assert
            assert_that(instance._lock_file).is_none()
            assert_that(instance._lock_file_path).ends_with("decker.lock")
            assert_that(instance.is_dev_mode).is_false()
            assert_that(instance.api).is_none()

        def test_init_with_dev_mode(self):
            # Act
            instance = ServiceManager(dev_mode=True)

            # Assert
            assert_that(instance.is_dev_mode).is_true()

    class TestStartServer:
        """Tests for the InstanceManager's start_server method."""

        @patch("decker.platform.lock_file", autospec=True)
        @patch("decker.server.instance_manager.Server")
        @patch("threading.Event")
        def test_start_server_with_lock(self, mock_event, mock_server, mock_lock_file):
            # Test server start behavior when lock is acquired.

            # Arrange
            mock_lock_file.return_value = True
            mock_event_instance = MagicMock()
            mock_event.return_value = mock_event_instance
            instance = ServiceManager()

            # Act
            instance.start()

            # Assert
            mock_lock_file.assert_called_once()
            assert_that(instance.api).is_not_none()
            mock_event_instance.wait.assert_called_once()

        @patch("decker.server.instance_manager.Server")
        @patch("decker.platform.lock_file", autospec=True)
        @patch("decker.server.instance_manager.logging.error")
        @patch("threading.Event")
        def test_start_server_without_lock(self, mock_event, mock_log_error, mock_lock_file, mock_server):
            # Test server start behavior when lock acquisition fails.

            # Arrange
            mock_lock_file.side_effect = IOError("Lock failed")
            instance = ServiceManager()

            # Act
            instance.start()

            # Assert
            mock_log_error.assert_called_once()
            assert_that(instance.api).is_none()
