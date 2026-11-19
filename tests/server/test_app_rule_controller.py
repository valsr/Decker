import json
from typing import cast
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that

from decker.common.model import AppRule, DefaultRule, MatchCondition
from decker.server.app_rule_controller import (
    APP_RULES_CHANGED_EVENT,
    AppRuleController,
)
from decker.server.app_rule_store import AppRuleStore
from decker.server.device_state_store import DeviceStateStore
from decker.server.key_assignments import KeyAssignmentStore
from decker.server.page_controller import PageController
from decker.server.pages import PageStore
from decker.server.server_context import ServerContext

DEV = "dev1"


@pytest.fixture()
def context(tmp_path):
    db = tmp_path / "decker.db"
    pages, keys, states = PageStore(db_path=db), KeyAssignmentStore(db_path=db), DeviceStateStore(data_dir=tmp_path)
    store, controller = AppRuleStore(db_path=db), AppRuleController()
    ctx = ServerContext(
        device_manager=MagicMock(),
        plugin_manager=MagicMock(),
        key_assignment_store=keys,
        device_state_store=states,
        page_store=pages,
        page_controller=PageController(),
        event_bus=MagicMock(),
        app_rule_store=store,
        app_rule_controller=controller,
    )
    managers = (pages, keys, states, store, controller)
    for manager in managers:
        manager.create(ctx)
    yield ctx
    for manager in reversed(managers):
        manager.destroy()


def _rule(profile_id: int = 0, page_id: str = "", value: str = "firefox", name: str = "Browser") -> AppRule:
    return AppRule("", name, True, [MatchCondition("executable", "contains", value)], profile_id, page_id)


def _controller(context: ServerContext) -> AppRuleController:
    assert context.app_rule_controller is not None
    return context.app_rule_controller


def _events(context: ServerContext) -> list[tuple[str, dict]]:
    push = cast(MagicMock, context.event_bus.push)
    return [(c.args[0], json.loads(c.args[1])) for c in push.call_args_list]


def test_add_rule_rejects_unknown_profile(context):
    assert_that(_controller(context).add_rule(DEV, _rule(profile_id=99))).is_none()
    assert_that(_controller(context).rules(DEV).rules).is_empty()
    assert_that(_events(context)).is_empty()


def test_add_rule_rejects_page_of_another_profile(context):
    other = context.page_store.add_profile(DEV, "Other")
    foreign = context.page_store.default_page_id(DEV, other.profile_id)

    assert_that(_controller(context).add_rule(DEV, _rule(profile_id=0, page_id=foreign))).is_none()
    assert_that(_controller(context).add_rule(DEV, _rule(profile_id=0, page_id="nope"))).is_none()
    assert_that(_controller(context).add_rule(DEV, _rule(profile_id=other.profile_id, page_id=foreign))).is_not_none()


def test_add_rule_rejects_empty_contains_value(context):
    assert_that(_controller(context).add_rule(DEV, _rule(value=""))).is_none()
    assert_that(_controller(context).rules(DEV).rules).is_empty()


def test_add_rule_rejects_blank_name(context):
    assert_that(_controller(context).add_rule(DEV, _rule(name="  "))).is_none()


def test_valid_edit_pushes_app_rules_changed(context):
    controller = _controller(context)
    added = controller.add_rule(DEV, _rule())
    assert added is not None
    assert_that(_events(context)).is_equal_to([(APP_RULES_CHANGED_EVENT, {"device_id": DEV})])

    assert_that(controller.update_rule(DEV, AppRule(added.rule_id, "New", False, [], 0))).is_true()
    assert_that(controller.update_rule(DEV, AppRule("missing", "New", False, [], 0))).is_false()
    second = controller.add_rule(DEV, _rule(value="code"))
    assert second is not None
    assert_that(controller.move_rule(DEV, second.rule_id, 0)).is_true()
    assert_that([r.rule_id for r in controller.rules(DEV).rules]).is_equal_to([second.rule_id, added.rule_id])
    assert_that(controller.delete_rule(DEV, added.rule_id)).is_true()
    assert_that(controller.delete_rule(DEV, added.rule_id)).is_false()
    assert_that(controller.move_rule(DEV, "missing", 0)).is_false()
    assert_that(_events(context)).is_length(5)


def test_update_rule_rejects_invalid_input(context):
    controller = _controller(context)
    added = controller.add_rule(DEV, _rule())
    assert added is not None

    assert_that(controller.update_rule(DEV, AppRule(added.rule_id, "x", True, [], 42))).is_false()
    assert_that(controller.update_rule(DEV, AppRule(added.rule_id, "", True, [], 0))).is_false()
    assert_that(controller.rules(DEV).rules[0].name).is_equal_to("Browser")


def test_set_default_rule_validates_target(context):
    controller = _controller(context)

    assert_that(controller.set_default_rule(DEV, DefaultRule(True, 99))).is_false()
    assert_that(controller.set_default_rule(DEV, DefaultRule(True, 0, "nope"))).is_false()
    assert_that(_events(context)).is_empty()
    assert_that(controller.set_default_rule(DEV, DefaultRule(True, 0))).is_true()
    assert_that(controller.rules(DEV).default_rule).is_equal_to(DefaultRule(True, 0))
    assert_that(_events(context)).is_equal_to([(APP_RULES_CHANGED_EVENT, {"device_id": DEV})])


def test_rule_name_length_cap(context):
    assert_that(_controller(context).add_rule(DEV, _rule(name="n" * 200))).is_not_none()
    assert_that(_controller(context).add_rule(DEV, _rule(name="n" * 201))).is_none()


def test_condition_value_length_cap(context):
    assert_that(_controller(context).add_rule(DEV, _rule(value="v" * 1024))).is_not_none()
    assert_that(_controller(context).add_rule(DEV, _rule(value="v" * 1025))).is_none()


def test_conditions_per_rule_cap(context):
    def with_conditions(count: int) -> AppRule:
        return AppRule("", "R", True, [MatchCondition("executable", "contains", "x")] * count, 0, "")

    assert_that(_controller(context).add_rule(DEV, with_conditions(20))).is_not_none()
    assert_that(_controller(context).add_rule(DEV, with_conditions(21))).is_none()


def test_update_enforces_the_caps_too(context):
    stored = _controller(context).add_rule(DEV, _rule())
    assert stored is not None

    too_long = AppRule(stored.rule_id, "n" * 201, True, stored.conditions, 0, "")

    assert_that(_controller(context).update_rule(DEV, too_long)).is_false()


def test_rules_per_device_cap(context):
    for _ in range(200):
        assert_that(_controller(context).add_rule(DEV, _rule())).is_not_none()

    assert_that(_controller(context).add_rule(DEV, _rule())).is_none()
    assert_that(_controller(context).add_rule("other-device", _rule())).is_not_none()
    assert_that(_controller(context).rules(DEV).rules).is_length(200)
