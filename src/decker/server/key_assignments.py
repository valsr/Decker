"""SQLite-backed store mapping (device_id, page_id, key_index) to an active action assignment."""

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from decker.common import paths as decker_paths
from decker.common.manager import Manager
from decker.plugin.target import ActionTarget
from decker.server.pages import initial_page_id

if TYPE_CHECKING:
    from decker.server.server_context import ServerContext

_TABLE = "key_assignments"
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    device_id   TEXT NOT NULL,
    page_id     TEXT NOT NULL,
    key_index   INTEGER NOT NULL,
    plugin_uuid TEXT NOT NULL,
    action_uuid TEXT NOT NULL,
    context_id  TEXT NOT NULL,
    settings    TEXT NOT NULL DEFAULT '{{}}',
    appearance  TEXT NOT NULL DEFAULT '{{}}',
    PRIMARY KEY (device_id, page_id, key_index)
)
"""
_META_SCHEMA = "CREATE TABLE IF NOT EXISTS key_assignment_meta (name TEXT PRIMARY KEY)"
_LEGACY_COLUMNS = "key_index, plugin_uuid, action_uuid, context_id, settings"
_COLUMNS = f"{_LEGACY_COLUMNS}, appearance"
_COUNTER_PLUGIN = "com.decker.counter"
_COUNTER_APPEARANCE_MIGRATION = "counter_appearance"
_COUNTER_APPEARANCE_KEYS = (
    "background",
    "title",
    "title_position",
    "title_font",
    "title_size",
    "title_color",
    "title_outline",
    "title_outline_width",
)


@dataclass(frozen=True)
class KeyAssignment:
    """One active key slot: which action occupies it and its current settings."""

    target: ActionTarget
    settings: dict[str, Any]
    appearance: dict[str, Any] = field(default_factory=dict)


class KeyAssignmentStore(Manager):
    """Persists and retrieves key→action mappings per page from decker.db."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._lock = threading.Lock()
        self._db_path = Path(db_path) if db_path is not None else decker_paths.db()
        self._conn: sqlite3.Connection | None = None

    def create(self, context: "ServerContext") -> None:
        """Open the SQLite connection, migrate pre-page data, and initialise the schema."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._migrate_to_pages()
        self._db.execute(_SCHEMA)
        self._db.execute(_META_SCHEMA)
        self._add_appearance_column()
        self._migrate_counter_appearance()
        self._db.commit()

    def destroy(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def _db(self) -> sqlite3.Connection:
        assert self._conn is not None, "KeyAssignmentStore.create() must be called before use"
        return self._conn

    def assign(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, device_id: str, page_id: str, key_index: int, target: ActionTarget, settings: dict[str, Any]
    ) -> None:
        """Persist an assignment, replacing any previous one for this slot."""
        with self._lock:
            self._db.execute(
                f"""
                INSERT INTO {_TABLE}
                    (device_id, page_id, key_index, plugin_uuid, action_uuid, context_id, settings)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id, page_id, key_index) DO UPDATE SET
                    plugin_uuid = excluded.plugin_uuid,
                    action_uuid = excluded.action_uuid,
                    context_id  = excluded.context_id,
                    settings    = excluded.settings,
                    appearance  = '{{}}'
                """,
                (
                    device_id,
                    page_id,
                    key_index,
                    target.plugin_uuid,
                    target.action_uuid,
                    target.context_id,
                    json.dumps(settings),
                ),
            )
            self._db.commit()

    def unassign(self, device_id: str, page_id: str, key_index: int) -> None:
        """Remove the assignment for this slot. No-op if unassigned."""
        with self._lock:
            self._db.execute(
                f"DELETE FROM {_TABLE} WHERE device_id = ? AND page_id = ? AND key_index = ?",
                (device_id, page_id, key_index),
            )
            self._db.commit()

    def get(self, device_id: str, page_id: str, key_index: int) -> KeyAssignment | None:
        """Return the assignment for this slot, or None if unassigned."""
        with self._lock:
            row = self._db.execute(
                f"SELECT {_COLUMNS} FROM {_TABLE} WHERE device_id = ? AND page_id = ? AND key_index = ?",
                (device_id, page_id, key_index),
            ).fetchone()
        return _to_assignment(device_id, row)[1] if row is not None else None

    def update_settings(self, device_id: str, page_id: str, key_index: int, settings: dict[str, Any]) -> bool:
        """Overwrite settings for an existing assignment. Returns False if slot is unassigned."""
        with self._lock:
            cursor = self._db.execute(
                f"UPDATE {_TABLE} SET settings = ? WHERE device_id = ? AND page_id = ? AND key_index = ?",
                (json.dumps(settings), device_id, page_id, key_index),
            )
            self._db.commit()
        return cursor.rowcount > 0

    def update_appearance(self, device_id: str, page_id: str, key_index: int, appearance: dict[str, Any]) -> bool:
        """Overwrite the key's appearance. Returns False if slot is unassigned."""
        with self._lock:
            cursor = self._db.execute(
                f"UPDATE {_TABLE} SET appearance = ? WHERE device_id = ? AND page_id = ? AND key_index = ?",
                (json.dumps(appearance), device_id, page_id, key_index),
            )
            self._db.commit()
        return cursor.rowcount > 0

    def all_for_page(self, device_id: str, page_id: str) -> list[tuple[int, KeyAssignment]]:
        """Return all assignments on one page as (key_index, assignment) pairs, in key order."""
        with self._lock:
            rows = self._db.execute(
                f"SELECT {_COLUMNS} FROM {_TABLE} WHERE device_id = ? AND page_id = ? ORDER BY key_index",
                (device_id, page_id),
            ).fetchall()
        return [_to_assignment(device_id, row) for row in rows]

    def assignments_for_plugin(self, plugin_id: str) -> list[tuple[str, str, int, KeyAssignment]]:
        """Return every assignment of a plugin's actions as (device_id, page_id, key_index, assignment)."""
        with self._lock:
            rows = self._db.execute(
                f"SELECT device_id, page_id, {_COLUMNS} FROM {_TABLE} WHERE plugin_uuid = ? "
                "ORDER BY device_id, page_id, key_index",
                (plugin_id,),
            ).fetchall()
        return [(row[0], row[1], *_to_assignment(row[0], row[2:])) for row in rows]

    def plugin_ids(self) -> set[str]:
        """Return the ids of every plugin referenced by at least one assignment."""
        with self._lock:
            rows = self._db.execute(f"SELECT DISTINCT plugin_uuid FROM {_TABLE}").fetchall()
        return {row[0] for row in rows}

    def delete_page(self, device_id: str, page_id: str) -> None:
        """Remove every assignment on a page."""
        with self._lock:
            self._db.execute(f"DELETE FROM {_TABLE} WHERE device_id = ? AND page_id = ?", (device_id, page_id))
            self._db.commit()

    def _migrate_to_pages(self) -> None:
        columns = [row[1] for row in self._db.execute(f"PRAGMA table_info({_TABLE})").fetchall()]
        if not columns or "page_id" in columns:
            return
        rows = self._db.execute(f"SELECT device_id, {_LEGACY_COLUMNS} FROM {_TABLE}").fetchall()
        with self._db:
            self._db.execute(f"ALTER TABLE {_TABLE} RENAME TO {_TABLE}_legacy")
            self._db.execute(_SCHEMA)
            self._db.executemany(
                f"INSERT INTO {_TABLE} (device_id, page_id, {_LEGACY_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(row[0], initial_page_id(row[0]), *row[1:]) for row in rows],
            )
            self._db.execute(f"DROP TABLE {_TABLE}_legacy")

    def _add_appearance_column(self) -> None:
        columns = [row[1] for row in self._db.execute(f"PRAGMA table_info({_TABLE})").fetchall()]
        if "appearance" not in columns:
            self._db.execute(f"ALTER TABLE {_TABLE} ADD COLUMN appearance TEXT NOT NULL DEFAULT '{{}}'")

    def _migrate_counter_appearance(self) -> None:
        done = self._db.execute(
            "SELECT 1 FROM key_assignment_meta WHERE name = ?", (_COUNTER_APPEARANCE_MIGRATION,)
        ).fetchone()
        if done is not None:
            return
        rows = self._db.execute(
            f"SELECT device_id, page_id, key_index, settings, appearance FROM {_TABLE} WHERE plugin_uuid = ?",
            (_COUNTER_PLUGIN,),
        ).fetchall()
        for device_id, page_id, key_index, settings_json, appearance_json in rows:
            settings = json.loads(settings_json)
            moved = {k: settings.pop(k) for k in _COUNTER_APPEARANCE_KEYS if k in settings}
            if not moved.get("title_outline"):
                moved.pop("title_outline", None)
            self._db.execute(
                f"UPDATE {_TABLE} SET settings = ?, appearance = ? "
                "WHERE device_id = ? AND page_id = ? AND key_index = ?",
                (
                    json.dumps(settings),
                    json.dumps({**json.loads(appearance_json), **moved}),
                    device_id,
                    page_id,
                    key_index,
                ),
            )
        self._db.execute("INSERT INTO key_assignment_meta (name) VALUES (?)", (_COUNTER_APPEARANCE_MIGRATION,))


def _to_assignment(device_id: str, row: tuple[Any, ...]) -> tuple[int, KeyAssignment]:
    key_index, plugin_uuid, action_uuid, context_id, settings_json, appearance_json = row
    target = ActionTarget(
        device_id=device_id,
        key_index=key_index,
        plugin_uuid=plugin_uuid,
        action_uuid=action_uuid,
        context_id=context_id,
    )
    return key_index, KeyAssignment(
        target=target, settings=json.loads(settings_json), appearance=json.loads(appearance_json)
    )
