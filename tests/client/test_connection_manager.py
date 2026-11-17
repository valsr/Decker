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
    OpenUrlRequestedEvent,
    PagesUpdatedEvent,
    PluginInstallFinishedEvent,
    PluginInstallProgressEvent,
    PluginLoadFailedEvent,
    PluginsChangedEvent,
    PluginUpdatesAvailableEvent,
    ProfilesUpdatedEvent,
    RepositoriesCheckFinishedEvent,
    ServerConnectedEvent,
    ServerDisconnectedEvent,
)
from decker.client.events.event_manager import EventManager
from decker.common.model import (
    DeviceHardwareInfo,
    DevicePages,
    DeviceProfiles,
    PageInfo,
    ProfileInfo,
)
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

        def _close_mid_pull() -> str:
            self.manager._close_connection()  # pylint: disable=protected-access
            return json.dumps([])

        conn.root.devices_list.side_effect = _close_mid_pull
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

    def test_upload_call_waits_up_to_120_seconds(self, monkeypatch):
        seen: dict = {}

        class FakeResult:
            value = "job-1"

            def set_expiry(self, timeout):
                seen["timeout"] = timeout

        monkeypatch.setattr(
            "decker.client.connection_manager.async_", lambda fn: lambda *a: (seen.update(args=a), FakeResult())[1]
        )
        self.manager._conn = MagicMock()  # pylint: disable=protected-access

        result = self.manager.call("plugin_install", "x.deckerplugin", b"data")

        assert_that(result).is_equal_to("job-1")
        assert_that(seen["timeout"]).is_equal_to(120.0)
        assert_that(seen["args"]).is_equal_to(("x.deckerplugin", b"data"))

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

    def test_plugin_failed_dispatches_plugin_load_failed_event(self):
        payload = json.dumps({"plugin_id": "com.decker.x", "error": "crashed"})
        self.manager._on_server_event("plugin_failed", payload)  # pylint: disable=protected-access
        events = [e for e in EventManager.get().drain() if isinstance(e, PluginLoadFailedEvent)]
        assert_that(events).is_length(1)
        assert_that(events[0].plugin_uuid).is_equal_to("com.decker.x")
        assert_that(events[0].error).is_equal_to("crashed")

    def test_open_url_event_parsed(self):
        payload = json.dumps({"plugin_id": "com.decker.x", "url": "https://example.com"})
        self.manager._on_server_event("open_url", payload)  # pylint: disable=protected-access
        events = [e for e in EventManager.get().drain() if isinstance(e, OpenUrlRequestedEvent)]
        assert_that(events).is_length(1)
        assert_that(events[0].plugin_id).is_equal_to("com.decker.x")
        assert_that(events[0].url).is_equal_to("https://example.com")

    def test_install_events_become_client_events(self):
        self.manager._on_server_event(  # pylint: disable=protected-access
            "plugin_install_progress", json.dumps({"job_id": "j", "message": "working"})
        )
        self.manager._on_server_event(  # pylint: disable=protected-access
            "plugin_install_finished",
            json.dumps(
                {"job_id": "j", "ok": True, "plugin_id": "a.b", "version": "2", "previous_version": None, "message": ""}
            ),
        )
        events = EventManager.get().drain()
        assert_that([type(e) for e in events]).is_equal_to([PluginInstallProgressEvent, PluginInstallFinishedEvent])
        progress, finished = events
        assert isinstance(progress, PluginInstallProgressEvent) and isinstance(finished, PluginInstallFinishedEvent)
        assert_that(progress.message).is_equal_to("working")
        assert_that(finished.ok).is_true()
        assert_that(finished.previous_version).is_equal_to("")

    def test_plugins_changed_refreshes_action_list(self):
        self.manager._on_server_event("plugins_changed", "{}")  # pylint: disable=protected-access
        assert_that([type(e) for e in EventManager.get().drain()]).is_equal_to([PluginsChangedEvent])
        assert_that(self.manager._actions_refresh_requested.is_set()).is_true()  # pylint: disable=protected-access

        self.manager._conn = MagicMock()  # pylint: disable=protected-access
        self.manager._conn.root.plugins_actions_list.return_value = json.dumps(
            [{"id": "x"}]
        )  # pylint: disable=protected-access
        self.manager._run_once(time.monotonic())  # pylint: disable=protected-access
        events = [e for e in EventManager.get().drain() if isinstance(e, ActionListUpdatedEvent)]
        assert_that(events).is_length(1)

    def test_unknown_event_type_is_silently_ignored(self):
        self.manager._on_server_event("some_future_event", "{}")  # pylint: disable=protected-access
        assert_that(EventManager.get().drain()).is_empty()

    def test_malformed_payload_does_not_raise(self):
        self.manager._on_server_event("key_event", "NOT JSON")  # pylint: disable=protected-access


