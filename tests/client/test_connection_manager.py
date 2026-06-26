"""Tests for decker.client.connection_manager."""

import json
import time
from unittest.mock import MagicMock, patch

from assertpy import assert_that

from decker.client.connection_manager import ConnectionManager, _ClientService
from decker.client.context import AppContext
from decker.client.events import (
    ActionListUpdatedEvent,
    DeviceListUpdatedEvent,
    KeyDisplayStatesUpdatedEvent,
    KeyEvent,
    PluginLoadFailedEvent,
    ServerConnectedEvent,
    ServerDisconnectedEvent,
)
from decker.client.events.event_manager import EventManager
from decker.common.model import DeviceHardwareInfo


class TestConnectionManager:
    def setup_method(self):
        EventManager.reset()
        self.manager = ConnectionManager("localhost", 18861)

    def teardown_method(self):
        self.manager.stop()

    @patch("decker.client.connection_manager.rpyc.utils.factory.connect")
    def test_try_connect_success_marks_connected_and_pushes_events(self, mock_connect: MagicMock):
        mock_conn = MagicMock()
        mock_conn.root.devices_list.return_value = json.dumps([{"id": "abc123", "serial": "X"}])
        mock_conn.root.plugins_load_failures.return_value = json.dumps([])
        mock_conn.root.plugins_actions_list.return_value = json.dumps([])
        mock_connect.return_value = mock_conn

        self.manager._try_connect()  # pylint: disable=protected-access

        assert_that(self.manager.connected).is_true()
        events = EventManager.get().drain()
        assert_that(events).is_length(3)
        assert_that(events[0]).is_instance_of(ServerConnectedEvent)
        assert_that(events[1]).is_instance_of(DeviceListUpdatedEvent)
        assert isinstance(events[1], DeviceListUpdatedEvent)
        assert_that(events[1].devices).is_length(1)
        assert_that(events[1].devices[0].id).is_equal_to("abc123")
        assert_that(events[1].devices[0].serial).is_equal_to("X")

    @patch("decker.client.connection_manager.rpyc.utils.factory.connect")
    def test_try_connect_failure_leaves_disconnected_and_pushes_nothing(self, mock_connect: MagicMock):
        mock_connect.side_effect = ConnectionRefusedError("refused")

        self.manager._try_connect()  # pylint: disable=protected-access

        assert_that(self.manager.connected).is_false()
        assert_that(EventManager.get().drain()).is_empty()

    def test_check_heartbeat_failure_pushes_disconnected_event(self):
        mock_conn = MagicMock()
        mock_conn.root.heartbeat.side_effect = ConnectionResetError("lost")
        self.manager._conn = mock_conn  # pylint: disable=protected-access
        self.manager.connected = True

        self.manager._check_heartbeat()  # pylint: disable=protected-access

        assert_that(self.manager.connected).is_false()
        events = EventManager.get().drain()
        assert_that(events).is_length(1)
        assert_that(events[0]).is_instance_of(ServerDisconnectedEvent)

    def test_check_heartbeat_success_refreshes_devices(self):
        mock_conn = MagicMock()
        mock_conn.root.heartbeat.return_value = json.dumps({"status": "healthy"})
        mock_conn.root.devices_list.return_value = json.dumps([{"id": "abc123"}])
        mock_conn.root.plugins_load_failures.return_value = json.dumps([])
        mock_conn.root.plugins_actions_list.return_value = json.dumps([])
        self.manager._conn = mock_conn  # pylint: disable=protected-access
        self.manager.connected = True

        self.manager._check_heartbeat()  # pylint: disable=protected-access

        events = EventManager.get().drain()
        assert_that(events).is_length(2)
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
        mock_conn.root.devices_list.return_value = json.dumps([])
        mock_conn.root.plugins_load_failures.return_value = json.dumps(
            [{"plugin_uuid": "com.decker.broken", "error": "boom"}]
        )
        mock_conn.root.plugins_actions_list.return_value = json.dumps([])
        mock_connect.return_value = mock_conn

        self.manager._try_connect()  # pylint: disable=protected-access

        events = EventManager.get().drain()
        failure_events = [e for e in events if isinstance(e, PluginLoadFailedEvent)]
        assert_that(failure_events).is_length(1)
        assert_that(failure_events[0].plugin_uuid).is_equal_to("com.decker.broken")
        assert_that(failure_events[0].error).is_equal_to("boom")

    def test_plugin_failure_is_only_reported_once(self):
        mock_conn = MagicMock()
        mock_conn.root.plugins_load_failures.return_value = json.dumps(
            [{"plugin_uuid": "com.decker.broken", "error": "boom"}]
        )
        self.manager._conn = mock_conn  # pylint: disable=protected-access

        self.manager._check_plugin_failures()  # pylint: disable=protected-access
        self.manager._check_plugin_failures()  # pylint: disable=protected-access

        events = [e for e in EventManager.get().drain() if isinstance(e, PluginLoadFailedEvent)]
        assert_that(events).is_length(1)

    @patch("decker.client.connection_manager.rpyc.utils.factory.connect")
    def test_try_connect_pushes_action_list_updated_event(self, mock_connect: MagicMock):
        mock_conn = MagicMock()
        mock_conn.root.devices_list.return_value = json.dumps([])
        mock_conn.root.plugins_load_failures.return_value = json.dumps([])
        mock_conn.root.plugins_actions_list.return_value = json.dumps(
            [{"plugin_uuid": "p", "plugin_name": "P", "action_uuid": "p.a", "action_name": "A"}]
        )
        mock_connect.return_value = mock_conn

        self.manager._try_connect()  # pylint: disable=protected-access

        events = [e for e in EventManager.get().drain() if isinstance(e, ActionListUpdatedEvent)]
        assert_that(events).is_length(1)
        assert_that(events[0].actions).is_equal_to(
            [{"plugin_uuid": "p", "plugin_name": "P", "action_uuid": "p.a", "action_name": "A"}]
        )

    def test_check_heartbeat_success_refreshes_actions(self):
        mock_conn = MagicMock()
        mock_conn.root.heartbeat.return_value = json.dumps({"status": "healthy"})
        mock_conn.root.devices_list.return_value = json.dumps([])
        mock_conn.root.plugins_load_failures.return_value = json.dumps([])
        mock_conn.root.plugins_actions_list.return_value = json.dumps(
            [{"plugin_uuid": "p", "plugin_name": "P", "action_uuid": "p.a", "action_name": "A"}]
        )
        self.manager._conn = mock_conn  # pylint: disable=protected-access
        self.manager.connected = True

        self.manager._check_heartbeat()  # pylint: disable=protected-access

        events = [e for e in EventManager.get().drain() if isinstance(e, ActionListUpdatedEvent)]
        assert_that(events).is_length(1)

    def test_refresh_actions_failure_does_not_raise(self):
        mock_conn = MagicMock()
        mock_conn.root.plugins_actions_list.side_effect = RuntimeError("boom")
        self.manager._conn = mock_conn  # pylint: disable=protected-access

        self.manager._refresh_actions()  # pylint: disable=protected-access

        assert_that(EventManager.get().drain()).is_empty()

    def test_call_delegates_to_rpc_root(self):
        mock_conn = MagicMock()
        mock_conn.root.some_method.return_value = "result"
        self.manager._conn = mock_conn  # pylint: disable=protected-access
        result = self.manager.call("some_method", "arg1", 42)
        mock_conn.root.some_method.assert_called_once_with("arg1", 42)
        assert_that(result).is_equal_to("result")

    def test_call_returns_none_when_not_connected(self):
        result = self.manager.call("some_method")
        assert_that(result).is_none()

    def test_call_returns_none_and_logs_on_rpc_error(self):
        mock_conn = MagicMock()
        mock_conn.root.some_method.side_effect = RuntimeError("rpc error")
        self.manager._conn = mock_conn  # pylint: disable=protected-access
        result = self.manager.call("some_method")
        assert_that(result).is_none()

    def test_refresh_key_display_states_pushes_event(self):
        mock_conn = MagicMock()
        mock_conn.root.key_get_states.return_value = json.dumps([{"key_index": 0, "label": "5", "settings": {}}])
        self.manager._conn = mock_conn  # pylint: disable=protected-access
        AppContext.reset()
        AppContext.get().active_device = DeviceHardwareInfo(
            id="dev1", type="Stream Deck", vendor_id=0, product_id=0, num_keys=15
        )
        self.manager._refresh_key_display_states()  # pylint: disable=protected-access
        events = [e for e in EventManager.get().drain() if isinstance(e, KeyDisplayStatesUpdatedEvent)]
        assert_that(events).is_length(1)
        assert_that(events[0].device_id).is_equal_to("dev1")
        AppContext.reset()

    def test_refresh_key_display_states_no_op_without_device(self):
        mock_conn = MagicMock()
        self.manager._conn = mock_conn  # pylint: disable=protected-access
        AppContext.reset()
        self.manager._refresh_key_display_states()  # pylint: disable=protected-access
        mock_conn.root.key_get_states.assert_not_called()
        AppContext.reset()

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


