import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that

from decker.plugin.context import ActionTarget
from decker.plugin.events import PluginLoadFailedEvent
from decker.server.key_assignments import KeyAssignmentStore
from decker.server.service import DeckerService


def _make_target(device_id="dev1", key_index=0, plugin="com.p", action="com.p.a", ctx="ctx1"):
    return ActionTarget(
        plugin_uuid=plugin, action_uuid=action, context_id=ctx, device_id=device_id, key_index=key_index
    )


@pytest.fixture(autouse=True)
def _reset_service():
    """Ensure class-level state is clean for each test."""
    DeckerService._plugin_manager = None  # pylint: disable=protected-access
    DeckerService._key_assignment_store = None  # pylint: disable=protected-access
    yield
    DeckerService._plugin_manager = None  # pylint: disable=protected-access
    DeckerService._key_assignment_store = None  # pylint: disable=protected-access


@pytest.fixture()
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        s = KeyAssignmentStore(db_path=Path(tmpdir) / "test.db")
        yield s
        s.close()


@pytest.fixture()
def manager():
    return MagicMock()


@pytest.fixture()
def service(store, manager):
    DeckerService.configure_plugin_manager(manager)
    DeckerService.configure_key_assignment_store(store)
    return DeckerService()


class TestHeartbeatStatusDevices:
    def test_heartbeat_returns_healthy(self):
        s = DeckerService()
        result = s.heartbeat()
        assert_that(result["status"]).is_equal_to("healthy")

    def test_status_returns_running(self):
        s = DeckerService()
        result = s.status()
        assert_that(result["service_status"]).is_equal_to("running")

    def test_devices_list_returns_list(self):
        s = DeckerService()
        with patch("decker.server.service.list_devices", return_value=[]):
            result = s.devices_list()
        assert_that(result).is_equal_to([])

    def test_on_connect_and_disconnect_do_not_raise(self):
        s = DeckerService()
        s.on_connect(MagicMock())
        s.on_disconnect(MagicMock())

    def test_commands_returns_dict(self):
        s = DeckerService()
        result = s.commands()
        assert_that(result).is_instance_of(dict)
        assert_that(result).contains_key("heartbeat")

    def test_stop_returns_false_without_server(self):
        s = DeckerService()
        assert_that(s.stop()).is_false()


class TestKeySimulateLongPress:
    def test_simulate_long_press_dispatches_key_down_and_up(self, store, manager):
        DeckerService.configure_plugin_manager(manager)
        DeckerService.configure_key_assignment_store(store)
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
    def test_returns_empty_list_when_no_plugin_manager_configured(self):
        assert_that(DeckerService().plugins_load_failures()).is_equal_to([])

    def test_returns_failures_from_plugin_manager(self, manager):
        manager.load_failures.return_value = [PluginLoadFailedEvent(plugin_uuid="com.decker.broken", error="boom")]
        DeckerService.configure_plugin_manager(manager)
        result = DeckerService().plugins_load_failures()
        assert_that(result).is_equal_to([{"plugin_uuid": "com.decker.broken", "error": "boom"}])


class TestPluginsActionsList:
    def test_returns_empty_list_when_no_plugin_manager_configured(self):
        assert_that(DeckerService().plugins_actions_list()).is_equal_to([])

    def test_returns_actions_from_plugin_manager(self, manager):
        manager.list_actions.return_value = [
            {"plugin_uuid": "p", "plugin_name": "P", "action_uuid": "p.a", "action_name": "A"}
        ]
        DeckerService.configure_plugin_manager(manager)
        result = DeckerService().plugins_actions_list()
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

    def test_assign_returns_false_without_store(self, manager):
        DeckerService.configure_plugin_manager(manager)
        s = DeckerService()
        assert_that(s.key_assign("dev1", 0, "p", "a", "c")).is_false()

    def test_assign_opens_device_via_device_runner(self, service, manager):
        runner = MagicMock()
        manager._device_runner = runner  # pylint: disable=protected-access
        service.key_assign("dev1", 0, "com.p", "com.p.a", "ctx1")
        runner.open_device.assert_called_once_with("dev1")


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

    def test_unassign_returns_false_without_store(self, manager):
        DeckerService.configure_plugin_manager(manager)
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
    def test_returns_empty_without_store(self, manager):
        DeckerService.configure_plugin_manager(manager)
        s = DeckerService()
        assert_that(s.key_get_display_states("dev1")).is_empty()

    def test_returns_states_with_labels(self, service, manager, store):
        target = _make_target()
        store.assign("dev1", 0, target, {"step": 2})
        manager.get_key_display_states.return_value = [{"key_index": 0, "label": "5"}]
        states = service.key_get_display_states("dev1")
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
