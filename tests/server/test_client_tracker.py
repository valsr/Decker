"""Tests for decker.server.client_tracker and its wiring into the service."""

import threading
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that

from decker.server.client_tracker import ClientTracker

_GRACE = 0.05


def _tracker() -> tuple[ClientTracker, threading.Event]:
    fired = threading.Event()
    return ClientTracker(_GRACE, fired.set), fired


def test_fires_after_the_grace_period_when_the_last_client_leaves() -> None:
    tracker, fired = _tracker()
    tracker.connected()
    tracker.disconnected()

    assert_that(fired.wait(2)).is_true()


def test_never_fires_before_any_client_has_connected() -> None:
    tracker, fired = _tracker()
    tracker.disconnected()

    assert_that(fired.wait(_GRACE * 6)).is_false()


def test_a_reconnect_within_the_grace_period_cancels() -> None:
    tracker, fired = _tracker()
    tracker.connected()
    tracker.disconnected()
    tracker.connected()

    assert_that(fired.wait(_GRACE * 6)).is_false()


def test_one_of_two_clients_leaving_does_not_fire() -> None:
    tracker, fired = _tracker()
    tracker.connected()
    tracker.connected()
    tracker.disconnected()

    assert_that(fired.wait(_GRACE * 6)).is_false()


def test_the_second_client_leaving_fires_once() -> None:
    count = MagicMock()
    tracker = ClientTracker(_GRACE, count)
    tracker.connected()
    tracker.connected()
    tracker.disconnected()
    tracker.disconnected()
    threading.Event().wait(_GRACE * 6)

    assert_that(count.call_count).is_equal_to(1)


def test_cancel_stops_a_pending_timer() -> None:
    tracker, fired = _tracker()
    tracker.connected()
    tracker.disconnected()
    tracker.cancel()

    assert_that(fired.wait(_GRACE * 6)).is_false()


class TestServiceWiring:
    @pytest.fixture()
    def wired(self, isolated_config):
        from decker.server.server_context import ServerContext
        from decker.server.service import DeckerService

        ctx = ServerContext(
            device_manager=MagicMock(),
            plugin_manager=MagicMock(),
            key_assignment_store=MagicMock(),
            device_state_store=MagicMock(),
            page_store=MagicMock(),
            page_controller=MagicMock(),
            event_bus=MagicMock(),
        )
        idle = threading.Event()
        ctx.client_tracker = ClientTracker(_GRACE, idle.set)
        DeckerService.configure_context(ctx)
        yield DeckerService(), idle
        DeckerService._context = None  # pylint: disable=protected-access

    def test_an_attached_client_counts_and_its_disconnect_starts_the_timer(self, wired) -> None:
        svc, idle = wired
        svc.on_connect(MagicMock())
        svc.client_attached()
        svc.on_disconnect(MagicMock())

        assert_that(idle.wait(2)).is_true()

    def test_a_connection_that_never_attached_is_not_a_client(self, wired) -> None:
        svc, idle = wired
        svc.on_connect(MagicMock())
        svc.on_disconnect(MagicMock())

        assert_that(idle.wait(_GRACE * 6)).is_false()

    def test_an_unattached_connection_does_not_keep_the_server_alive(self, wired) -> None:
        from decker.server.service import DeckerService

        gui, idle = wired
        monitor = DeckerService()
        monitor.on_connect(MagicMock())
        gui.on_connect(MagicMock())
        gui.client_attached()
        gui.on_disconnect(MagicMock())

        assert_that(idle.wait(2)).is_true()

    def test_attaching_twice_counts_once(self, wired) -> None:
        svc, idle = wired
        svc.client_attached()
        svc.client_attached()
        svc.on_disconnect(MagicMock())

        assert_that(idle.wait(2)).is_true()


class TestOnLastClientGone:
    @staticmethod
    def _server(restart_requested: bool = False):
        from decker.common.context import ServerAppContext
        from decker.server.server import ServerProcess

        server = ServerProcess(18861, 1.0, ServerAppContext())
        server._context = MagicMock(restart_requested=restart_requested)  # pylint: disable=protected-access
        server._gate = MagicMock()  # pylint: disable=protected-access
        return server

    def test_flag_off_never_stops(self, isolated_config) -> None:
        server = self._server()
        server._on_last_client_gone()  # pylint: disable=protected-access

        server._gate.request.assert_not_called()  # pylint: disable=protected-access

    def test_flag_on_requests_a_clean_shutdown(self, isolated_config) -> None:
        isolated_config.set("server.stop_when_last_client_leaves", True)
        server = self._server()
        server._on_last_client_gone()  # pylint: disable=protected-access

        server._gate.request.assert_called_once()  # pylint: disable=protected-access

    def test_a_pending_restart_is_never_turned_into_a_stop(self, isolated_config) -> None:
        isolated_config.set("server.stop_when_last_client_leaves", True)
        server = self._server(restart_requested=True)
        server._on_last_client_gone()  # pylint: disable=protected-access

        server._gate.request.assert_not_called()  # pylint: disable=protected-access