class TestClientService:
    def setup_method(self):
        EventManager.reset()

    def test_exposed_on_server_event_invokes_callback(self):
        received = []
        service = _ClientService(on_event=lambda t, p: received.append((t, p)))
        service.exposed_on_server_event("key_event", '{"key": 1}')
        assert_that(received).is_length(1)
        assert_that(received[0][0]).is_equal_to("key_event")

    def test_exposed_on_server_event_swallows_callback_errors(self):
        def bad_callback(t: str, p: str) -> None:
            raise RuntimeError("boom")

        service = _ClientService(on_event=bad_callback)
        service.exposed_on_server_event("key_event", "{}")  # should not raise


class TestOnServerEvent:
    def setup_method(self):
        EventManager.reset()
        self.manager = ConnectionManager("localhost", 18861)

    def test_key_event_dispatches_key_event(self):
        payload = json.dumps({"device_id": "abc", "key_index": 3, "pressed": True})
        self.manager._on_server_event("key_event", payload)  # pylint: disable=protected-access
        events = [e for e in EventManager.get().drain() if isinstance(e, KeyEvent)]
        assert_that(events).is_length(1)
        assert_that(events[0].device_id).is_equal_to("abc")
        assert_that(events[0].key_index).is_equal_to(3)
        assert_that(events[0].pressed).is_true()

    def test_key_state_changed_dispatches_display_states_event(self):
        payload = json.dumps({"device_id": "abc", "key_index": 2, "image_b64": None, "label": "Hi"})
        self.manager._on_server_event("key_state_changed", payload)  # pylint: disable=protected-access
        events = [e for e in EventManager.get().drain() if isinstance(e, KeyDisplayStatesUpdatedEvent)]
        assert_that(events).is_length(1)
        assert_that(events[0].device_id).is_equal_to("abc")
        assert_that(events[0].states[0]["key_index"]).is_equal_to(2)
        assert_that(events[0].states[0]["label"]).is_equal_to("Hi")

    def test_unknown_event_type_is_silently_ignored(self):
        self.manager._on_server_event("some_future_event", "{}")  # pylint: disable=protected-access
        assert_that(EventManager.get().drain()).is_empty()

    def test_malformed_payload_does_not_raise(self):
        self.manager._on_server_event("key_event", "NOT JSON")  # pylint: disable=protected-access