_DEVICE_PAGES = DevicePages(
    device_id="dev1",
    pages=[PageInfo("p1", "Page 1"), PageInfo("p2", "Media")],
    default_page_id="p1",
    active_page_id="p2",
)


@api_response
def _pages_payload(pages: DevicePages) -> DevicePages:
    """Serialise with the server's own encoder so the wire format can't drift."""
    return pages


class TestPageRefresh:  # pylint: disable=protected-access
    def setup_method(self):
        EventManager.reset()
        AppContext.reset()
        AppContext.get().active_device = DeviceHardwareInfo(
            id="dev1", type="Stream Deck", vendor_id=0, product_id=0, num_keys=15
        )
        self.manager = ConnectionManager()
        self.conn = MagicMock()
        self.conn.root.pages_list.return_value = str(_pages_payload(_DEVICE_PAGES))
        self.conn.root.key_get_states.return_value = json.dumps([])
        self.manager._conn = self.conn

    def teardown_method(self):
        self.manager._conn = None
        AppContext.reset()

    def test_refresh_pages_pushes_parsed_pages(self):
        self.manager._refresh_pages()

        events = [e for e in EventManager.get().drain() if isinstance(e, PagesUpdatedEvent)]
        assert_that(events).is_length(1)
        assert_that(events[0].pages).is_equal_to(_DEVICE_PAGES)
        self.conn.root.pages_list.assert_called_once_with("dev1")

    def test_refresh_pages_without_device_is_a_no_op(self):
        AppContext.reset()

        self.manager._refresh_pages()

        self.conn.root.pages_list.assert_not_called()

    def test_malformed_or_failed_pages_response_is_logged_not_raised(self):
        for reply in (json.dumps([]), json.dumps({"device_id": "dev1", "pages": []}), RuntimeError("down")):
            if isinstance(reply, Exception):
                self.conn.root.pages_list.side_effect = reply
            else:
                self.conn.root.pages_list.return_value = reply

            self.manager._refresh_pages()

        assert_that([e for e in EventManager.get().drain() if isinstance(e, PagesUpdatedEvent)]).is_empty()

    def test_pages_changed_for_active_device_requests_refresh(self):
        self.manager._on_server_event("pages_changed", json.dumps({"device_id": "dev1"}))

        assert_that(self.manager._device_refresh_requested.is_set()).is_true()
        assert_that(self.manager._wake_event.is_set()).is_true()
        self.conn.root.pages_list.assert_not_called()  # fetched later on the worker thread

    def test_pages_changed_for_other_device_is_ignored(self):
        self.manager._on_server_event("pages_changed", json.dumps({"device_id": "other"}))

        assert_that(self.manager._device_refresh_requested.is_set()).is_false()

    def test_worker_handles_refresh_request(self):
        self.manager.request_device_refresh()
        with patch("decker.client.connection_manager._HEARTBEAT_INTERVAL_S", 3600):
            self.manager._run_once(last_heartbeat=time.monotonic())

        self.conn.root.pages_list.assert_called_once_with("dev1")
        self.conn.root.key_get_states.assert_called_once_with("dev1")
        assert_that(self.manager._device_refresh_requested.is_set()).is_false()

    @patch("decker.client.connection_manager.rpyc.utils.factory.connect")
    def test_connect_fetches_pages_for_active_device(self, mock_connect: MagicMock):
        conn = _healthy_conn()
        conn.root.pages_list.return_value = str(_pages_payload(_DEVICE_PAGES))
        conn.root.key_get_states.return_value = json.dumps([])
        mock_connect.return_value = conn
        self.manager._conn = None
        with (
            patch("decker.client.config.get_server_host", return_value="localhost"),
            patch("decker.client.config.get_server_port", return_value=18861),
        ):
            self.manager._try_connect()

        assert_that([e for e in EventManager.get().drain() if isinstance(e, PagesUpdatedEvent)]).is_length(1)
        self.manager._close_connection()

    def test_updates_event_routed(self):
        payload = {"updates": [{"id": "a.b", "name": "B", "installed": "1", "available": "2"}], "missing": []}
        self.manager._on_server_event(
            "plugin_updates_available", json.dumps(payload)
        )  # pylint: disable=protected-access
        (event,) = EventManager.get().drain()
        assert isinstance(event, PluginUpdatesAvailableEvent)
        assert_that(event.updates).is_equal_to(payload["updates"])
        assert_that(event.missing).is_equal_to([])

    def test_check_finished_event_routed(self):
        payload = {"repositories": [{"url": "u", "name": "N", "plugin_count": 1, "last_checked": 1.0, "error": None}]}
        self.manager._on_server_event(
            "repositories_check_finished", json.dumps(payload)
        )  # pylint: disable=protected-access
        (event,) = EventManager.get().drain()
        assert isinstance(event, RepositoriesCheckFinishedEvent)
        assert_that(event.repositories).is_equal_to(payload["repositories"])

    def test_updates_fetched_on_connect(self):
        conn = _healthy_conn()
        conn.root.plugin_updates.return_value = {"updates": [], "missing": [{"id": "m"}]}
        with patch("rpyc.utils.factory.connect", return_value=conn), patch(
            "decker.client.connection_manager.BgServingThread"
        ):
            self.manager._try_connect()  # pylint: disable=protected-access
        events = [e for e in EventManager.get().drain() if isinstance(e, PluginUpdatesAvailableEvent)]
        assert_that(events).is_length(1)
        assert_that(events[0].missing).is_equal_to([{"id": "m"}])


