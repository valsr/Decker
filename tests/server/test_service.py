import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that

from decker.plugin.context import ActionTarget
from decker.plugin.events import PluginLoadFailedEvent
from decker.server.key_assignments import KeyAssignmentStore
from decker.server.server_context import ServerContext
from decker.server.service import DeckerService


def _make_target(device_id="dev1", key_index=0, plugin="com.p", action="com.p.a", ctx="ctx1"):
    return ActionTarget(
        plugin_uuid=plugin, action_uuid=action, context_id=ctx, device_id=device_id, key_index=key_index
    )


def _make_context(plugin_manager: MagicMock, store: KeyAssignmentStore) -> ServerContext:
    return ServerContext(
        device_manager=MagicMock(),
        plugin_manager=plugin_manager,
        icon_pack_manager=MagicMock(),
        key_assignment_store=store,
    )


@pytest.fixture(autouse=True)
def _reset_service():
    """Ensure class-level state is clean for each test."""
    DeckerService._context = None  # pylint: disable=protected-access
    yield
    DeckerService._context = None  # pylint: disable=protected-access


@pytest.fixture()
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        s = KeyAssignmentStore(db_path=Path(tmpdir) / "test.db")
        s.create(MagicMock())
        yield s
        s.destroy()


@pytest.fixture()
def manager():
    return MagicMock()


@pytest.fixture()
def service(store, manager):
    DeckerService.configure_context(_make_context(manager, store))
    return DeckerService()


class TestHeartbeatStatusDevices:
    def test_heartbeat_returns_healthy(self):
        s = DeckerService()
        result = json.loads(s.heartbeat())
        assert_that(result).is_instance_of(dict)
        assert_that(result["service_status"]).is_equal_to("healthy")

    def test_status_returns_healthy(self):
        s = DeckerService()
        result = json.loads(s.status())
        assert_that(result).is_instance_of(dict)
        assert_that(result["service_status"]).is_equal_to("healthy")

    def test_devices_list_returns_list(self):
        s = DeckerService()
        result = json.loads(s.devices_list())  # no context → returns []
        assert_that(result).is_equal_to([])

    def test_on_connect_and_disconnect_do_not_raise(self):
        s = DeckerService()
        s.on_connect(MagicMock())
        s.on_disconnect(MagicMock())

    def test_commands_returns_dict(self):
        s = DeckerService()
        result = json.loads(s.commands())
        assert_that(result).is_instance_of(dict)
        assert_that(result).contains_key("heartbeat")

    def test_stop_returns_false_without_server(self):
        s = DeckerService()
        assert_that(s.stop()).is_false()


class TestKeySimulateLongPress:
    def test_simulate_long_press_dispatches_key_down_and_up(self, store, manager):
        DeckerService.configure_context(_make_context(manager, store))
        target = _make_target()
        store.assign("dev1", 0, target, {})
        s = DeckerService()
        with patch("decker.server.service.time.sleep") as mock_sleep:
            result = s.key_simulate_long_press("dev1", 0)
        assert_that(result).is_true()
        mock_sleep.assert_called_once()
        manager.dispatch_key_down.assert_called_once_with(target)
        manager.dispatch_key_up.assert_called_once_with(target)


class TestPluginsLoadFailures:
    def test_returns_empty_list_when_no_context_configured(self):
        assert_that(json.loads(DeckerService().plugins_load_failures())).is_equal_to([])

    def test_returns_failures_from_plugin_manager(self, store, manager):
        manager.load_failures.return_value = [PluginLoadFailedEvent(plugin_uuid="com.decker.broken", error="boom")]
        DeckerService.configure_context(_make_context(manager, store))
        result = json.loads(DeckerService().plugins_load_failures())
        assert_that(result).is_equal_to([{"plugin_uuid": "com.decker.broken", "error": "boom"}])


class TestPluginsActionsList:
    def test_returns_empty_list_when_no_context_configured(self):
        assert_that(json.loads(DeckerService().plugins_actions_list())).is_equal_to([])

    def test_returns_actions_from_plugin_manager(self, store, manager):
        manager.list_actions.return_value = [
            {"plugin_uuid": "p", "plugin_name": "P", "action_uuid": "p.a", "action_name": "A"}
        ]
        DeckerService.configure_context(_make_context(manager, store))
        result = json.loads(DeckerService().plugins_actions_list())
        assert_that(result).is_equal_to(
            [{"plugin_uuid": "p", "plugin_name": "P", "action_uuid": "p.a", "action_name": "A"}]
        )


