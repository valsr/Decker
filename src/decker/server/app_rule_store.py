"""SQLite-backed store of each device's ordered app rules and its default rule."""

import json
import sqlite3
import threading
import uuid
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from decker.common import paths as decker_paths
from decker.common.manager import Manager
from decker.common.model import AppRule, DefaultRule, DeviceRules, MatchCondition

if TYPE_CHECKING:
    from decker.server.server_context import ServerContext

_SCHEMA_RULES = """
CREATE TABLE IF NOT EXISTS app_rules (
    device_id       TEXT NOT NULL,
    rule_id         TEXT NOT NULL,
    position        INTEGER NOT NULL,
    name            TEXT NOT NULL,
    enabled         INTEGER NOT NULL,
    conditions_json TEXT NOT NULL,
    profile_id      INTEGER NOT NULL,
    page_id         TEXT NOT NULL,
    PRIMARY KEY (device_id, rule_id)
)
"""

_SCHEMA_DEFAULT_RULES = """
CREATE TABLE IF NOT EXISTS default_rules (
    device_id  TEXT PRIMARY KEY,
    enabled    INTEGER NOT NULL,
    profile_id INTEGER NOT NULL,
    page_id    TEXT NOT NULL
)
"""

_RULE_COLUMNS = "rule_id, name, enabled, conditions_json, profile_id, page_id"


def _row_to_rule(row: tuple[str, str, int, str, int, str]) -> AppRule:
    conditions = [MatchCondition(c["field"], c["op"], c["value"]) for c in json.loads(row[3])]
    return AppRule(row[0], row[1], bool(row[2]), conditions, row[4], row[5])


def _conditions_json(rule: AppRule) -> str:
    return json.dumps([{"field": c.field, "op": c.op, "value": c.value} for c in rule.conditions])


