"""SQLite-backed store of each device's ordered pages and its default page."""

import sqlite3
import threading
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from decker.common import paths as decker_paths
from decker.common.manager import Manager
from decker.common.model import PageInfo

if TYPE_CHECKING:
    from decker.server.server_context import ServerContext

_SCHEMA_PAGES = """
CREATE TABLE IF NOT EXISTS pages (
    page_id   TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    name      TEXT NOT NULL,
    position  INTEGER NOT NULL
)
"""

_SCHEMA_DEFAULTS = """
CREATE TABLE IF NOT EXISTS page_defaults (
    device_id TEXT PRIMARY KEY,
    page_id   TEXT NOT NULL
)
"""

_PAGE_NAME_PREFIX = "Page "


def initial_page_id(device_id: str) -> str:
    """The id of a device's first page; key data stored before pages existed migrates to it."""
    return f"{device_id}-page-1"


class PageStore(Manager):
    """Persists pages per device in decker.db. Every device has at least one page.

    A device's first page ("Page 1", id initial_page_id) is created on first access.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._lock = threading.RLock()
        self._db_path = Path(db_path) if db_path is not None else decker_paths.db()
        self._conn: sqlite3.Connection | None = None

    def create(self, context: "ServerContext") -> None:
        """Open the SQLite connection and initialise the schema."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._db.execute(_SCHEMA_PAGES)
        self._db.execute(_SCHEMA_DEFAULTS)
        self._db.commit()

    def destroy(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def _db(self) -> sqlite3.Connection:
        assert self._conn is not None, "PageStore.create() must be called before use"
        return self._conn

    def list_pages(self, device_id: str) -> list[PageInfo]:
        """Return the device's pages in display order, creating "Page 1" if it has none."""
        with self._lock:
            rows = self._db.execute(
                "SELECT page_id, name FROM pages WHERE device_id = ? ORDER BY position", (device_id,)
            ).fetchall()
            if rows:
                return [PageInfo(page_id=row[0], name=row[1]) for row in rows]
            page = PageInfo(page_id=initial_page_id(device_id), name=f"{_PAGE_NAME_PREFIX}1")
            self._insert(device_id, page, position=0)
            return [page]

    def get(self, device_id: str, page_id: str) -> PageInfo | None:
        """Return the page if it belongs to device_id, else None."""
        return next((page for page in self.list_pages(device_id) if page.page_id == page_id), None)

    def add_page(self, device_id: str, name: str | None = None) -> PageInfo:
        """Append a page, named "Page N" (first unused N) unless a non-blank name is given."""
        with self._lock:
            pages = self.list_pages(device_id)
            page = PageInfo(page_id=uuid.uuid4().hex, name=(name or "").strip() or _next_page_name(pages))
            self._insert(device_id, page, position=self._next_position(device_id))
            return page

    def rename_page(self, device_id: str, page_id: str, name: str) -> bool:
        """Rename a page. Returns False for an unknown page or a blank name."""
        name = name.strip()
        if not name:
            return False
        with self._lock:
            cursor = self._db.execute(
                "UPDATE pages SET name = ? WHERE device_id = ? AND page_id = ?", (name, device_id, page_id)
            )
            self._db.commit()
        return cursor.rowcount > 0

    def delete_page(self, device_id: str, page_id: str) -> bool:
        """Delete a page. Refuses the last page; a deleted default page passes to the first page."""
        with self._lock:
            pages = self.list_pages(device_id)
            if len(pages) <= 1 or all(page.page_id != page_id for page in pages):
                return False
            was_default = self.default_page_id(device_id) == page_id
            self._db.execute("DELETE FROM pages WHERE device_id = ? AND page_id = ?", (device_id, page_id))
            if was_default:
                self._db.execute("DELETE FROM page_defaults WHERE device_id = ?", (device_id,))
            self._db.commit()
            return True

    def default_page_id(self, device_id: str) -> str:
        """Return the page shown when the device starts: the chosen default, else the first page."""
        with self._lock:
            pages = self.list_pages(device_id)
            row = self._db.execute("SELECT page_id FROM page_defaults WHERE device_id = ?", (device_id,)).fetchone()
            ids = {page.page_id for page in pages}
            return row[0] if row is not None and row[0] in ids else pages[0].page_id

    def set_default_page(self, device_id: str, page_id: str) -> bool:
        """Make page_id the device's default page. Returns False for an unknown page."""
        with self._lock:
            if self.get(device_id, page_id) is None:
                return False
            self._db.execute(
                """
                INSERT INTO page_defaults (device_id, page_id) VALUES (?, ?)
                ON CONFLICT(device_id) DO UPDATE SET page_id = excluded.page_id
                """,
                (device_id, page_id),
            )
            self._db.commit()
            return True

    def _insert(self, device_id: str, page: PageInfo, position: int) -> None:
        self._db.execute(
            "INSERT INTO pages (page_id, device_id, name, position) VALUES (?, ?, ?, ?)",
            (page.page_id, device_id, page.name, position),
        )
        self._db.commit()

    def _next_position(self, device_id: str) -> int:
        row = self._db.execute("SELECT MAX(position) FROM pages WHERE device_id = ?", (device_id,)).fetchone()
        return (row[0] if row and row[0] is not None else -1) + 1


def _next_page_name(pages: list[PageInfo]) -> str:
    names = {page.name for page in pages}
    number = 1
    while f"{_PAGE_NAME_PREFIX}{number}" in names:
        number += 1
    return f"{_PAGE_NAME_PREFIX}{number}"
