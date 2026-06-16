"""Shared SQLite database path, used by both the plugin settings store and the asset system."""

from pathlib import Path

DB_PATH = Path.home() / ".decker" / "decker.db"
_LEGACY_DB_PATH = Path.home() / ".decker" / "plugins.db"


def migrate_legacy_db() -> None:
    """Rename the legacy plugins.db to decker.db, once. No-op if already migrated or never existed."""
    if _LEGACY_DB_PATH.exists() and not DB_PATH.exists():
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _LEGACY_DB_PATH.rename(DB_PATH)
