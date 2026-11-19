import time

from assertpy import assert_that

from decker.common.model import (
    AppRule,
    DefaultRule,
    DeviceRules,
    MatchCondition,
    RuleTarget,
    WindowInfo,
)
from decker.common.window_match import (
    condition_matches,
    resolve_target,
    rule_matches,
    validate_condition,
)

DOLPHIN = WindowInfo(window_class="org.kde.dolphin", window_type="normal", title="Home - Dolphin", executable="dolphin")


def _cond(field: str, op: str, value: str) -> MatchCondition:
    return MatchCondition(field, op, value)


def _rule(rule_id: str, conditions: list[MatchCondition], enabled: bool = True, profile_id: int = 1) -> AppRule:
    return AppRule(rule_id, rule_id, enabled, conditions, profile_id)


def test_equals_is_case_insensitive() -> None:
    assert_that(condition_matches(_cond("executable", "equals", "DOLPHIN"), DOLPHIN)).is_true()
    assert_that(condition_matches(_cond("executable", "equals", "dolph"), DOLPHIN)).is_false()


def test_contains_and_not_contains() -> None:
    assert_that(condition_matches(_cond("title", "contains", "HOME"), DOLPHIN)).is_true()
    assert_that(condition_matches(_cond("title", "contains", "konsole"), DOLPHIN)).is_false()
    assert_that(condition_matches(_cond("title", "not_contains", "konsole"), DOLPHIN)).is_true()
    assert_that(condition_matches(_cond("title", "not_contains", "home"), DOLPHIN)).is_false()


def test_not_contains_true_on_empty_field_others_false() -> None:
    empty = WindowInfo()
    assert_that(condition_matches(_cond("title", "contains", "x"), empty)).is_false()
    assert_that(condition_matches(_cond("title", "regex", ".*"), empty)).is_false()
    assert_that(condition_matches(_cond("title", "not_contains", "x"), empty)).is_true()
    assert_that(condition_matches(_cond("title", "equals", ""), empty)).is_true()
    assert_that(condition_matches(_cond("title", "equals", "x"), empty)).is_false()


def test_regex_uses_search() -> None:
    assert_that(condition_matches(_cond("window_class", "regex", r"^org\.kde\."), DOLPHIN)).is_true()
    assert_that(condition_matches(_cond("window_class", "regex", r"dolph"), DOLPHIN)).is_true()
    assert_that(condition_matches(_cond("window_class", "regex", r"^dolphin"), DOLPHIN)).is_false()


def test_rule_requires_all_conditions() -> None:
    both = _rule("a", [_cond("executable", "equals", "dolphin"), _cond("title", "contains", "home")])
    one_wrong = _rule("b", [_cond("executable", "equals", "dolphin"), _cond("title", "contains", "zzz")])
    assert_that(rule_matches(both, DOLPHIN)).is_true()
    assert_that(rule_matches(one_wrong, DOLPHIN)).is_false()


def test_rule_without_conditions_never_matches() -> None:
    assert_that(rule_matches(_rule("a", []), DOLPHIN)).is_false()


def test_resolve_target_first_enabled_match_wins() -> None:
    rules = DeviceRules(
        "d",
        [
            _rule("miss", [_cond("executable", "equals", "firefox")], profile_id=1),
            _rule("first", [_cond("executable", "equals", "dolphin")], profile_id=2),
            _rule("second", [_cond("executable", "equals", "dolphin")], profile_id=3),
        ],
        DefaultRule(),
    )
    assert_that(resolve_target(rules, DOLPHIN)).is_equal_to(RuleTarget(2, ""))


def test_resolve_target_skips_disabled_rule() -> None:
    rules = DeviceRules(
        "d",
        [
            _rule("off", [_cond("executable", "equals", "dolphin")], enabled=False, profile_id=2),
            _rule("on", [_cond("executable", "equals", "dolphin")], profile_id=3),
        ],
        DefaultRule(),
    )
    assert_that(resolve_target(rules, DOLPHIN)).is_equal_to(RuleTarget(3, ""))


def test_resolve_target_falls_back_to_enabled_default_rule() -> None:
    rules = DeviceRules("d", [], DefaultRule(enabled=True, profile_id=4, page_id="p"))
    assert_that(resolve_target(rules, DOLPHIN)).is_equal_to(RuleTarget(4, "p"))


def test_resolve_target_none_when_default_disabled() -> None:
    rules = DeviceRules("d", [], DefaultRule(enabled=False, profile_id=4))
    assert_that(resolve_target(rules, DOLPHIN)).is_none()


def test_validate_rejects_unknown_field_op_bad_regex_and_empty_contains_or_regex() -> None:
    assert_that(validate_condition(_cond("nope", "equals", "x"))).is_not_none()
    assert_that(validate_condition(_cond("title", "starts", "x"))).is_not_none()
    assert_that(validate_condition(_cond("title", "regex", "("))).is_not_none()
    for op in ("contains", "not_contains", "regex"):
        assert_that(validate_condition(_cond("title", op, ""))).is_not_none()
    assert_that(validate_condition(_cond("title", "equals", ""))).is_none()
    assert_that(validate_condition(_cond("title", "regex", r"^a+$"))).is_none()


def test_pathological_regex_times_out_as_no_match() -> None:
    window = WindowInfo(title="a" * 40 + "!")
    start = time.monotonic()
    result = condition_matches(_cond("title", "regex", "(a+)+$"), window)
    assert_that(result).is_false()
    assert_that(time.monotonic() - start).is_less_than(1.0)
