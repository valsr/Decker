"""Tests for decker.client.connection_manager."""

import time
from unittest.mock import MagicMock, patch

from assertpy import assert_that

from decker.client.connection_manager import ConnectionManager
from decker.client.event_hub import EventHub
from decker.client.events import (
    DeviceListUpdatedEvent,
    PluginLoadFailedEvent,
    ServerConnectedEvent,
    ServerDisconnectedEvent,
)


class TestConnectionManager:
    def setup_method(self):
        EventHub._instance = None  # pylint: disable=protected-access
        self.manager = ConnectionManager("localhost", 18861)

    def teardown_method(self):
        self.manager.stop()

    @patch("decker.client.connection_manager.rpyc.utils.factory.connect")
    def test_try_connect_success_marks_connected_and_pushes_events(self, mock_connect: MagicMock):
        mock_conn = MagicMock()
        mock_conn.root.devices_list.return_value = [{"id": "abc123", "serial": "X"}]
        mock_connect.return_value = mock_conn

        self.manager._try_connect()  # pylint: disable=protected-access

        assert_that(self.manager.connected).is_true()
        events = EventHub.get().drain()
        assert_that(events).is_length(2)
        assert_that(events[0]).is_instance_of(ServerConnectedEvent)
        assert_that(events[1]).is_instance_of(DeviceListUpdatedEvent)
        assert isinstance(events[1], DeviceListUpdatedEvent)
        assert_that(events[1].devices).is_equal_to([{"id": "abc123", "serial": "X"}])

    @patch("decker.client.connection_manager.rpyc.utils.factory.connect")
    def test_try_connect_failure_leaves_disconnected_and_pushes_nothing(self, mock_connect: MagicMock):
        mock_connect.side_effect = ConnectionRefusedError("refused")

        self.manager._try_connect()  # pylint: disable=protected-access

        assert_that(self.manager.connected).is_false()
        assert_that(EventHub.get().drain()).is_empty()

    def test_check_heartbeat_failure_pushes_disconnected_event(self):
        mock_conn = MagicMock()
        mock_conn.root.heartbeat.side_effect = ConnectionResetError("lost")
        self.manager._conn = mock_conn  # pylint: disable=protected-access
        self.manager.connected = True

        self.manager._check_heartbeat()  # pylint: disable=protected-access

        assert_that(self.manager.connected).is_false()
        events = EventHub.get().drain()
        assert_that(events).is_length(1)
        assert_that(events[0]).is_instance_of(ServerDisconnectedEvent)

    def test_check_heartbeat_success_refreshes_devices(self):
        mock_conn = MagicMock()
        mock_conn.root.heartbeat.return_value = {"status": "healthy"}
        mock_conn.root.devices_list.return_value = [{"id": "abc123"}]
        self.manager._conn = mock_conn  # pylint: disable=protected-access
        self.manager.connected = True

        self.manager._check_heartbeat()  # pylint: disable=protected-access

        events = EventHub.get().drain()
        assert_that(events).is_length(1)
        assert_that(events[0]).is_instance_of(DeviceListUpdatedEvent)

    def test_stop_closes_connection_and_clears_connected(self):
        mock_conn = MagicMock()
        self.manager._conn = mock_conn  # pylint: disable=protected-access
        self.manager.connected = True

        self.manager.stop()

        mock_conn.close.assert_called_once()
        assert_that(self.manager.connected).is_false()

    @patch("decker.client.connection_manager.rpyc.utils.factory.connect")
    def test_try_connect_pushes_plugin_load_failed_event(self, mock_connect: MagicMock):
        mock_conn = MagicMock()
        mock_conn.root.devices_list.return_value = []
        mock_conn.root.plugins_load_failures.return_value = [{"plugin_uuid": "com.decker.broken", "error": "boom"}]
        mock_connect.return_value = mock_conn

        self.manager._try_connect()  # pylint: disable=protected-access

        events = EventHub.get().drain()
        failure_events = [e for e in events if isinstance(e, PluginLoadFailedEvent)]
        assert_that(failure_events).is_length(1)
        assert_that(failure_events[0].plugin_uuid).is_equal_to("com.decker.broken")
        assert_that(failure_events[0].error).is_equal_to("boom")

    def test_plugin_failure_is_only_reported_once(self):
        mock_conn = MagicMock()
        mock_conn.root.plugins_load_failures.return_value = [{"plugin_uuid": "com.decker.broken", "error": "boom"}]
        self.manager._conn = mock_conn  # pylint: disable=protected-access

        self.manager._check_plugin_failures()  # pylint: disable=protected-access
        self.manager._check_plugin_failures()  # pylint: disable=protected-access

        events = [e for e in EventHub.get().drain() if isinstance(e, PluginLoadFailedEvent)]
        assert_that(events).is_length(1)

    @patch("decker.client.connection_manager.rpyc.utils.factory.connect")
    def test_start_spawns_a_worker_thread_and_stop_joins_it(self, mock_connect: MagicMock):
        mock_connect.side_effect = ConnectionRefusedError("refused")
        with (
            patch("decker.client.connection_manager._RETRY_INTERVAL_S", 0.01),
            patch("decker.client.connection_manager._HEARTBEAT_INTERVAL_S", 0.01),
        ):
            self.manager.start()
            time.sleep(0.05)
            thread = self.manager._thread  # pylint: disable=protected-access
            assert thread is not None
            assert_that(thread.is_alive()).is_true()

            self.manager.stop()

            assert_that(self.manager._thread).is_none()  # pylint: disable=protected-access
