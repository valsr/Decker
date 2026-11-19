from dataclasses import replace
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that

from decker.common.model import AppRule, DefaultRule, DeviceRules, MatchCondition
from decker.server.app_rule_store import AppRuleStore


@pytest.fixture()
def store(tmp_path):
    s = AppRuleStore(db_path=tmp_path / "test.db")
    s.create(MagicMock())
    yield s
    s.destroy()


def _rule(name: str, profile_id: int = 1, page_id: str = "") -> AppRule:
    return AppRule("", name, True, [MatchCondition("app_id", "equals", name)], profile_id, page_id)


def _names(store: AppRuleStore, device_id: str = "dev1") -> list[str]:
    return [r.name for r in store.list_rules(device_id).rules]


def test_round_trip_preserves_order_and_conditions(store):
    conditions = [MatchCondition("app_id", "equals", "firefox"), MatchCondition("title", "contains", "Docs")]
    first = store.add_rule("dev1", AppRule("", "Browser", False, conditions, 2, "page-x"))
    second = store.add_rule("dev1", _rule("Editor"))

    rules = store.list_rules("dev1")

    assert_that(rules.device_id).is_equal_to("dev1")
    assert_that(rules.rules).is_equal_to([first, second])
    assert_that(rules.rules[0].conditions).is_equal_to(conditions)
    assert_that(rules.rules[0].enabled).is_false()
    assert_that(rules.rules[0].page_id).is_equal_to("page-x")


def test_add_assigns_unique_ids(store):
    ids = {store.add_rule("dev1", _rule(f"r{i}")).rule_id for i in range(3)}

    assert_that(ids).is_length(3)
    assert_that(ids).does_not_contain("")


def test_move_rule_reorders_and_clamps(store):
    rules = [store.add_rule("dev1", _rule(n)) for n in ("a", "b", "c")]

    assert_that(store.move_rule("dev1", rules[2].rule_id, 0)).is_true()
    assert_that(_names(store)).is_equal_to(["c", "a", "b"])
    assert_that(store.move_rule("dev1", rules[2].rule_id, 99)).is_true()
    assert_that(_names(store)).is_equal_to(["a", "b", "c"])
    assert_that(store.move_rule("dev1", rules[0].rule_id, -5)).is_true()
    assert_that(_names(store)).is_equal_to(["a", "b", "c"])
    assert_that(store.move_rule("dev1", "nope", 0)).is_false()


def test_update_rule_changes_fields_but_not_position(store):
    first = store.add_rule("dev1", _rule("a"))
    store.add_rule("dev1", _rule("b"))

    changed = replace(first, name="renamed", enabled=False, profile_id=3, conditions=[])

    assert_that(store.update_rule("dev1", changed)).is_true()
    assert_that(store.list_rules("dev1").rules[0]).is_equal_to(changed)
    assert_that(_names(store)).is_equal_to(["renamed", "b"])


def test_update_and_delete_unknown_rule_return_false(store):
    assert_that(store.update_rule("dev1", replace(_rule("a"), rule_id="missing"))).is_false()
    assert_that(store.delete_rule("dev1", "missing")).is_false()


def test_delete_rule_removes_it_and_keeps_order_contiguous(store):
    rules = [store.add_rule("dev1", _rule(n)) for n in ("a", "b", "c")]

    assert_that(store.delete_rule("dev1", rules[1].rule_id)).is_true()
    assert_that(_names(store)).is_equal_to(["a", "c"])
    assert_that(store.move_rule("dev1", rules[2].rule_id, 0)).is_true()
    assert_that(_names(store)).is_equal_to(["c", "a"])


def test_rules_are_per_device(store):
    store.add_rule("dev1", _rule("a"))

    assert_that(store.list_rules("dev2").rules).is_empty()


def test_fresh_device_has_disabled_default_rule_for_profile_zero(store):
    rules = store.list_rules("dev1")

    assert_that(rules.rules).is_empty()
    assert_that(rules.default_rule).is_equal_to(DefaultRule(enabled=False, profile_id=0, page_id=""))


def test_set_default_rule_round_trips(store):
    store.set_default_rule("dev1", DefaultRule(True, 2, "page-1"))
    store.set_default_rule("dev1", DefaultRule(True, 3, "page-2"))

    assert_that(store.list_rules("dev1").default_rule).is_equal_to(DefaultRule(True, 3, "page-2"))


def test_profile_deleted_removes_its_rules_and_resets_default_rule(store):
    store.add_rule("dev1", _rule("keep", profile_id=1))
    store.add_rule("dev1", _rule("drop", profile_id=2))
    store.set_default_rule("dev1", DefaultRule(True, 2, "page-1"))

    assert_that(store.profile_deleted("dev1", 2, 0)).is_true()

    rules = store.list_rules("dev1")
    assert_that(_names(store)).is_equal_to(["keep"])
    assert_that(rules.default_rule).is_equal_to(DefaultRule(False, 0, ""))
    assert_that(store.profile_deleted("dev1", 2, 0)).is_false()


def test_page_deleted_clears_page_id_on_rules_and_default_rule(store):
    hit = store.add_rule("dev1", _rule("hit", profile_id=1, page_id="p1"))
    other = store.add_rule("dev1", _rule("other", profile_id=1, page_id="p2"))
    store.set_default_rule("dev1", DefaultRule(True, 1, "p1"))

    assert_that(store.page_deleted("dev1", "p1")).is_true()

    rules = store.list_rules("dev1")
    assert_that(rules.rules).is_equal_to([replace(hit, page_id=""), other])
    assert_that(rules.default_rule).is_equal_to(DefaultRule(True, 1, ""))
    assert_that(store.page_deleted("dev1", "p1")).is_false()
    assert_that(store.page_deleted("dev1", "")).is_false()


def test_data_survives_reopen(tmp_path):
    first = AppRuleStore(db_path=tmp_path / "test.db")
    first.create(MagicMock())
    rule = first.add_rule("dev1", _rule("a", page_id="p"))
    first.set_default_rule("dev1", DefaultRule(True, 4, "p"))
    first.destroy()

    second = AppRuleStore(db_path=tmp_path / "test.db")
    second.create(MagicMock())

    assert_that(second.list_rules("dev1")).is_equal_to(DeviceRules("dev1", [rule], DefaultRule(True, 4, "p")))
    second.destroy()


def test_profile_deleted_resets_default_rule_to_the_fallback_profile(store):
    store.set_default_rule("dev1", DefaultRule(True, 0, "page-1"))

    assert_that(store.profile_deleted("dev1", 0, 3)).is_true()

    assert_that(store.list_rules("dev1").default_rule).is_equal_to(DefaultRule(False, 3, ""))


def test_profile_deleted_leaves_a_default_rule_for_another_profile_alone(store):
    store.set_default_rule("dev1", DefaultRule(True, 4, "page-1"))

    assert_that(store.profile_deleted("dev1", 0, 3)).is_false()

    assert_that(store.list_rules("dev1").default_rule).is_equal_to(DefaultRule(True, 4, "page-1"))
