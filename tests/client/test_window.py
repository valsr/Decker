"""Tests for decker.client.window.MainWindow."""

from unittest.mock import MagicMock

import pytest
from assertpy import assert_that
from PyQt6.QtGui import QCloseEvent

from decker.client.context import AppContext
from decker.client.event_hub import EventHub
from decker.client.events import (
    DeviceListUpdatedEvent,
    ServerConnectedEvent,
    ServerDisconnectedEvent,
)
from decker.client.view_name import ViewName
from decker.client.window import MainWindow


@pytest.fixture
def connection_manager() -> MagicMock:
    manager = MagicMock()
    manager.connected = False
    return manager


@pytest.fixture
def window(qapp, connection_manager) -> MainWindow:  # pylint: disable=unused-argument,redefined-outer-name
    AppContext._instance = None  # pylint: disable=protected-access
    EventHub._instance = None  # pylint: disable=protected-access
    win = MainWindow(connection_manager)
    for view in win._views.values():  # pylint: disable=protected-access
        view.on_activate = MagicMock()  # type: ignore[method-assign]
        view.on_deactivate = MagicMock()  # type: ignore[method-assign]
        view.handle_event = MagicMock()  # type: ignore[method-assign]
    return win


class TestRegisterView:
    def test_all_five_views_registered(self, window):  # pylint: disable=redefined-outer-name
        assert_that(set(window._views.keys())).is_equal_to(set(ViewName))  # pylint: disable=protected-access


class TestSwitchTo:
    def test_activates_target_and_sets_active(self, window):  # pylint: disable=redefined-outer-name
        window.switch_to(ViewName.DASHBOARD)

        window._views[ViewName.DASHBOARD].on_activate.assert_called_once()  # pylint: disable=protected-access
        assert_that(window._active).is_equal_to(ViewName.DASHBOARD)  # pylint: disable=protected-access

    def test_deactivates_outgoing_before_activating_incoming(self, window):  # pylint: disable=redefined-outer-name
        calls = []
        window._views[ViewName.CONNECTING].on_deactivate.side_effect = lambda: calls.append(
            "deactivate"
        )  # pylint: disable=protected-access
        window._views[ViewName.DASHBOARD].on_activate.side_effect = lambda: calls.append(
            "activate"
        )  # pylint: disable=protected-access

        window.switch_to(ViewName.CONNECTING)
        window.switch_to(ViewName.DASHBOARD)

        assert_that(calls).is_equal_to(["deactivate", "activate"])

    def test_is_noop_when_target_already_active(self, window):  # pylint: disable=redefined-outer-name
        window.switch_to(ViewName.DASHBOARD)
        window._views[ViewName.DASHBOARD].on_activate.reset_mock()  # pylint: disable=protected-access

        window.switch_to(ViewName.DASHBOARD)

        window._views[ViewName.DASHBOARD].on_activate.assert_not_called()  # pylint: disable=protected-access


class TestSwitchDevice:
    def test_sets_active_device_and_navigates_to_device_view(self, window):  # pylint: disable=redefined-outer-name
        window.switch_device("abc123")

        assert_that(AppContext.get().active_device).is_equal_to("abc123")
        assert_that(window._active).is_equal_to(ViewName.DEVICE)  # pylint: disable=protected-access


class TestDispatch:
    def test_server_disconnected_saves_last_view_and_switches_to_connecting(
        self, window
    ):  # pylint: disable=redefined-outer-name
        window.switch_to(ViewName.DASHBOARD)

        window.dispatch(ServerDisconnectedEvent(reason="lost"))

        assert_that(window._active).is_equal_to(ViewName.CONNECTING)  # pylint: disable=protected-access
        assert_that(window._last_view).is_equal_to(ViewName.DASHBOARD)  # pylint: disable=protected-access

    def test_server_disconnected_does_not_overwrite_last_view_when_already_connecting(
        self, window  # pylint: disable=redefined-outer-name
    ):
        window.switch_to(ViewName.DASHBOARD)
        window.dispatch(ServerDisconnectedEvent(reason="lost"))
        window.dispatch(ServerDisconnectedEvent(reason="lost again"))

        assert_that(window._last_view).is_equal_to(ViewName.DASHBOARD)  # pylint: disable=protected-access

    def test_server_connected_restores_last_view_and_clears_it(self, window):  # pylint: disable=redefined-outer-name
        window.switch_to(ViewName.DASHBOARD)
        window.dispatch(ServerDisconnectedEvent(reason="lost"))

        window.dispatch(ServerConnectedEvent(host="localhost", port=18861))

        assert_that(window._active).is_equal_to(ViewName.DASHBOARD)  # pylint: disable=protected-access
        assert_that(window._last_view).is_none()  # pylint: disable=protected-access

    def test_server_connected_falls_back_to_dashboard_with_no_last_view(
        self, window
    ):  # pylint: disable=redefined-outer-name
        window.dispatch(ServerConnectedEvent(host="localhost", port=18861))

        assert_that(window._active).is_equal_to(ViewName.DASHBOARD)  # pylint: disable=protected-access

    def test_unknown_event_forwarded_to_active_view(self, window):  # pylint: disable=redefined-outer-name
        window.switch_to(ViewName.DASHBOARD)
        event = DeviceListUpdatedEvent(devices=[])

        window.dispatch(event)

        window._views[ViewName.DASHBOARD].handle_event.assert_called_once_with(
            event
        )  # pylint: disable=protected-access


class TestCheckInitialView:
    def test_connected_switches_to_dashboard_and_shows(
        self, window, connection_manager  # pylint: disable=redefined-outer-name
    ):
        connection_manager.connected = True

        window.check_initial_view()

        assert_that(window._active).is_equal_to(ViewName.DASHBOARD)  # pylint: disable=protected-access

    def test_apply_initial_view_falls_back_to_connecting_when_disconnected(
        self, window  # pylint: disable=redefined-outer-name
    ):
        window._apply_initial_view()  # pylint: disable=protected-access

        assert_that(window._active).is_equal_to(ViewName.CONNECTING)  # pylint: disable=protected-access

    def test_apply_initial_view_uses_dashboard_when_connected(
        self, window, connection_manager  # pylint: disable=redefined-outer-name
    ):
        connection_manager.connected = True

        window._apply_initial_view()  # pylint: disable=protected-access

        assert_that(window._active).is_equal_to(ViewName.DASHBOARD)  # pylint: disable=protected-access


class TestRestart:
    def test_stops_and_restarts_connection_manager_and_lands_on_connecting(
        self, window, connection_manager  # pylint: disable=redefined-outer-name
    ):
        window.switch_to(ViewName.DASHBOARD)
        window.dispatch(ServerDisconnectedEvent(reason="lost"))  # populate _last_view

        window.restart()

        connection_manager.stop.assert_called_once()
        connection_manager.start.assert_called_once()
        assert_that(window._active).is_equal_to(ViewName.CONNECTING)  # pylint: disable=protected-access
        assert_that(window._last_view).is_none()  # pylint: disable=protected-access
        assert_that(AppContext.get().window).is_same_as(window)


class TestCloseEvent:
    def test_stops_connection_manager(self, window, connection_manager):  # pylint: disable=redefined-outer-name
        window.closeEvent(QCloseEvent())

        connection_manager.stop.assert_called_once()
