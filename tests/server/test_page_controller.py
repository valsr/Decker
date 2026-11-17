import json
import threading
from typing import cast
from unittest.mock import MagicMock, call

import pytest
from assertpy import assert_that

from decker.plugin.target import ActionTarget
from decker.server.device_state_store import DeviceStateStore
from decker.server.key_assignments import KeyAssignmentStore
from decker.server.page_controller import PAGES_CHANGED_EVENT, PageController
from decker.server.pages import PageStore, initial_page_id
from decker.server.server_context import ServerContext

DEV = "dev1"
PAGE1 = initial_page_id(DEV)


def _target(key_index: int, ctx: str) -> ActionTarget:
    return ActionTarget(plugin_uuid="com.p", action_uuid="com.p.a", context_id=ctx, device_id=DEV, key_index=key_index)


@pytest.fixture()
def context(tmp_path):
    pages = PageStore(db_path=tmp_path / "decker.db")
    keys = KeyAssignmentStore(db_path=tmp_path / "decker.db")
    states = DeviceStateStore(data_dir=tmp_path)
    controller = PageController()
    device_manager = MagicMock()
    device_manager.show_page.return_value = True
    ctx = ServerContext(
        device_manager=device_manager,
        plugin_manager=MagicMock(),
        key_assignment_store=keys,
        device_state_store=states,
        page_store=pages,
        page_controller=controller,
        event_bus=MagicMock(),
    )
    for manager in (pages, keys, states, controller):
        manager.create(ctx)
    yield ctx
    for manager in (controller, states, keys, pages):
        manager.destroy()


def _events(context: ServerContext) -> list[tuple[str, dict]]:
    push = cast(MagicMock, context.event_bus.push)
    return [(c.args[0], json.loads(c.args[1])) for c in push.call_args_list]


class TestActivePage:
    def test_starts_on_default_page(self, context):
        page = context.page_store.add_page(DEV)
        context.page_store.set_default_page(DEV, page.page_id)

        assert_that(context.page_controller.active_page_id(DEV)).is_equal_to(page.page_id)

    def test_recorded_active_page_is_read_without_the_lock(self, context):
        controller = context.page_controller
        expected = controller.active_page_id(DEV)
        result: list[str] = []

        with controller._lock:  # pylint: disable=protected-access
            thread = threading.Thread(target=lambda: result.append(controller.active_page_id(DEV)))
            thread.start()
            thread.join(2)
            finished = not thread.is_alive()

        assert_that(finished).is_true()
        assert_that(result).is_equal_to([expected])

    def test_device_pages_snapshot(self, context):
        page = context.page_controller.add_page(DEV, "Media")
        context.page_controller.activate(DEV, page.page_id)

        snapshot = context.page_controller.device_pages(DEV)

        assert_that([p.name for p in snapshot.pages]).is_equal_to(["Page 1", "Media"])
        assert_that(snapshot.default_page_id).is_equal_to(PAGE1)
        assert_that(snapshot.active_page_id).is_equal_to(page.page_id)


class TestActivate:
    def test_switch_deactivates_old_shows_new_then_activates_new(self, context):
        page2 = context.page_store.add_page(DEV)
        old, new = _target(0, "old"), _target(0, "new")
        context.key_assignment_store.assign(DEV, PAGE1, 0, old, {})
        context.key_assignment_store.assign(DEV, page2.page_id, 0, new, {"step": 2})
        tracker = MagicMock()
        tracker.attach_mock(context.plugin_manager, "pm")
        tracker.attach_mock(context.device_manager, "dm")

        assert_that(context.page_controller.activate(DEV, page2.page_id)).is_true()

        assert_that(tracker.mock_calls).is_equal_to(
            [
                call.pm.deactivate_action(old),
                call.dm.show_page(DEV, page2.page_id),
                call.pm.store_settings(new, {"step": 2}),
                call.pm.activate_action(new, {}),
                call.pm.refresh_page_dependent(DEV),
            ]
        )
        assert_that(context.page_controller.active_page_id(DEV)).is_equal_to(page2.page_id)
        assert_that(_events(context)[-1]).is_equal_to((PAGES_CHANGED_EVENT, {"device_id": DEV}))

    def test_activating_current_page_does_not_redraw(self, context):
        assert_that(context.page_controller.activate(DEV, PAGE1)).is_true()

        context.device_manager.show_page.assert_not_called()

    def test_unknown_page_is_refused(self, context):
        assert_that(context.page_controller.activate(DEV, "nope")).is_false()
        context.event_bus.push.assert_not_called()

    def test_unavailable_device_still_switches(self, context):
        page2 = context.page_store.add_page(DEV)
        context.device_manager.show_page.return_value = False

        assert_that(context.page_controller.activate(DEV, page2.page_id)).is_true()
        assert_that(context.page_controller.active_page_id(DEV)).is_equal_to(page2.page_id)


