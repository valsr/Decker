"""Validates and applies edits to each device's app rules, announcing every change to clients."""

import json
from typing import TYPE_CHECKING

from decker.common.manager import Manager
from decker.common.model import AppRule, DefaultRule, DeviceRules
from decker.common.window_match import validate_condition

if TYPE_CHECKING:
    from decker.server.app_rule_store import AppRuleStore
    from decker.server.server_context import ServerContext

APP_RULES_CHANGED_EVENT = "app_rules_changed"
MAX_RULES_PER_DEVICE = 200
MAX_CONDITIONS_PER_RULE = 20
MAX_CONDITION_VALUE_LENGTH = 1024
MAX_RULE_NAME_LENGTH = 200


class AppRuleController(Manager):
    """Gatekeeper for app rule edits: invalid input is rejected without touching the store."""

    def __init__(self) -> None:
        self._context: "ServerContext | None" = None

    def create(self, context: "ServerContext") -> None:
        """Bind the server context."""
        self._context = context

    def destroy(self) -> None:
        """Release the server context."""
        self._context = None

    @property
    def _ctx(self) -> "ServerContext":
        assert self._context is not None, "AppRuleController.create() must be called before use"
        return self._context

    @property
    def _store(self) -> "AppRuleStore":
        store = self._ctx.app_rule_store
        assert store is not None, "AppRuleController requires an AppRuleStore"
        return store

    def rules(self, device_id: str) -> DeviceRules:
        """The device's rules in priority order plus its default rule."""
        return self._store.list_rules(device_id)

    def add_rule(self, device_id: str, rule: AppRule) -> AppRule | None:
        """Append a rule; returns the stored rule, or None when it is invalid."""
        if (
            not self._rule_valid(device_id, rule)
            or len(self._store.list_rules(device_id).rules) >= MAX_RULES_PER_DEVICE
        ):
            return None
        stored = self._store.add_rule(device_id, rule)
        self._notify(device_id)
        return stored

    def update_rule(self, device_id: str, rule: AppRule) -> bool:
        """Replace a rule; returns False when it is invalid or unknown."""
        if not self._rule_valid(device_id, rule) or not self._store.update_rule(device_id, rule):
            return False
        self._notify(device_id)
        return True

    def delete_rule(self, device_id: str, rule_id: str) -> bool:
        """Delete a rule; returns False for an unknown rule."""
        deleted = self._store.delete_rule(device_id, rule_id)
        if deleted:
            self._notify(device_id)
        return deleted

    def move_rule(self, device_id: str, rule_id: str, position: int) -> bool:
        """Move a rule to position; returns False for an unknown rule."""
        moved = self._store.move_rule(device_id, rule_id, position)
        if moved:
            self._notify(device_id)
        return moved

    def set_default_rule(self, device_id: str, default_rule: DefaultRule) -> bool:
        """Store the default rule; returns False when its target is invalid."""
        if not self._target_valid(device_id, default_rule.profile_id, default_rule.page_id):
            return False
        self._store.set_default_rule(device_id, default_rule)
        self._notify(device_id)
        return True

    def _rule_valid(self, device_id: str, rule: AppRule) -> bool:
        if not rule.name.strip() or len(rule.name) > MAX_RULE_NAME_LENGTH:
            return False
        if len(rule.conditions) > MAX_CONDITIONS_PER_RULE:
            return False
        if any(len(condition.value) > MAX_CONDITION_VALUE_LENGTH for condition in rule.conditions):
            return False
        if any(validate_condition(condition) is not None for condition in rule.conditions):
            return False
        return self._target_valid(device_id, rule.profile_id, rule.page_id)

    def _target_valid(self, device_id: str, profile_id: int, page_id: str) -> bool:
        store = self._ctx.page_store
        if store.get_profile(device_id, profile_id) is None:
            return False
        return not page_id or store.profile_of_page(device_id, page_id) == profile_id

    def _notify(self, device_id: str) -> None:
        self._ctx.event_bus.push(APP_RULES_CHANGED_EVENT, json.dumps({"device_id": device_id}))
