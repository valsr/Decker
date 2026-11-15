import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that

from decker.plugin.events import PluginLoadFailedEvent
from decker.plugin.target import ActionTarget
from decker.server.key_assignments import KeyAssignmentStore
from decker.server.page_controller import PageController
from decker.server.pages import PageStore, initial_page_id
from decker.server.server_context import ServerContext
from decker.server.service import DeckerService

P1 = initial_page_id("dev1")


def _make_target(device_id="dev1", key_index=0, plugin="com.p", action="com.p.a", ctx="ctx1"):
    return ActionTarget(
        plugin_uuid=plugin, action_uuid=action, context_id=ctx, device_id=device_id, key_index=key_index
    )


def _make_context(plugin_manager: MagicMock, store: KeyAssignmentStore, device_manager=None) -> ServerContext:
    """A context with real page and key stores (sharing one database) and mocked hardware/plugins."""
    page_store = PageStore(db_path=store._db_path)  # pylint: disable=protected-access
    controller = PageController()
    dm = device_manager or MagicMock()
    dm.show_page.return_value = True
    ctx = ServerContext(
        device_manager=dm,
        plugin_manager=plugin_manager,
        icon_pack_manager=MagicMock(),
        key_assignment_store=store,
        device_state_store=MagicMock(),
        page_store=page_store,
        page_controller=controller,
        event_bus=MagicMock(),
    )
    page_store.create(ctx)
    controller.create(ctx)
    return ctx


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
    mock = MagicMock()
    mock.complete_settings.side_effect = lambda _target, settings: settings
    mock.appearance_for.side_effect = lambda _target, stored: (dict(stored), {"background": "#000000"})
    return mock


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
        store.assign("dev1", P1, 0, target, {})
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
        result = service.key_assign("dev1", P1, 0, "com.p", "com.p.a", "ctx1", json.dumps({"step": 2}))
        assert_that(result).is_true()
        manager.activate_action.assert_called_once()
        assert_that(store.get("dev1", P1, 0)).is_not_none()

    def test_assign_deactivates_previous_if_exists(self, service, manager, store):
        target = _make_target()
        store.assign("dev1", P1, 0, target, {})
        service.key_assign("dev1", P1, 0, "com.q", "com.q.b", "ctx2")
        manager.deactivate_action.assert_called_once_with(target)

    def test_assign_returns_false_without_context(self):
        s = DeckerService()
        assert_that(s.key_assign("dev1", P1, 0, "p", "a", "c")).is_false()

    def test_assign_opens_device_via_device_manager(self, store, manager):
        dm = MagicMock()
        DeckerService.configure_context(_make_context(manager, store, device_manager=dm))
        DeckerService().key_assign("dev1", P1, 0, "com.p", "com.p.a", "ctx1")
        dm.open_device.assert_called_with("dev1")


class TestKeyUnassign:
    def test_unassign_deactivates_action(self, service, manager, store):
        target = _make_target()
        store.assign("dev1", P1, 0, target, {})
        result = service.key_unassign("dev1", P1, 0)
        assert_that(result).is_true()
        manager.deactivate_action.assert_called_once_with(target)
        assert_that(store.get("dev1", P1, 0)).is_none()

    def test_unassign_returns_false_when_unassigned(self, service, manager):
        result = service.key_unassign("dev1", P1, 0)
        assert_that(result).is_false()
        manager.deactivate_action.assert_not_called()

    def test_unassign_returns_false_without_context(self):
        s = DeckerService()
        assert_that(s.key_unassign("dev1", P1, 0)).is_false()


class TestKeyUpdateSettings:
    def test_update_settings_dispatches_settings_changed(self, service, manager, store):
        target = _make_target()
        store.assign("dev1", P1, 0, target, {"step": 1})
        result = service.key_update_settings("dev1", P1, 0, json.dumps({"step": 5}))
        assert_that(result).is_true()
        manager.dispatch_settings_changed.assert_called_once_with(target)

    def test_update_settings_returns_false_for_unassigned_slot(self, service, manager):
        result = service.key_update_settings("dev1", P1, 99, json.dumps({"step": 1}))
        assert_that(result).is_false()
        manager.dispatch_settings_changed.assert_not_called()


class TestKeyUpdateAppearance:
    def test_key_update_appearance_rpc(self, service, manager, store):
        target = _make_target()
        store.assign("dev1", P1, 0, target, {})

        result = service.key_update_appearance(
            "dev1", P1, 0, json.dumps({"background": "#ff0000", "title": "A", "bogus": 1})
        )

        assert_that(result).is_true()
        assert_that(store.get("dev1", P1, 0).appearance).is_equal_to({"background": "#ff0000", "title": "A"})
        manager.set_appearance.assert_called_once_with(target, {"background": "#ff0000", "title": "A"})
        manager.dispatch_settings_changed.assert_not_called()

    def test_unassigned_slot_returns_false(self, service, manager):
        assert_that(service.key_update_appearance("dev1", P1, 5, "{}")).is_false()
        manager.set_appearance.assert_not_called()

    def test_non_object_json_is_rejected(self, service, store):
        store.assign("dev1", P1, 0, _make_target(), {})

        assert_that(service.key_update_appearance("dev1", P1, 0, "[1]")).is_false()

    def test_inactive_page_is_stored_without_redraw(self, service, manager, store):
        page2 = service._context.page_store.add_page("dev1").page_id  # pylint: disable=protected-access
        store.assign("dev1", page2, 0, _make_target(), {})

        assert_that(service.key_update_appearance("dev1", page2, 0, json.dumps({"title": "x"}))).is_true()

        manager.set_appearance.assert_not_called()

    def test_without_context_returns_false(self):
        assert_that(DeckerService().key_update_appearance("dev1", P1, 0, "{}")).is_false()