class TestRestore:
    def test_shows_active_page_and_activates_its_actions(self, context):
        target = _target(3, "c3")
        context.key_assignment_store.assign(DEV, PAGE1, 3, target, {"x": 1})

        context.page_controller.restore(DEV)

        context.device_manager.show_page.assert_called_once_with(DEV, PAGE1)
        context.plugin_manager.store_settings.assert_called_once_with(target, {"x": 1})
        context.plugin_manager.activate_action.assert_called_once_with(target, {})


class TestEditing:
    def test_add_rename_set_default_notify(self, context):
        page = context.page_controller.add_page(DEV)

        assert_that(context.page_controller.rename_page(DEV, page.page_id, "Media")).is_true()
        assert_that(context.page_controller.set_default_page(DEV, page.page_id)).is_true()

        assert_that(_events(context)).is_length(3)
        assert_that(context.page_store.default_page_id(DEV)).is_equal_to(page.page_id)
        context.device_manager.show_page.assert_not_called()

    def test_failed_edits_do_not_notify(self, context):
        assert_that(context.page_controller.rename_page(DEV, "nope", "x")).is_false()
        assert_that(context.page_controller.set_default_page(DEV, "nope")).is_false()

        context.event_bus.push.assert_not_called()


class TestDeletePage:
    def test_deleting_inactive_page_removes_its_data(self, context):
        page2 = context.page_store.add_page(DEV)
        context.key_assignment_store.assign(DEV, page2.page_id, 0, _target(0, "c"), {})
        context.device_state_store.save_key_label(DEV, page2.page_id, 0, "x")

        assert_that(context.page_controller.delete_page(DEV, page2.page_id)).is_true()

        assert_that(context.key_assignment_store.all_for_page(DEV, page2.page_id)).is_empty()
        assert_that(context.device_state_store.get_all_key_labels(DEV, page2.page_id)).is_empty()
        assert_that(context.page_store.get(DEV, page2.page_id)).is_none()
        context.plugin_manager.deactivate_action.assert_not_called()
        context.device_manager.show_page.assert_not_called()

    def test_deleting_active_page_moves_to_next_page(self, context):
        page2 = context.page_store.add_page(DEV)
        page3 = context.page_store.add_page(DEV)
        context.page_controller.activate(DEV, page2.page_id)
        live = _target(0, "live")
        context.key_assignment_store.assign(DEV, page2.page_id, 0, live, {})

        context.page_controller.delete_page(DEV, page2.page_id)

        context.plugin_manager.deactivate_action.assert_called_once_with(live)
        assert_that(context.page_controller.active_page_id(DEV)).is_equal_to(page3.page_id)

    def test_deleting_active_last_page_moves_to_previous_page(self, context):
        page2 = context.page_store.add_page(DEV)
        context.page_controller.activate(DEV, page2.page_id)

        context.page_controller.delete_page(DEV, page2.page_id)

        assert_that(context.page_controller.active_page_id(DEV)).is_equal_to(PAGE1)
        context.device_manager.show_page.assert_called_with(DEV, PAGE1)

    def test_cannot_delete_last_or_unknown_page(self, context):
        assert_that(context.page_controller.delete_page(DEV, PAGE1)).is_false()
        assert_that(context.page_controller.delete_page(DEV, "nope")).is_false()
        context.event_bus.push.assert_not_called()

    def test_active_page_falls_back_if_deleted_elsewhere(self, context):
        page2 = context.page_store.add_page(DEV)
        context.page_controller.activate(DEV, page2.page_id)
        context.page_store.delete_page(DEV, page2.page_id)

        assert_that(context.page_controller.active_page_id(DEV)).is_equal_to(PAGE1)


class TestNotifyRefreshesPlugins:
    @pytest.mark.parametrize("operation", ["add", "rename", "delete", "activate"])
    def test_notify_refreshes_the_plugin_manager(self, context, operation):
        second = context.page_store.add_page(DEV)
        manager = cast(MagicMock, context.plugin_manager)
        manager.refresh_page_dependent.reset_mock()
        lock_free: list[bool] = []

        def _probe(_device_id: str) -> None:
            def _try() -> None:
                lock = context.page_controller._lock  # pylint: disable=protected-access
                got = lock.acquire(blocking=False)
                lock_free.append(got)
                if got:
                    lock.release()

            thread = threading.Thread(target=_try)
            thread.start()
            thread.join()

        manager.refresh_page_dependent.side_effect = _probe
        controller = context.page_controller
        if operation == "add":
            controller.add_page(DEV)
        elif operation == "rename":
            controller.rename_page(DEV, second.page_id, "Renamed")
        elif operation == "delete":
            controller.delete_page(DEV, second.page_id)
        else:
            controller.activate(DEV, second.page_id)

        assert_that(manager.refresh_page_dependent.call_args_list).is_equal_to([call(DEV)])
        assert_that(lock_free).is_equal_to([True])