class AppRuleStore(Manager):
    """Persists each device's ordered app rules and default rule in decker.db; it does not validate targets."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._lock = threading.RLock()
        self._db_path = Path(db_path) if db_path is not None else decker_paths.db()
        self._conn: sqlite3.Connection | None = None

    def create(self, context: "ServerContext") -> None:
        """Open the SQLite connection and create the schema if missing."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._db.execute(_SCHEMA_RULES)
        self._db.execute(_SCHEMA_DEFAULT_RULES)
        self._db.commit()

    def destroy(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def _db(self) -> sqlite3.Connection:
        assert self._conn is not None, "AppRuleStore.create() must be called before use"
        return self._conn

    def list_rules(self, device_id: str) -> DeviceRules:
        """Return the device's rules in priority order and its default rule (disabled, profile 0, when unset)."""
        with self._lock:
            return DeviceRules(device_id, self._rules(device_id), self._default_rule(device_id))

    def add_rule(self, device_id: str, rule: AppRule) -> AppRule:
        """Append the rule under a freshly generated id and return the stored rule."""
        with self._lock:
            stored = replace(rule, rule_id=uuid.uuid4().hex)
            row = self._db.execute(
                "SELECT COALESCE(MAX(position) + 1, 0) FROM app_rules WHERE device_id = ?", (device_id,)
            ).fetchone()
            self._db.execute(
                "INSERT INTO app_rules (device_id, rule_id, position, name, enabled, conditions_json, profile_id, page_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    device_id,
                    stored.rule_id,
                    row[0],
                    stored.name,
                    int(stored.enabled),
                    _conditions_json(stored),
                    stored.profile_id,
                    stored.page_id,
                ),
            )
            self._db.commit()
            return stored

    def update_rule(self, device_id: str, rule: AppRule) -> bool:
        """Replace a rule's fields in place. Returns False for an unknown rule."""
        with self._lock:
            cursor = self._db.execute(
                "UPDATE app_rules SET name = ?, enabled = ?, conditions_json = ?, profile_id = ?, page_id = ?"
                " WHERE device_id = ? AND rule_id = ?",
                (
                    rule.name,
                    int(rule.enabled),
                    _conditions_json(rule),
                    rule.profile_id,
                    rule.page_id,
                    device_id,
                    rule.rule_id,
                ),
            )
            self._db.commit()
            return cursor.rowcount > 0

    def delete_rule(self, device_id: str, rule_id: str) -> bool:
        """Delete a rule. Returns False for an unknown rule."""
        with self._lock:
            cursor = self._db.execute("DELETE FROM app_rules WHERE device_id = ? AND rule_id = ?", (device_id, rule_id))
            self._renumber(device_id)
            self._db.commit()
            return cursor.rowcount > 0

    def move_rule(self, device_id: str, rule_id: str, position: int) -> bool:
        """Move a rule to position (clamped to the list). Returns False for an unknown rule."""
        with self._lock:
            ids = [r[0] for r in self._db.execute(*self._order_query(device_id)).fetchall()]
            if rule_id not in ids:
                return False
            ids.remove(rule_id)
            ids.insert(max(0, min(position, len(ids))), rule_id)
            self._write_order(device_id, ids)
            self._db.commit()
            return True

    def set_default_rule(self, device_id: str, default_rule: DefaultRule) -> None:
        """Store the device's default rule."""
        with self._lock:
            self._write_default(device_id, default_rule)
            self._db.commit()

    def profile_deleted(self, device_id: str, profile_id: int, fallback_profile_id: int) -> bool:
        """Drop the profile's rules and reset a default rule that targeted it to the fallback profile, disabled.

        Returns whether anything changed.
        """
        with self._lock:
            cursor = self._db.execute(
                "DELETE FROM app_rules WHERE device_id = ? AND profile_id = ?", (device_id, profile_id)
            )
            changed = cursor.rowcount > 0
            self._renumber(device_id)
            default = self._default_rule(device_id)
            if default.profile_id == profile_id:
                self._write_default(device_id, DefaultRule(profile_id=fallback_profile_id))
                changed = True
            self._db.commit()
            return changed

    def page_deleted(self, device_id: str, page_id: str) -> bool:
        """Clear the page on rules and the default rule that targeted it. Returns whether anything changed."""
        if not page_id:
            return False
        with self._lock:
            cursor = self._db.execute(
                "UPDATE app_rules SET page_id = '' WHERE device_id = ? AND page_id = ?", (device_id, page_id)
            )
            changed = cursor.rowcount > 0
            default = self._default_rule(device_id)
            if default.page_id == page_id:
                self._write_default(device_id, replace(default, page_id=""))
                changed = True
            self._db.commit()
            return changed

    def _rules(self, device_id: str) -> list[AppRule]:
        rows = self._db.execute(
            f"SELECT {_RULE_COLUMNS} FROM app_rules WHERE device_id = ? ORDER BY position", (device_id,)
        ).fetchall()
        return [_row_to_rule(row) for row in rows]

    def _default_rule(self, device_id: str) -> DefaultRule:
        row = self._db.execute(
            "SELECT enabled, profile_id, page_id FROM default_rules WHERE device_id = ?", (device_id,)
        ).fetchone()
        return DefaultRule(bool(row[0]), row[1], row[2]) if row is not None else DefaultRule()

    def _write_default(self, device_id: str, rule: DefaultRule) -> None:
        self._db.execute(
            """
            INSERT INTO default_rules (device_id, enabled, profile_id, page_id) VALUES (?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                enabled = excluded.enabled, profile_id = excluded.profile_id, page_id = excluded.page_id
            """,
            (device_id, int(rule.enabled), rule.profile_id, rule.page_id),
        )

    @staticmethod
    def _order_query(device_id: str) -> tuple[str, tuple[str]]:
        return "SELECT rule_id FROM app_rules WHERE device_id = ? ORDER BY position", (device_id,)

    def _renumber(self, device_id: str) -> None:
        self._write_order(device_id, [r[0] for r in self._db.execute(*self._order_query(device_id)).fetchall()])

    def _write_order(self, device_id: str, ids: list[str]) -> None:
        for position, rule_id in enumerate(ids):
            self._db.execute(
                "UPDATE app_rules SET position = ? WHERE device_id = ? AND rule_id = ?", (position, device_id, rule_id)
            )
