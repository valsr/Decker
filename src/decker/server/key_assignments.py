"""SQLite-backed store mapping (device_id, key_index) to an active action assignment."""

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from decker.common import paths as decker_paths
from decker.common.manager import Manager
from decker.plugin.context import ActionTarget

if TYPE_CHECKING:
    from decker.server.server_context import ServerContext

_SCHEMA = """
CREATE TABLE IF NOT EXISTS key_assignments (
    device_id   TEXT NOT NULL,
    key_index   INTEGER NOT NULL,
    plugin_uuid TEXT NOT NULL,
    action_uuid TEXT NOT NULL,
    context_id  TEXT NOT NULL,
    settings    TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (device_id, key_index)
)
"""


@dataclass(frozen=True)
class KeyAssignment:
    """One active key slot: which action occupies it and its current settings."""

    target: ActionTarget
    settings: dict[str, Any]


class KeyAssignmentStore(Manager):
    """Persists and retrieves key→action mappings from decker.db."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._lock = threading.Lock()
        self._db_path = Path(db_path) if db_path is not None else decker_paths.db()
        self._conn: sqlite3.Connection | None = None

    def create(self, context: "ServerContext") -> None:
        """Open the SQLite connection and initialise the schema."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._db.execute(_SCHEMA)
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

    def assign(self, device_id: str, key_index: int, target: ActionTarget, settings: dict[str, Any]) -> None:
        """Persist an assignment, replacing any previous one for this slot."""
        with self._lock:
            self._db.execute(
                """
                INSERT INTO key_assignments
                    (device_id, key_index, plugin_uuid, action_uuid, context_id, settings)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id, key_index) DO UPDATE SET
                    plugin_uuid = excluded.plugin_uuid,
                    action_uuid = excluded.action_uuid,
                    context_id  = excluded.context_id,
                    settings    = excluded.settings
                """,
                (device_id, key_index, target.plugin_uuid, target.action_uuid, target.context_id, json.dumps(settings)),
            )
            self._db.commit()

    def unassign(self, device_id: str, key_index: int) -> None:
        """Remove the assignment for this slot. No-op if unassigned."""
        with self._lock:
            self._db.execute(
                "DELETE FROM key_assignments WHERE device_id = ? AND key_index = ?",
                (device_id, key_index),
            )
            self._db.commit()

    def get(self, device_id: str, key_index: int) -> KeyAssignment | None:
        """Return the active assignment for this slot, or None if unassigned."""
        with self._lock:
            row = self._db.execute(
                "SELECT plugin_uuid, action_uuid, context_id, settings FROM key_assignments WHERE device_id = ? AND key_index = ?",
                (device_id, key_index),
            ).fetchone()
        if row is None:
            return None
        target = ActionTarget(
            plugin_uuid=row[0], action_uuid=row[1], context_id=row[2], device_id=device_id, key_index=key_index
        )
        return KeyAssignment(target=target, settings=json.loads(row[3]))

    def update_settings(self, device_id: str, key_index: int, settings: dict[str, Any]) -> bool:
        """Overwrite settings for an existing assignment. Returns False if slot is unassigned."""
        with self._lock:
            cursor = self._db.execute(
                "UPDATE key_assignments SET settings = ? WHERE device_id = ? AND key_index = ?",
                (json.dumps(settings), device_id, key_index),
            )
            self._db.commit()
        return cursor.rowcount > 0

    def all_for_device(self, device_id: str) -> list[tuple[int, KeyAssignment]]:
        """Return all assignments for a device as (key_index, assignment) pairs."""
        with self._lock:
            rows = self._db.execute(
                "SELECT key_index, plugin_uuid, action_uuid, context_id, settings FROM key_assignments WHERE device_id = ?",
                (device_id,),
            ).fetchall()
        result = []
        for row in rows:
            key_index, plugin_uuid, action_uuid, context_id, settings_json = row
            target = ActionTarget(
                plugin_uuid=plugin_uuid,
                action_uuid=action_uuid,
                context_id=context_id,
                device_id=device_id,
                key_index=key_index,
            )
            result.append((key_index, KeyAssignment(target=target, settings=json.loads(settings_json))))
        return result