class TestKeyGetStates:
    def _make_mock_device(self, num_keys: int = 2):
        from decker.common.model import (  # pylint: disable=import-outside-toplevel
            DeviceHardwareInfo,
            KeyInfo,
            KeyPressState,
        )

        mock_device = MagicMock()
        mock_device.get_hw_info.return_value = DeviceHardwareInfo(
            id="dev1",
            type="StreamDeck",
            vendor_id=4057,
            product_id=96,
            num_keys=num_keys,
            keys=[KeyInfo(row=0, col=c, pixel_width=72, pixel_height=72, type="key") for c in range(num_keys)],
        )
        mock_device.get_key_state.return_value = KeyPressState.UP
        return mock_device

    def _make_mock_device_state(self, labels: dict[int, str] | None = None, images: dict[int, bytes] | None = None):
        from decker.common.model import (
            KeyPressState,  # pylint: disable=import-outside-toplevel
        )
        from decker.server.devices.state import (
            PerKeyState,  # pylint: disable=import-outside-toplevel
        )

        labels = labels or {}
        images = images or {}

        def _get_key_state(key_index: int) -> PerKeyState:
            return PerKeyState(
                key_index=key_index,
                image=images.get(key_index),
                label=labels.get(key_index, ""),
                press_state=KeyPressState.UP,
            )

        mock_ds = MagicMock()
        mock_ds.get_key_state.side_effect = _get_key_state
        return mock_ds

    def test_returns_empty_without_context(self):
        assert_that(json.loads(DeckerService().key_get_states("dev1"))).is_empty()

    def test_returns_empty_when_device_not_found(self, service):
        service._context.device_manager.open_device.return_value = None  # pylint: disable=protected-access
        result = json.loads(service.key_get_states("dev1"))
        assert_that(result).is_empty()

    def test_returns_all_keys_including_unassigned(self, service, manager, store):
        mock_device = self._make_mock_device(num_keys=2)
        mock_ds = self._make_mock_device_state(labels={0: "vol"})
        service._context.device_manager.open_device.return_value = mock_device  # pylint: disable=protected-access
        service._context.device_manager.get_device_state.return_value = mock_ds  # pylint: disable=protected-access
        target = _make_target()
        store.assign("dev1", P1, 0, target, {"step": 2})

        states = json.loads(service.key_get_states("dev1"))

        assert_that(states).is_length(2)
        assert_that(states[0]["key_index"]).is_equal_to(0)
        assert_that(states[0]["label"]).is_equal_to("vol")
        assert_that(states[0]["plugin_uuid"]).is_equal_to("com.p")
        assert_that(states[0]["state"]).is_equal_to("up")
        assert_that(states[0]["image_b64"]).is_none()
        assert_that(states[1]["key_index"]).is_equal_to(1)
        assert_that(states[1]["plugin_uuid"]).is_none()
        assert_that(states[1]["label"]).is_equal_to("")

    def test_states_carry_appearance_and_defaults(self, service, store):
        service._context.device_manager.open_device.return_value = self._make_mock_device(
            num_keys=2
        )  # pylint: disable=protected-access
        service._context.device_manager.get_device_state.return_value = (  # pylint: disable=protected-access
            self._make_mock_device_state()
        )
        store.assign("dev1", P1, 0, _make_target(), {})
        store.update_appearance("dev1", P1, 0, {"title": "Hi"})

        states = json.loads(service.key_get_states("dev1"))

        assert_that(states[0]["appearance"]).is_equal_to({"title": "Hi"})
        assert_that(states[0]["appearance_defaults"]).is_equal_to({"background": "#000000"})
        assert_that(states[1]["appearance"]).is_equal_to({})

    def test_returns_key_image_as_base64(self, service, store):
        import base64  # pylint: disable=import-outside-toplevel

        mock_device = self._make_mock_device(num_keys=1)
        mock_ds = self._make_mock_device_state(images={0: b"\x89PNG"})
        service._context.device_manager.open_device.return_value = mock_device  # pylint: disable=protected-access
        service._context.device_manager.get_device_state.return_value = mock_ds  # pylint: disable=protected-access

        states = json.loads(service.key_get_states("dev1"))

        assert_that(states[0]["image_b64"]).is_equal_to(base64.b64encode(b"\x89PNG").decode())


