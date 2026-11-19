from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that

from decker.common.model import AppRule, DefaultRule, MatchCondition, WindowInfo
from decker.server.app_rule_engine import AppRuleEngine
from decker.server.app_rule_store import AppRuleStore
from decker.server.device_state_store import DeviceStateStore
from decker.server.key_assignments import KeyAssignmentStore
from decker.server.page_controller import PageController
from decker.server.pages import PageStore
from decker.server.server_context import ServerContext

DEV = "dev1"
DEV2 = "dev2"
FIREFOX = WindowInfo(window_class="firefox")
KATE = WindowInfo(window_class="kate")
OTHER = WindowInfo(window_class="other")


@pytest.fixture()
def context(tmp_path):
    pages = PageStore(db_path=tmp_path / "decker.db")
    keys = KeyAssignmentStore(db_path=tmp_path / "decker.db")
    states = DeviceStateStore(data_dir=tmp_path)
    controller = PageController()
    rules = AppRuleStore(db_path=tmp_path / "decker.db")
    engine = AppRuleEngine()
    device_manager = MagicMock()
    device_manager.show_page.return_value = True
    device_manager.get_device_state.return_value.has_image.return_value = False
    device_manager.list_devices.return_value = [
        SimpleNamespace(id=DEV),
        SimpleNamespace(id=DEV2),
        SimpleNamespace(id=None),
    ]
    ctx = ServerContext(
        device_manager=device_manager,
        plugin_manager=MagicMock(),
        key_assignment_store=keys,
        device_state_store=states,
        page_store=pages,
        page_controller=controller,
        event_bus=MagicMock(),
        app_rule_store=rules,
        app_rule_engine=engine,
    )
    for manager in (pages, keys, states, rules, controller, engine):
        manager.create(ctx)
    yield ctx
    for manager in (engine, controller, rules, states, keys, pages):
        manager.destroy()


def _rule(window_class: str, profile_id: int, page_id: str = "") -> AppRule:
    return AppRule(
        "", window_class, True, [MatchCondition("window_class", "equals", window_class)], profile_id, page_id
    )


def _profile(ctx: ServerContext, device_id: str = DEV) -> int:
    return ctx.page_controller.add_profile(device_id).profile_id


def _active(ctx: ServerContext, device_id: str = DEV) -> int:
    return ctx.page_controller.active_profile_id(device_id)


def test_matching_rule_activates_profile_default_page(context):
    profile = _profile(context)
    context.app_rule_store.add_rule(DEV, _rule("firefox", profile))

    context.app_rule_engine.on_focus(FIREFOX)

    assert_that(_active(context)).is_equal_to(profile)
    default = context.page_store.default_page_id(DEV, profile)
    assert_that(context.page_controller.active_page_id(DEV)).is_equal_to(default)


def test_rule_with_page_activates_that_page(context):
    profile = _profile(context)
    context.page_store.set_active_profile(DEV, profile)
    page = context.page_controller.add_page(DEV)
    context.page_store.set_active_profile(DEV, 0)
    context.app_rule_store.add_rule(DEV, _rule("firefox", profile, page.page_id))

    context.app_rule_engine.on_focus(FIREFOX)

    assert_that(_active(context)).is_equal_to(profile)
    assert_that(context.page_controller.active_page_id(DEV)).is_equal_to(page.page_id)


def test_missing_page_falls_back_to_profile_default(context):
    profile = _profile(context)
    context.app_rule_store.add_rule(DEV, _rule("firefox", profile, "no-such-page"))

    context.app_rule_engine.on_focus(FIREFOX)

    assert_that(_active(context)).is_equal_to(profile)


def test_no_rule_no_default_changes_nothing(context):
    _profile(context)

    context.app_rule_engine.on_focus(FIREFOX)

    assert_that(_active(context)).is_equal_to(0)


def test_default_rule_applies_when_nothing_matches(context):
    profile = _profile(context)
    context.app_rule_store.set_default_rule(DEV, DefaultRule(True, profile, ""))

    context.app_rule_engine.on_focus(OTHER)

    assert_that(_active(context)).is_equal_to(profile)


def test_manual_switch_sticks_while_target_unchanged(context):
    profile = _profile(context)
    context.app_rule_store.add_rule(DEV, _rule("firefox", profile))
    context.app_rule_store.add_rule(DEV, _rule("firefox2", profile))
    context.app_rule_engine.on_focus(FIREFOX)
    context.page_controller.activate_profile(DEV, 0)

    context.app_rule_engine.on_focus(WindowInfo(window_class="firefox2"))

    assert_that(_active(context)).is_equal_to(0)


def test_returning_after_unmatched_window_reasserts(context):
    profile = _profile(context)
    context.app_rule_store.add_rule(DEV, _rule("firefox", profile))
    context.app_rule_engine.on_focus(FIREFOX)
    context.page_controller.activate_profile(DEV, 0)
    context.app_rule_engine.on_focus(OTHER)

    context.app_rule_engine.on_focus(FIREFOX)

    assert_that(_active(context)).is_equal_to(profile)


def test_already_on_profile_with_no_page_does_nothing(context):
    profile = _profile(context)
    context.page_store.set_active_profile(DEV, profile)
    extra = context.page_controller.add_page(DEV)
    context.page_controller.activate(DEV, extra.page_id)
    context.app_rule_store.add_rule(DEV, _rule("firefox", profile))

    context.app_rule_engine.on_focus(FIREFOX)

    assert_that(context.page_controller.active_page_id(DEV)).is_equal_to(extra.page_id)


def test_evaluate_device_applies_current_window_on_connect(context):
    profile = _profile(context)
    context.app_rule_store.add_rule(DEV, _rule("firefox", profile))
    context.app_rule_engine.evaluate_device(DEV)
    assert_that(_active(context)).is_equal_to(0)
    context.app_rule_engine.on_focus(OTHER)
    context.app_rule_engine.on_focus(FIREFOX)
    context.page_controller.activate_profile(DEV, 0)
    context.app_rule_engine.forget_device(DEV)

    context.app_rule_engine.evaluate_device(DEV)

    assert_that(_active(context)).is_equal_to(profile)


def test_deleted_profile_race_does_not_raise(context):
    context.app_rule_store.add_rule(DEV, _rule("firefox", 42))

    context.app_rule_engine.on_focus(FIREFOX)

    assert_that(_active(context)).is_equal_to(0)


def test_exception_for_one_device_does_not_stop_others(context):
    context.app_rule_store.add_rule(DEV, _rule("firefox", _profile(context, DEV)))
    context.app_rule_store.add_rule(DEV2, _rule("firefox", _profile(context, DEV2)))
    context.page_controller.activate_profile = MagicMock(side_effect=[RuntimeError("boom"), True])

    context.app_rule_engine.on_focus(FIREFOX)

    assert_that(cast(MagicMock, context.page_controller.activate_profile).call_count).is_equal_to(2)


def test_devices_are_independent(context):
    p1 = _profile(context, DEV)
    p2 = _profile(context, DEV2)
    context.app_rule_store.add_rule(DEV, _rule("firefox", p1))
    context.app_rule_store.add_rule(DEV2, _rule("kate", p2))

    context.app_rule_engine.on_focus(FIREFOX)

    assert_that(_active(context, DEV)).is_equal_to(p1)
    assert_that(_active(context, DEV2)).is_equal_to(0)
