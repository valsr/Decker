"""SQLite-backed store of each device's screensaver settings."""

import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from decker.common import paths as decker_paths
from decker.common.manager import Manager
from decker.common.model import ScreensaverSettings
from decker.server.screensaver.settings import (
    settings_from_json,
    settings_to_json,
    validate,
)

if TYPE_CHECKING:
    from decker.server.server_context import ServerContext

_SCHEMA = """
CREATE TABLE IF NOT EXISTS screensaver_settings (
    device_id     TEXT PRIMARY KEY,
    settings_json TEXT NOT NULL
)
"""


class ScreensaverStore(Manager):
    """Persists each device's validated screensaver settings in decker.db."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._lock = threading.RLock()
        self._db_path = Path(db_path) if db_path is not None else decker_paths.db()
        self._conn: sqlite3.Connection | None = None

    def create(self, context: "ServerContext") -> None:
        """Open the SQLite connection and create the schema if missing."""
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
        assert self._conn is not None, "ScreensaverStore.create() must be called before use"
        return self._conn

    def get(self, device_id: str) -> ScreensaverSettings:
        """Return the device's settings, or the defaults when none are stored."""
        with self._lock:
            row = self._db.execute(
                "SELECT settings_json FROM screensaver_settings WHERE device_id = ?", (device_id,)
            ).fetchone()
        return settings_from_json(row[0]) if row is not None else ScreensaverSettings()

    def set(self, device_id: str, settings: ScreensaverSettings) -> None:
        """Validate and store the device's settings; raises ValueError for an invalid field."""
        text = settings_to_json(validate(settings))
        with self._lock:
            self._db.execute(
                "INSERT INTO screensaver_settings (device_id, settings_json) VALUES (?, ?)"
                " ON CONFLICT(device_id) DO UPDATE SET settings_json = excluded.settings_json",
                (device_id, text),
            )
            self._db.commit()
