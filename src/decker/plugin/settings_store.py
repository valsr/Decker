"""SQLite-backed persistence for per-context card settings, at ~/.decker/decker.db."""

import json
import sqlite3
from pathlib import Path

from decker.common import paths as decker_paths
from decker.common.dbmigrate import rename_column

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    plugin_uuid  TEXT NOT NULL,
    card_uuid  TEXT NOT NULL,
    context_id   TEXT NOT NULL,
    settings     TEXT NOT NULL,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (plugin_uuid, card_uuid, context_id)
)
"""
_GLOBAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS global_settings (
    plugin_id  TEXT PRIMARY KEY,
    settings   TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""


class PluginSettingsStore:
    """Reads and writes card settings, persisted across server restarts."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else decker_paths.db()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute(_SCHEMA)
        rename_column(self._conn, "settings", "action_uuid", "card_uuid")
        self._conn.execute(_GLOBAL_SCHEMA)
        self._conn.commit()

    def get_settings(self, plugin_uuid: str, card_uuid: str, context_id: str) -> dict:
        """Return persisted settings for this card instance, or {} if none exist."""
        row = self._conn.execute(
            "SELECT settings FROM settings WHERE plugin_uuid = ? AND card_uuid = ? AND context_id = ?",
            (plugin_uuid, card_uuid, context_id),
        ).fetchone()
        if row is None:
            return {}
        return json.loads(row[0])

    def set_settings(self, plugin_uuid: str, card_uuid: str, context_id: str, settings: dict) -> None:
        """Persist (overwrite) settings for this card instance."""
        self._conn.execute(
            """
            INSERT INTO settings (plugin_uuid, card_uuid, context_id, settings, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(plugin_uuid, card_uuid, context_id)
            DO UPDATE SET settings = excluded.settings, updated_at = CURRENT_TIMESTAMP
            """,
            (plugin_uuid, card_uuid, context_id, json.dumps(settings)),
        )
        self._conn.commit()

    def get_global_settings(self, plugin_id: str) -> dict:
        """Return the plugin-wide settings, or {} if none are stored."""
        row = self._conn.execute("SELECT settings FROM global_settings WHERE plugin_id = ?", (plugin_id,)).fetchone()
        return json.loads(row[0]) if row is not None else {}

    def set_global_settings(self, plugin_id: str, settings: dict) -> None:
        """Persist (overwrite) the plugin-wide settings."""
        self._conn.execute(
            """
            INSERT INTO global_settings (plugin_id, settings, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(plugin_id) DO UPDATE SET settings = excluded.settings, updated_at = CURRENT_TIMESTAMP
            """,
            (plugin_id, json.dumps(settings)),
        )
        self._conn.commit()

    def delete_plugin(self, plugin_id: str) -> None:
        """Remove every stored setting (per-context and plugin-wide) for a plugin."""
        self._conn.execute("DELETE FROM settings WHERE plugin_uuid = ?", (plugin_id,))
        self._conn.execute("DELETE FROM global_settings WHERE plugin_id = ?", (plugin_id,))
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
