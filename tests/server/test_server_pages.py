"""Tests for the page-aware parts of ServerProcess: hardware key routing and device restore."""

import json
from unittest.mock import MagicMock

from assertpy import assert_that

from decker.common.model import DeviceHardwareInfo
from decker.server.server import ServerProcess

# pylint: disable=protected-access


def _process_with_context() -> tuple[ServerProcess, MagicMock]:
    process = ServerProcess(port=0, startup_wait=0, app_context=MagicMock())
    context = MagicMock()
    context.page_controller.active_page_id.return_value = "p2"
    process._context = context
    return process, context


def _info(device_id: str | None) -> DeviceHardwareInfo:
    return DeviceHardwareInfo(id=device_id, type="Stream Deck", vendor_id=0, product_id=0, num_keys=15)


class TestHardwareKeyEvent:
    def test_routes_press_to_action_on_active_page(self):
        process, context = _process_with_context()
        assignment = MagicMock()
        context.key_assignment_store.get.return_value = assignment

        process._on_hardware_key_event("dev1", 3, True)
        process._on_hardware_key_event("dev1", 3, False)

        context.key_assignment_store.get.assert_called_with("dev1", "p2", 3)
        context.plugin_manager.dispatch_key_down.assert_called_once_with(assignment.target)
        context.plugin_manager.dispatch_key_up.assert_called_once_with(assignment.target)
        event, payload = context.event_bus.push.call_args.args
        assert_that(event).is_equal_to("key_event")
        assert_that(json.loads(payload)).is_equal_to({"device_id": "dev1", "key_index": 3, "pressed": False})

    def test_unassigned_key_still_pushes_event(self):
        process, context = _process_with_context()
        context.key_assignment_store.get.return_value = None

        process._on_hardware_key_event("dev1", 0, True)

        context.plugin_manager.dispatch_key_down.assert_not_called()
        context.event_bus.push.assert_called_once()

    def test_no_context_is_ignored(self):
        ServerProcess(port=0, startup_wait=0, app_context=MagicMock())._on_hardware_key_event("dev1", 0, True)


class TestRestoreDevices:
    def test_restores_every_connected_device(self):
        process, context = _process_with_context()
        context.device_manager.list_devices.return_value = [_info("b"), _info("a"), _info(None)]

        process._restore_devices()

        restored = [c.args[0] for c in context.page_controller.restore.call_args_list]
        assert_that(restored).is_equal_to(["a", "b"])

    def test_filter_restores_only_matching_connected_device(self):
        process, context = _process_with_context()
        context.device_manager.list_devices.return_value = [_info("a"), _info("b")]

        process._restore_devices(device_id_filter="b")
        process._restore_devices(device_id_filter="missing")

        context.page_controller.restore.assert_called_once_with("b")

    def test_no_context_is_ignored(self):
        ServerProcess(port=0, startup_wait=0, app_context=MagicMock())._restore_devices()