_DEVICE_PROFILES = DeviceProfiles(
    device_id="dev1",
    profiles=[ProfileInfo(0, "Default", ""), ProfileInfo(2, "Work", "pack:a/b.svg")],
    active_profile_id=2,
)


@api_response
def _profiles_payload(profiles: DeviceProfiles) -> DeviceProfiles:
    return profiles


class TestProfileRefresh:  # pylint: disable=protected-access
    def setup_method(self):
        EventManager.reset()
        AppContext.reset()
        AppContext.get().active_device = DeviceHardwareInfo(
            id="dev1", type="Stream Deck", vendor_id=0, product_id=0, num_keys=15
        )
        self.manager = ConnectionManager()
        self.conn = MagicMock()
        self.conn.root.pages_list.return_value = str(_pages_payload(_DEVICE_PAGES))
        self.conn.root.profiles_list.return_value = str(_profiles_payload(_DEVICE_PROFILES))
        self.conn.root.key_get_states.return_value = json.dumps([])
        self.manager._conn = self.conn

    def teardown_method(self):
        self.manager._conn = None
        AppContext.reset()

    def test_refresh_profiles_pushes_parsed_profiles(self):
        self.manager._refresh_profiles()

        events = [e for e in EventManager.get().drain() if isinstance(e, ProfilesUpdatedEvent)]
        assert_that(events).is_length(1)
        assert_that(events[0].profiles).is_equal_to(_DEVICE_PROFILES)
        self.conn.root.profiles_list.assert_called_once_with("dev1")

    def test_malformed_or_failed_profiles_response_is_logged_not_raised(self):
        replies = [json.dumps([]), json.dumps({"device_id": "dev1", "profiles": []}), RuntimeError("down")]
        replies.append(
            json.dumps({"device_id": "d", "profiles": [{"profile_id": "x", "name": "n"}], "active_profile_id": 0})
        )
        for reply in replies:
            if isinstance(reply, Exception):
                self.conn.root.profiles_list.side_effect = reply
            else:
                self.conn.root.profiles_list.return_value = reply

            self.manager._refresh_profiles()

        assert_that([e for e in EventManager.get().drain() if isinstance(e, ProfilesUpdatedEvent)]).is_empty()

    def test_refresh_without_device_is_a_no_op(self):
        AppContext.reset()

        self.manager._refresh_profiles()

        self.conn.root.profiles_list.assert_not_called()

    def test_profiles_changed_for_active_device_requests_refresh(self):
        self.manager._on_server_event("profiles_changed", json.dumps({"device_id": "dev1"}))

        assert_that(self.manager._device_refresh_requested.is_set()).is_true()

    def test_profiles_changed_for_other_device_is_ignored(self):
        self.manager._on_server_event("profiles_changed", json.dumps({"device_id": "other"}))

        assert_that(self.manager._device_refresh_requested.is_set()).is_false()

    def test_device_refresh_fetches_pages_and_profiles(self):
        self.manager._refresh_active_device()

        self.conn.root.pages_list.assert_called_once_with("dev1")
        self.conn.root.profiles_list.assert_called_once_with("dev1")

    def test_pages_carry_their_profile_id(self):
        payload = json.loads(str(_pages_payload(DevicePages("dev1", [PageInfo("p1", "A")], "p1", "p1", profile_id=3))))
        self.conn.root.pages_list.return_value = json.dumps(payload)

        self.manager._refresh_pages()

        pages = [e for e in EventManager.get().drain() if isinstance(e, PagesUpdatedEvent)][0].pages
        assert_that(pages.profile_id).is_equal_to(3)
