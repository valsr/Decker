import logging

import regex

from decker.common.model import (
    MATCH_FIELDS,
    MATCH_OPS,
    AppRule,
    DeviceRules,
    MatchCondition,
    RuleTarget,
    WindowInfo,
)

_LOGGER = logging.getLogger(__name__)
_REGEX_TIMEOUT = 0.1
_NEEDS_VALUE = ("contains", "not_contains", "regex")


def _regex_matches(pattern: str, text: str) -> bool:
    try:
        return regex.search(pattern, text, flags=regex.IGNORECASE, timeout=_REGEX_TIMEOUT) is not None
    except TimeoutError:
        _LOGGER.debug("Regex %r timed out; treating as no match", pattern)
        return False
    except regex.error:
        return False


def condition_matches(condition: MatchCondition, window: WindowInfo) -> bool:
    """Whether one condition holds for the window (case-insensitive; see the design for empty fields)."""
    text = str(getattr(window, condition.field, "")).lower()
    value = condition.value.lower()
    if condition.op == "not_contains":
        return value not in text
    if condition.op == "equals":
        return text == value
    if not text:
        return False
    if condition.op == "contains":
        return value in text
    if condition.op == "regex":
        return _regex_matches(condition.value, text)
    return False


def rule_matches(rule: AppRule, window: WindowInfo) -> bool:
    """Whether every condition matches; a rule with no conditions never matches."""
    return bool(rule.conditions) and all(condition_matches(c, window) for c in rule.conditions)


def resolve_target(rules: DeviceRules, window: WindowInfo) -> RuleTarget | None:
    """The first enabled matching rule's target, else the enabled default rule's, else None."""
    for rule in rules.rules:
        if rule.enabled and rule_matches(rule, window):
            return RuleTarget(rule.profile_id, rule.page_id)
    default = rules.default_rule
    return RuleTarget(default.profile_id, default.page_id) if default.enabled else None


def validate_condition(condition: MatchCondition) -> str | None:
    """Error text for an invalid condition, or None when it is valid."""
    if condition.field not in MATCH_FIELDS:
        return f"Unknown field: {condition.field}"
    if condition.op not in MATCH_OPS:
        return f"Unknown operator: {condition.op}"
    if condition.op in _NEEDS_VALUE and not condition.value:
        return f"A value is required for {condition.op}"
    if condition.op == "regex":
        try:
            regex.compile(condition.value)
        except regex.error as exc:
            return f"Invalid regular expression: {exc}"
    return None
