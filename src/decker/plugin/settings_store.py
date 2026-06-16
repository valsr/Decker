"""SQLite-backed persistence for per-context action settings, at ~/.decker/decker.db."""

import json
import sqlite3
from pathlib import Path

from decker.common.db import DB_PATH as _DEFAULT_DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    plugin_uuid  TEXT NOT NULL,
    action_uuid  TEXT NOT NULL,
    context_id   TEXT NOT NULL,
    settings     TEXT NOT NULL,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (plugin_uuid, action_uuid, context_id)
)
"""


class PluginSettingsStore:
    """Reads and writes action settings, persisted across server restarts."""

    def __init__(self, db_path: str | Path = _DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def get_settings(self, plugin_uuid: str, action_uuid: str, context_id: str) -> dict:
        """Return persisted settings for this action instance, or {} if none exist."""
        row = self._conn.execute(
            "SELECT settings FROM settings WHERE plugin_uuid = ? AND action_uuid = ? AND context_id = ?",
            (plugin_uuid, action_uuid, context_id),
        ).fetchone()
        if row is None:
            return {}
        return json.loads(row[0])

    def set_settings(self, plugin_uuid: str, action_uuid: str, context_id: str, settings: dict) -> None:
        """Persist (overwrite) settings for this action instance."""
        self._conn.execute(
            """
            INSERT INTO settings (plugin_uuid, action_uuid, context_id, settings, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(plugin_uuid, action_uuid, context_id)
            DO UPDATE SET settings = excluded.settings, updated_at = CURRENT_TIMESTAMP
            """,
            (plugin_uuid, action_uuid, context_id, json.dumps(settings)),
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
