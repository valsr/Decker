"""SQLite-backed persistence for per-key user icon assignments, in decker.db."""

import sqlite3
from pathlib import Path

from decker.common import paths as decker_paths

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_icon_assignments (
    context_id TEXT PRIMARY KEY,
    icon_path  TEXT NOT NULL
);
"""


class IconPackStore:
    """Reads and writes per-key user icon assignments."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else decker_paths.db()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def set_user_icon(self, context_id: str, icon_path: str) -> None:
        """Assign a custom icon path to a key context, overwriting any previous assignment."""
        self._conn.execute(
            """
            INSERT INTO user_icon_assignments (context_id, icon_path) VALUES (?, ?)
            ON CONFLICT(context_id) DO UPDATE SET icon_path = excluded.icon_path
            """,
            (context_id, icon_path),
        )
        self._conn.commit()

    def get_user_icon(self, context_id: str) -> str | None:
        """Return the user-assigned icon path for a key context, or None if unassigned."""
        row = self._conn.execute(
            "SELECT icon_path FROM user_icon_assignments WHERE context_id = ?", (context_id,)
        ).fetchone()
        return row[0] if row else None

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()
