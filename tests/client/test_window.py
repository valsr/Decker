"""Tests for decker.client.window.MainWindow."""

from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that
from PyQt6.QtGui import QCloseEvent

from decker.client.context import AppContext
from decker.client.events import (
    DeviceListUpdatedEvent,
    PluginLoadFailedEvent,
    ServerConnectedEvent,
    ServerDisconnectedEvent,
)
from decker.client.events.event_manager import EventManager
from decker.client.ui_state_store import UiStateStore
from decker.client.view_name import ViewName
from decker.client.window import MainWindow


@pytest.fixture
def connection_manager() -> MagicMock:
    manager = MagicMock()
    manager.connected = False
    return manager


@pytest.fixture
def window(qapp, connection_manager, tmp_path):  # pylint: disable=unused-argument,redefined-outer-name
    AppContext._instance = None  # pylint: disable=protected-access
    EventManager.reset()
    win = MainWindow(connection_manager, ui_state_store=UiStateStore(tmp_path / "config.db"))
    for view in win._views.values():  # pylint: disable=protected-access
        view.on_activate = MagicMock()  # type: ignore[method-assign]
        view.on_deactivate = MagicMock()  # type: ignore[method-assign]
        view.handle_event = MagicMock()  # type: ignore[method-assign]
        view.save_state = MagicMock()  # type: ignore[method-assign]
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

    def test_plugin_load_failed_shows_toast_and_does_not_forward_to_view(
        self, window
    ):  # pylint: disable=redefined-outer-name
        window.switch_to(ViewName.DASHBOARD)

        window.dispatch(PluginLoadFailedEvent(plugin_uuid="com.decker.broken", error="boom"))

        assert_that(window._toast.isHidden()).is_false()  # pylint: disable=protected-access
        assert_that(window._toast.text()).contains("com.decker.broken").contains(
            "boom"
        )  # pylint: disable=protected-access
        window._views[ViewName.DASHBOARD].handle_event.assert_not_called()  # pylint: disable=protected-access

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

    def test_saves_window_geometry(self, window):  # pylint: disable=redefined-outer-name
        window.setGeometry(10, 20, 300, 400)

        window.closeEvent(QCloseEvent())

        saved = window._ui_state_store.get("window_geometry")  # pylint: disable=protected-access
        assert_that(saved).is_equal_to({"x": 10, "y": 20, "w": 300, "h": 400})

    def test_calls_save_state_on_every_view(self, window):  # pylint: disable=redefined-outer-name
        window.closeEvent(QCloseEvent())

        for view in window._views.values():  # pylint: disable=protected-access
            view.save_state.assert_called_once()


class TestShowEvent:
    def test_restores_saved_geometry_on_first_show(self, window):  # pylint: disable=redefined-outer-name
        window._ui_state_store.set(  # pylint: disable=protected-access
            "window_geometry", {"x": 5, "y": 6, "w": 333, "h": 222}
        )

        with patch.object(MainWindow, "setGeometry") as mock_set_geometry:
            window.show()

        mock_set_geometry.assert_called_once_with(5, 6, 333, 222)

    def test_does_not_restore_again_on_subsequent_shows(self, window):  # pylint: disable=redefined-outer-name
        window._ui_state_store.set(  # pylint: disable=protected-access
            "window_geometry", {"x": 5, "y": 6, "w": 333, "h": 222}
        )
        window.show()

        with patch.object(MainWindow, "setGeometry") as mock_set_geometry:
            window.hide()
            window.show()

        mock_set_geometry.assert_not_called()

    def test_no_saved_geometry_does_not_call_set_geometry(self, window):  # pylint: disable=redefined-outer-name
        with patch.object(MainWindow, "setGeometry") as mock_set_geometry:
            window.show()

        mock_set_geometry.assert_not_called()