class TestKeySimulatePress:
    def test_simulate_press_dispatches_key_down_and_up(self, service, manager, store):
        target = _make_target()
        store.assign("dev1", P1, 0, target, {})
        result = service.key_simulate_press("dev1", 0)
        assert_that(result).is_true()
        manager.dispatch_key_down.assert_called_once_with(target)
        manager.dispatch_key_up.assert_called_once_with(target)

    def test_simulate_press_returns_false_for_unassigned_slot(self, service, manager):
        result = service.key_simulate_press("dev1", 99)
        assert_that(result).is_false()
        manager.dispatch_key_down.assert_not_called()


class TestKeysOnInactivePage:
    @pytest.fixture()
    def page2(self, service):
        return service._context.page_store.add_page("dev1").page_id  # pylint: disable=protected-access

    def test_assign_to_inactive_page_stores_without_activating(self, service, manager, store, page2):
        assert_that(service.key_assign("dev1", page2, 0, "com.p", "com.p.a", "c", json.dumps({"step": 4}))).is_true()

        manager.activate_action.assert_not_called()
        manager.store_settings.assert_called_once()
        saved = store.get("dev1", page2, 0)
        assert saved is not None
        assert_that(saved.settings).is_equal_to({"step": 4})

    def test_assign_to_unknown_page_is_refused(self, service, manager, store):
        assert_that(service.key_assign("dev1", "nope", 0, "com.p", "com.p.a", "c")).is_false()
        assert_that(store.get("dev1", "nope", 0)).is_none()

    def test_unassign_on_inactive_page_clears_only_stored_state(self, service, manager, store, page2):
        store.assign("dev1", page2, 0, _make_target(), {})

        assert_that(service.key_unassign("dev1", page2, 0)).is_true()

        manager.deactivate_action.assert_not_called()
        ctx = service._context  # pylint: disable=protected-access
        ctx.device_state_store.delete_key_state.assert_called_once_with("dev1", page2, 0)
        ctx.device_manager.clear_key_state.assert_not_called()

    def test_update_settings_on_inactive_page_does_not_notify_plugin(self, service, manager, store, page2):
        store.assign("dev1", page2, 0, _make_target(), {"step": 1})

        assert_that(service.key_update_settings("dev1", page2, 0, json.dumps({"step": 2}))).is_true()

        manager.dispatch_settings_changed.assert_not_called()
        manager.store_settings.assert_called_once()

    def test_get_states_and_simulate_press_use_active_page(self, service, manager, store, page2):
        on_page2 = _make_target(ctx="p2")
        store.assign("dev1", page2, 0, on_page2, {})
        assert_that(service.key_simulate_press("dev1", 0)).is_false()

        service.page_activate("dev1", page2)

        assert_that(service.key_simulate_press("dev1", 0)).is_true()
        manager.dispatch_key_down.assert_called_once_with(on_page2)


class TestPageRpcs:
    def test_without_context(self):
        s = DeckerService()
        assert_that(json.loads(s.pages_list("dev1"))).is_none()
        assert_that(json.loads(s.page_add("dev1"))).is_none()
        assert_that(s.page_rename("dev1", P1, "x")).is_false()
        assert_that(s.page_delete("dev1", P1)).is_false()
        assert_that(s.page_set_default("dev1", P1)).is_false()
        assert_that(s.page_activate("dev1", P1)).is_false()

    def test_pages_list(self, service):
        result = json.loads(service.pages_list("dev1"))

        assert_that(result).is_equal_to(
            {
                "device_id": "dev1",
                "pages": [{"page_id": P1, "name": "Page 1"}],
                "default_page_id": P1,
                "active_page_id": P1,
            }
        )

    def test_add_rename_default_activate_delete(self, service):
        page = json.loads(service.page_add("dev1", "Media"))
        assert_that(page["name"]).is_equal_to("Media")
        assert_that(json.loads(service.page_add("dev1"))["name"]).is_equal_to("Page 2")

        assert_that(service.page_rename("dev1", page["page_id"], "Audio")).is_true()
        assert_that(service.page_set_default("dev1", page["page_id"])).is_true()
        assert_that(service.page_activate("dev1", page["page_id"])).is_true()

        listing = json.loads(service.pages_list("dev1"))
        assert_that([p["name"] for p in listing["pages"]]).is_equal_to(["Page 1", "Audio", "Page 2"])
        assert_that(listing["default_page_id"]).is_equal_to(page["page_id"])
        assert_that(listing["active_page_id"]).is_equal_to(page["page_id"])

        assert_that(service.page_delete("dev1", page["page_id"])).is_true()
        assert_that(json.loads(service.pages_list("dev1"))["pages"]).is_length(2)

    def test_page_commands_are_listed(self, service):
        commands = json.loads(service.commands())

        assert_that(commands).contains_key(
            "pages.list", "page.add", "page.rename", "page.delete", "page.set.default", "page.activate"
        )
        assert_that(commands["key.assign"]["params"]).starts_with("device_id, page_id, key_index")