class TestKeyAssign:
    def test_assign_activates_action(self, service, manager, store):
        result = service.key_assign("dev1", 0, "com.p", "com.p.a", "ctx1", json.dumps({"step": 2}))
        assert_that(result).is_true()
        manager.activate_action.assert_called_once()
        assert_that(store.get("dev1", 0)).is_not_none()

    def test_assign_deactivates_previous_if_exists(self, service, manager, store):
        target = _make_target()
        store.assign("dev1", 0, target, {})
        service.key_assign("dev1", 0, "com.q", "com.q.b", "ctx2")
        manager.deactivate_action.assert_called_once_with(target)

    def test_assign_returns_false_without_context(self):
        s = DeckerService()
        assert_that(s.key_assign("dev1", 0, "p", "a", "c")).is_false()

    def test_assign_opens_device_via_device_manager(self, store, manager):
        dm = MagicMock()
        DeckerService.configure_context(
            ServerContext(
                device_manager=dm, plugin_manager=manager, icon_pack_manager=MagicMock(), key_assignment_store=store
            )
        )
        DeckerService().key_assign("dev1", 0, "com.p", "com.p.a", "ctx1")
        dm.open_device.assert_called_with("dev1")


class TestKeyUnassign:
    def test_unassign_deactivates_action(self, service, manager, store):
        target = _make_target()
        store.assign("dev1", 0, target, {})
        result = service.key_unassign("dev1", 0)
        assert_that(result).is_true()
        manager.deactivate_action.assert_called_once_with(target)
        assert_that(store.get("dev1", 0)).is_none()

    def test_unassign_returns_false_when_unassigned(self, service, manager):
        result = service.key_unassign("dev1", 0)
        assert_that(result).is_false()
        manager.deactivate_action.assert_not_called()

    def test_unassign_returns_false_without_context(self):
        s = DeckerService()
        assert_that(s.key_unassign("dev1", 0)).is_false()


class TestKeyUpdateSettings:
    def test_update_settings_dispatches_settings_changed(self, service, manager, store):
        target = _make_target()
        store.assign("dev1", 0, target, {"step": 1})
        result = service.key_update_settings("dev1", 0, json.dumps({"step": 5}))
        assert_that(result).is_true()
        manager.dispatch_settings_changed.assert_called_once_with(target)

    def test_update_settings_returns_false_for_unassigned_slot(self, service, manager):
        result = service.key_update_settings("dev1", 99, json.dumps({"step": 1}))
        assert_that(result).is_false()
        manager.dispatch_settings_changed.assert_not_called()


class TestKeyGetDisplayStates:
    def test_returns_empty_without_context(self):
        assert_that(json.loads(DeckerService().key_get_display_states("dev1"))).is_empty()

    def test_returns_states_with_labels(self, service, manager, store):
        target = _make_target()
        store.assign("dev1", 0, target, {"step": 2})
        manager.get_key_display_states.return_value = [{"key_index": 0, "label": "5"}]
        states = json.loads(service.key_get_display_states("dev1"))
        assert_that(states).is_length(1)
        assert_that(states[0]["label"]).is_equal_to("5")
        assert_that(states[0]["key_index"]).is_equal_to(0)
        assert_that(states[0]["plugin_uuid"]).is_equal_to("com.p")


class TestKeySimulatePress:
    def test_simulate_press_dispatches_key_down_and_up(self, service, manager, store):
        target = _make_target()
        store.assign("dev1", 0, target, {})
        result = service.key_simulate_press("dev1", 0)
        assert_that(result).is_true()
        manager.dispatch_key_down.assert_called_once_with(target)
        manager.dispatch_key_up.assert_called_once_with(target)

    def test_simulate_press_returns_false_for_unassigned_slot(self, service, manager):
        result = service.key_simulate_press("dev1", 99)
        assert_that(result).is_false()
        manager.dispatch_key_down.assert_not_called()
