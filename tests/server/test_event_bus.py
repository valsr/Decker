"""Tests for server-side EventBus push channel."""

from unittest.mock import MagicMock, call, patch

import pytest
from assertpy import assert_that

from decker.server.event_bus import EventBus


class TestEventBusRegistration:
    def test_register_adds_client(self):
        bus = EventBus()
        conn = MagicMock()
        bus.register(conn)
        assert_that(bus._clients).contains(conn)  # pylint: disable=protected-access

    def test_unregister_removes_client(self):
        bus = EventBus()
        conn = MagicMock()
        bus.register(conn)
        bus.unregister(conn)
        assert_that(bus._clients).does_not_contain(conn)  # pylint: disable=protected-access

    def test_unregister_unknown_client_is_noop(self):
        bus = EventBus()
        conn = MagicMock()
        bus.unregister(conn)  # should not raise


class TestEventBusPush:
    def test_push_calls_on_server_event_for_each_client(self):
        bus = EventBus()
        conn1, conn2 = MagicMock(), MagicMock()
        bus.register(conn1)
        bus.register(conn2)

        with patch("decker.server.event_bus.async_") as mock_async:
            mock_async.return_value = MagicMock(return_value=None)
            bus.push("key_event", '{"key": 1}')
            assert_that(mock_async.call_count).is_equal_to(2)

    def test_push_removes_dead_client_on_failure(self):
        bus = EventBus()
        dead_conn = MagicMock()
        live_conn = MagicMock()
        bus.register(dead_conn)
        bus.register(live_conn)

        def raise_for_dead(method):
            if method == dead_conn.root.on_server_event:
                raise OSError("disconnected")
            return MagicMock()

        with patch("decker.server.event_bus.async_", side_effect=raise_for_dead):
            bus.push("key_event", "{}")

        assert_that(bus._clients).does_not_contain(dead_conn)  # pylint: disable=protected-access
        assert_that(bus._clients).contains(live_conn)  # pylint: disable=protected-access

    def test_push_to_empty_bus_is_noop(self):
        bus = EventBus()
        bus.push("key_event", "{}")  # should not raise

    def test_push_with_no_registered_clients_skips_async(self):
        bus = EventBus()
        with patch("decker.server.event_bus.async_") as mock_async:
            bus.push("key_event", "{}")
            mock_async.assert_not_called()


class TestEventBusSenders:
    def test_the_remote_callable_is_resolved_once_per_client(self):
        bus = EventBus()
        conn = MagicMock()
        bus.register(conn)

        with patch("decker.server.event_bus.async_") as mock_async:
            send = MagicMock()
            mock_async.return_value = send
            for _ in range(3):
                bus.push("key_event", "{}")

        assert_that(mock_async.call_count).is_equal_to(1)
        assert_that(send.call_count).is_equal_to(3)

    def test_unregistering_forgets_the_resolved_callable(self):
        bus = EventBus()
        conn = MagicMock()
        bus.register(conn)
        with patch("decker.server.event_bus.async_", return_value=MagicMock()) as mock_async:
            bus.push("key_event", "{}")
            bus.unregister(conn)
            bus.register(conn)
            bus.push("key_event", "{}")

        assert_that(mock_async.call_count).is_equal_to(2)

    def test_a_client_whose_delivery_fails_is_dropped_and_its_callable_forgotten(self):
        bus = EventBus()
        conn = MagicMock()
        bus.register(conn)
        send = MagicMock(side_effect=OSError("gone"))

        with patch("decker.server.event_bus.async_", return_value=send):
            bus.push("key_event", "{}")

        assert_that(bus._clients).is_empty()  # pylint: disable=protected-access
        assert_that(bus._senders).is_empty()  # pylint: disable=protected-access


class _Conn:
    def __init__(self) -> None:
        self.received: list[tuple[str, str]] = []
        self.root = MagicMock()
        self.root.on_server_event = lambda event, payload: self.received.append((event, payload))


class TestEventBusTargeting:
    @pytest.fixture(autouse=True)
    def _direct_delivery(self):
        with patch("decker.server.event_bus.async_", side_effect=lambda method: method):
            yield

    def test_push_filtered_hands_each_client_its_own_loopback_flag(self):
        bus = EventBus()
        local, remote = _Conn(), _Conn()
        bus.register(local)
        bus.register(remote, loopback=False)

        bus.push_filtered("ev", lambda loopback: "local" if loopback else "remote")

        assert_that(local.received).is_equal_to([("ev", "local")])
        assert_that(remote.received).is_equal_to([("ev", "remote")])

    def test_register_defaults_to_loopback(self):
        bus = EventBus()
        conn = _Conn()
        bus.register(conn)

        bus.push_filtered("ev", str)

        assert_that(conn.received).is_equal_to([("ev", "True")])

    def test_push_to_reaches_only_that_client(self):
        bus = EventBus()
        first, second = _Conn(), _Conn()
        bus.register(first)
        bus.register(second)

        bus.push_to(first, "ev", "payload")

        assert_that(first.received).is_equal_to([("ev", "payload")])
        assert_that(second.received).is_empty()

    def test_push_to_a_failing_client_prunes_it(self):
        bus = EventBus()
        conn = _Conn()
        conn.root.on_server_event = MagicMock(side_effect=OSError("gone"))
        bus.register(conn)

        bus.push_to(conn, "ev", "payload")

        assert_that(bus._clients).does_not_contain(conn)  # pylint: disable=protected-access

    def test_push_filtered_prunes_failing_clients(self):
        bus = EventBus()
        conn = _Conn()
        conn.root.on_server_event = MagicMock(side_effect=OSError("gone"))
        bus.register(conn)

        bus.push_filtered("ev", str)

        assert_that(bus._clients).does_not_contain(conn)  # pylint: disable=protected-access
