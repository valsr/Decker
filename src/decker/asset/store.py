"""SQLite-backed persistence for installed icon packs and user icon assignments, in decker.db."""

import sqlite3
from pathlib import Path

from decker.common.db import DB_PATH as _DEFAULT_DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS iconpacks (
    uuid         TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    version      TEXT NOT NULL,
    path         TEXT NOT NULL,
    installed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS user_icon_assignments (
    context_id TEXT PRIMARY KEY,
    icon_path  TEXT NOT NULL
);
"""


class IconPackStore:
    """Reads and writes icon pack registrations and per-key user icon assignments."""

    def __init__(self, db_path: str | Path = _DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def add_pack(self, pack_uuid: str, name: str, version: str, path: str) -> None:
        """Register or update an installed icon pack."""
        self._conn.execute(
            """
            INSERT INTO iconpacks (uuid, name, version, path) VALUES (?, ?, ?, ?)
            ON CONFLICT(uuid) DO UPDATE SET name = excluded.name, version = excluded.version, path = excluded.path
            """,
            (pack_uuid, name, version, path),
        )
        self._conn.commit()

    def remove_pack(self, pack_uuid: str) -> None:
        """Unregister an icon pack. No-op if not registered."""
        self._conn.execute("DELETE FROM iconpacks WHERE uuid = ?", (pack_uuid,))
        self._conn.commit()

    def list_packs(self) -> list[dict]:
        """Return all registered icon packs, ordered by name."""
        rows = self._conn.execute("SELECT uuid, name, version, path FROM iconpacks ORDER BY name").fetchall()
        return [{"uuid": r[0], "name": r[1], "version": r[2], "path": r[3]} for r in rows]

    def get_pack(self, pack_uuid: str) -> dict | None:
        """Return one registered icon pack, or None if not found."""
        row = self._conn.execute(
            "SELECT uuid, name, version, path FROM iconpacks WHERE uuid = ?", (pack_uuid,)
        ).fetchone()
        if row is None:
            return None
        return {"uuid": row[0], "name": row[1], "version": row[2], "path": row[3]}

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
