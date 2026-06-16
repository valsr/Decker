"""Persists UI layout state (window geometry, splitter sizes, sidebar state) to config.db.

Separate SQLite database and lifecycle from the plugin/asset decker.db.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

_DEFAULT_DB_PATH = Path.home() / ".decker" / "config.db"

_SCHEMA = "CREATE TABLE IF NOT EXISTS ui_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)"


class UiStateStore:
    """Generic JSON-encoded key/value store for UI state."""

    def __init__(self, db_path: str | Path = _DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def get(self, key: str) -> Any | None:
        """Return the JSON-decoded value for key, or None if unset."""
        row = self._conn.execute("SELECT value FROM ui_state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def set(self, key: str, value: Any) -> None:
        """Persist value (JSON-encoded) for key, overwriting any previous value."""
        self._conn.execute(
            """
            INSERT INTO ui_state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, json.dumps(value)),
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
