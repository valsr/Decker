"""Tests for decker.client.connection_manager."""

import json
import time
from unittest.mock import MagicMock, patch

from assertpy import assert_that

from decker.client.connection_manager import (
    ConnectionManager,
    ServerState,
    _ClientService,
)
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
from decker.common.utils import api_response
from decker.server.service import DeckerServiceStatus, DeckerStatusEnum


@api_response
def _server_status(status: DeckerStatusEnum) -> DeckerServiceStatus:
    return DeckerServiceStatus(service_status=status, last_heartbeat=0.0)


def _heartbeat_payload(status: DeckerStatusEnum) -> str:
    """Build a heartbeat reply with the server's own serializer so the wire format can't drift."""
    return str(_server_status(status))


def _healthy_conn() -> MagicMock:
    conn = MagicMock()
    conn.root.heartbeat.return_value = _heartbeat_payload(DeckerStatusEnum.HEALTHY)
    conn.root.devices_list.return_value = json.dumps([])
    conn.root.plugins_load_failures.return_value = json.dumps([])
    conn.root.plugins_actions_list.return_value = json.dumps([])
    return conn


class TestConnectionManager:
    def setup_method(self):
        EventManager.reset()
        self._config_patches = [
            patch("decker.client.config.get_server_host", return_value="localhost"),
            patch("decker.client.config.get_server_port", return_value=18861),
        ]
        for p in self._config_patches:
            p.start()
        self.manager = ConnectionManager()

    def teardown_method(self):
        self.manager.stop()
        for p in self._config_patches:
            p.stop()

    @patch("decker.client.connection_manager.rpyc.utils.factory.connect")
    def test_try_connect_success_marks_connected_and_pushes_events(self, mock_connect: MagicMock):
        mock_conn = MagicMock()
        mock_conn.root.devices_list.return_value = json.dumps([{"id": "abc123", "serial": "X"}])
        mock_conn.root.plugins_load_failures.return_value = json.dumps([])
        mock_conn.root.plugins_actions_list.return_value = json.dumps([])
        mock_connect.return_value = mock_conn

        self.manager._try_connect()  # pylint: disable=protected-access

        assert_that(self.manager.state).is_equal_to(ServerState.HEALTHY)
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

        assert_that(self.manager.state).is_equal_to(ServerState.DISCONNECTED)
        assert_that(EventManager.get().drain()).is_empty()

    def test_check_heartbeat_failure_pushes_disconnected_event(self):
        mock_conn = MagicMock()
        mock_conn.root.heartbeat.side_effect = ConnectionResetError("lost")
        self.manager._conn = mock_conn  # pylint: disable=protected-access
        self.manager.state = ServerState.HEALTHY

        self.manager._check_heartbeat()  # pylint: disable=protected-access

        assert_that(self.manager.state).is_equal_to(ServerState.DISCONNECTED)
        events = EventManager.get().drain()
        assert_that(events).is_length(1)
        assert_that(events[0]).is_instance_of(ServerDisconnectedEvent)

    def test_check_heartbeat_success_refreshes_devices(self):
        mock_conn = MagicMock()
        mock_conn.root.heartbeat.return_value = _heartbeat_payload(DeckerStatusEnum.HEALTHY)
        mock_conn.root.devices_list.return_value = json.dumps([{"id": "abc123"}])
        mock_conn.root.plugins_load_failures.return_value = json.dumps([])
        mock_conn.root.plugins_actions_list.return_value = json.dumps([])
        self.manager._conn = mock_conn  # pylint: disable=protected-access
        self.manager.state = ServerState.HEALTHY

        self.manager._check_heartbeat()  # pylint: disable=protected-access

        events = EventManager.get().drain()
        assert_that(events).is_length(2)
        assert_that(events[0]).is_instance_of(DeviceListUpdatedEvent)

    def test_check_heartbeat_non_healthy_status_marks_unhealthy_but_stays_connected(self):
        mock_conn = MagicMock()
        mock_conn.root.heartbeat.return_value = _heartbeat_payload(DeckerStatusEnum.UNHEALTHY)
        mock_conn.root.devices_list.return_value = json.dumps([])
        mock_conn.root.plugins_load_failures.return_value = json.dumps([])
        mock_conn.root.plugins_actions_list.return_value = json.dumps([])
        self.manager._conn = mock_conn  # pylint: disable=protected-access
        self.manager.state = ServerState.HEALTHY

        self.manager._check_heartbeat()  # pylint: disable=protected-access

        assert_that(self.manager.state).is_equal_to(ServerState.UNHEALTHY)
        assert_that(self.manager.is_connected).is_true()
        assert_that(self.manager.is_ready).is_true()

    def test_initializing_state_is_connected_but_not_ready(self):
        self.manager.state = ServerState.INITIALIZING

        assert_that(self.manager.is_connected).is_true()
        assert_that(self.manager.is_ready).is_false()

    def test_disconnected_state_is_neither_connected_nor_ready(self):
        assert_that(self.manager.is_connected).is_false()
        assert_that(self.manager.is_ready).is_false()

    @patch("decker.client.connection_manager.rpyc.utils.factory.connect")
    def test_try_connect_reads_host_and_port_from_config(self, mock_connect: MagicMock):
        mock_connect.side_effect = ConnectionRefusedError("refused")
        with (
            patch("decker.client.config.get_server_host", return_value="otherhost"),
            patch("decker.client.config.get_server_port", return_value=9999),
        ):
            self.manager._try_connect()  # pylint: disable=protected-access

        assert_that(mock_connect.call_args.args[:2]).is_equal_to(("otherhost", 9999))

    def test_check_heartbeat_healthy_server_reply_marks_healthy(self):
        self.manager._conn = _healthy_conn()  # pylint: disable=protected-access
        self.manager.state = ServerState.UNHEALTHY

        self.manager._check_heartbeat()  # pylint: disable=protected-access

        assert_that(self.manager.state).is_equal_to(ServerState.HEALTHY)

    def test_check_heartbeat_non_dict_reply_disconnects_without_raising(self):
        conn = _healthy_conn()
        conn.root.heartbeat.return_value = json.dumps(None)
        self.manager._conn = conn  # pylint: disable=protected-access
        self.manager.state = ServerState.HEALTHY

        self.manager._check_heartbeat()  # pylint: disable=protected-access

        assert_that(self.manager.state).is_equal_to(ServerState.DISCONNECTED)
        assert_that(EventManager.get().drain()[-1]).is_instance_of(ServerDisconnectedEvent)

    def test_refresh_devices_malformed_payload_does_not_raise(self):
        conn = _healthy_conn()
        conn.root.devices_list.return_value = json.dumps([{"vendor_id": "abc"}])
        self.manager._conn = conn  # pylint: disable=protected-access

        self.manager._refresh_devices()  # pylint: disable=protected-access

        assert_that(EventManager.get().drain()).is_empty()

    def test_refresh_does_not_push_unchanged_device_and_action_lists(self):
        conn = _healthy_conn()
        conn.root.devices_list.return_value = json.dumps([{"id": "abc123"}])
        self.manager._conn = conn  # pylint: disable=protected-access

        self.manager._refresh_all()  # pylint: disable=protected-access
        first = EventManager.get().drain()
        self.manager._refresh_all()  # pylint: disable=protected-access
        second = EventManager.get().drain()

        assert_that([type(e) for e in first]).contains(DeviceListUpdatedEvent, ActionListUpdatedEvent)
        assert_that(second).is_empty()

    def test_run_once_survives_unexpected_error(self):
        self.manager._run_once = MagicMock(side_effect=[RuntimeError("boom"), 0.0])  # type: ignore[method-assign]
        self.manager._wait = MagicMock(side_effect=lambda _t: self.manager._stop_event.set())  # type: ignore[method-assign]

        self.manager._run()  # pylint: disable=protected-access

        assert_that(self.manager.state).is_equal_to(ServerState.DISCONNECTED)

    def test_request_reconnect_drops_connection_and_pushes_disconnect(self):
        conn = _healthy_conn()
        self.manager._conn = conn  # pylint: disable=protected-access
        self.manager.state = ServerState.HEALTHY
        self.manager.request_reconnect()
        self.manager._try_connect = MagicMock()  # type: ignore[method-assign]
        self.manager._wait = MagicMock()  # type: ignore[method-assign]

        self.manager._run_once(0.0)  # pylint: disable=protected-access

        conn.close.assert_called_once()
        self.manager._try_connect.assert_called_once()  # pylint: disable=protected-access
        assert_that(EventManager.get().drain()[0]).is_instance_of(ServerDisconnectedEvent)

    @patch("decker.client.connection_manager.rpyc.utils.factory.connect")
    def test_try_connect_does_not_overwrite_state_closed_during_initial_pull(self, mock_connect: MagicMock):
        conn = _healthy_conn()
        conn.root.devices_list.side_effect = lambda: (
            self.manager._close_connection(),  # pylint: disable=protected-access
            json.dumps([]),
        )[1]
        mock_connect.return_value = conn

        self.manager._try_connect()  # pylint: disable=protected-access

        assert_that(self.manager.state).is_equal_to(ServerState.DISCONNECTED)

    def test_stop_closes_connection_and_clears_connected(self):
        mock_conn = MagicMock()
        self.manager._conn = mock_conn  # pylint: disable=protected-access
        self.manager.state = ServerState.HEALTHY

        self.manager.stop()

        mock_conn.close.assert_called_once()
        assert_that(self.manager.state).is_equal_to(ServerState.DISCONNECTED)

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
        mock_conn.root.heartbeat.return_value = _heartbeat_payload(DeckerStatusEnum.HEALTHY)
        mock_conn.root.devices_list.return_value = json.dumps([])
        mock_conn.root.plugins_load_failures.return_value = json.dumps([])
        mock_conn.root.plugins_actions_list.return_value = json.dumps(
            [{"plugin_uuid": "p", "plugin_name": "P", "action_uuid": "p.a", "action_name": "A"}]
        )
        self.manager._conn = mock_conn  # pylint: disable=protected-access
        self.manager.state = ServerState.HEALTHY

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
        self.manager = ConnectionManager()

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
