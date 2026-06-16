"""Tests for decker.client.views.error.ErrorView."""

from unittest.mock import MagicMock

from assertpy import assert_that

from decker.client.context import AppContext
from decker.client.views.error import ErrorView


class TestErrorView:
    def setup_method(self):
        AppContext._instance = None  # pylint: disable=protected-access

    def test_show_error_sets_message(self, qapp):  # pylint: disable=unused-argument
        view = ErrorView()

        view.show_error("something broke")

        assert_that(view._message_label.text()).is_equal_to("something broke")  # pylint: disable=protected-access

    def test_restart_triggers_window_restart(self, qapp):  # pylint: disable=unused-argument
        view = ErrorView()
        mock_window = MagicMock()
        AppContext.get().window = mock_window

        view._on_restart()  # pylint: disable=protected-access

        mock_window.restart.assert_called_once()

    def test_restart_is_a_noop_without_window(self, qapp):  # pylint: disable=unused-argument
        view = ErrorView()

        view._on_restart()  # pylint: disable=protected-access
