"""Tests for decker.client.views.dashboard.DashboardView."""

from unittest.mock import MagicMock

from assertpy import assert_that

from decker.client.context import AppContext
from decker.client.events import DeviceListUpdatedEvent
from decker.client.views.dashboard import DashboardView


class TestDashboardView:
    def setup_method(self):
        AppContext._instance = None  # pylint: disable=protected-access

    def test_handle_event_renders_devices(self, qapp):  # pylint: disable=unused-argument
        view = DashboardView()
        event = DeviceListUpdatedEvent(devices=[{"type": "Stream Deck", "serial": "X1"}])

        view.handle_event(event)

        assert_that(view._list_layout.count()).is_equal_to(1)  # pylint: disable=protected-access

    def test_handle_event_with_no_devices_shows_empty_message(self, qapp):  # pylint: disable=unused-argument
        view = DashboardView()

        view.handle_event(DeviceListUpdatedEvent(devices=[]))

        assert_that(view._list_layout.count()).is_equal_to(1)  # pylint: disable=protected-access

    def test_select_device_navigates_via_window(self, qapp):  # pylint: disable=unused-argument
        view = DashboardView()
        mock_window = MagicMock()
        AppContext.get().window = mock_window

        view._select_device("abc123")  # pylint: disable=protected-access

        mock_window.switch_device.assert_called_once_with("abc123")

    def test_select_device_is_a_noop_without_window(self, qapp):  # pylint: disable=unused-argument
        view = DashboardView()

        view._select_device("abc123")  # pylint: disable=protected-access
