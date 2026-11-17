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
