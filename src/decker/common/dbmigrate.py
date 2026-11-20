"""Small SQLite schema migrations shared by the stores."""

import sqlite3


def rename_column(db: sqlite3.Connection, table: str, old: str, new: str) -> bool:
    """Rename ``old`` to ``new`` in ``table`` when the table has ``old``; True if it did."""
    columns = [row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()]
    if old not in columns or new in columns:
        return False
    db.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
    return True
