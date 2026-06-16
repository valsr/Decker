"""Tests for decker.client.app."""

from unittest.mock import MagicMock, patch

from assertpy import assert_that

from decker.client.app import main


class TestMain:
    @patch("decker.client.app.sys.exit")
    @patch("decker.client.app.MainWindow")
    @patch("decker.client.app.ConnectionManager")
    @patch("decker.client.app.QApplication")
    @patch("decker.common.logging.configure")
    def test_starts_connection_manager_before_constructing_window(
        self,
        mock_configure: MagicMock,  # pylint: disable=unused-argument
        mock_qapp_cls: MagicMock,
        mock_manager_cls: MagicMock,
        mock_window_cls: MagicMock,
        mock_exit: MagicMock,  # pylint: disable=unused-argument
    ):
        manager_instance = MagicMock()
        mock_manager_cls.return_value = manager_instance
        window_instance = MagicMock()
        mock_window_cls.return_value = window_instance
        mock_qapp_cls.return_value.exec.return_value = 0

        calls: list[str] = []

        def _on_window_init(*_args, **_kwargs) -> MagicMock:
            calls.append("window.init")
            return window_instance

        manager_instance.start.side_effect = lambda: calls.append("manager.start")
        mock_window_cls.side_effect = _on_window_init
        window_instance.check_initial_view.side_effect = lambda: calls.append("check_initial_view")

        main()

        assert_that(calls).is_equal_to(["manager.start", "window.init", "check_initial_view"])
        mock_window_cls.assert_called_once_with(manager_instance)
