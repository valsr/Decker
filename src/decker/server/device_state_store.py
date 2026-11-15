"""SQLite-backed persistence for device hardware info and per-page key images and labels.

Each device gets its own database file: ~/.decker/device-<id>.db
"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from decker.common import paths as decker_paths
from decker.common.manager import Manager
from decker.common.model import DeviceHardwareInfo, KeyInfo
from decker.server.pages import initial_page_id

if TYPE_CHECKING:
    from decker.server.server_context import ServerContext

_SCHEMA_DEVICES = """
CREATE TABLE IF NOT EXISTS devices (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    vendor_id   INTEGER NOT NULL,
    product_id  INTEGER NOT NULL,
    num_keys    INTEGER NOT NULL,
    serial      TEXT,
    path        TEXT NOT NULL DEFAULT '',
    key_layout  TEXT NOT NULL DEFAULT '[]',
    last_seen   DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

_SCHEMA_KEY_IMAGES = """
CREATE TABLE IF NOT EXISTS page_key_images (
    page_id     TEXT NOT NULL,
    key_index   INTEGER NOT NULL,
    image       BLOB NOT NULL,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (page_id, key_index)
)
"""

_SCHEMA_KEY_LABELS = """
CREATE TABLE IF NOT EXISTS page_key_labels (
    page_id     TEXT NOT NULL,
    key_index   INTEGER NOT NULL,
    label       TEXT NOT NULL,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (page_id, key_index)
)
"""

# Tables used before pages existed: (legacy table, page table, value column). Migrated on first open.
_LEGACY_TABLES = (("key_images", "page_key_images", "image"), ("key_labels", "page_key_labels", "label"))

_DB_PREFIX = "device-"
_DB_SUFFIX = ".db"


class DeviceStateStore(Manager):
    """Persists device hardware info, per-key images, and per-key labels.

    Each device is stored in its own file: ~/.decker/device-<id>.db
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir
        self._lock = threading.Lock()
        self._connections: dict[str, sqlite3.Connection] = {}

    def create(self, context: "ServerContext") -> None:
        """Ensure the data directory exists."""
        self._resolve_data_dir().mkdir(parents=True, exist_ok=True)

    def destroy(self) -> None:
        """Close all open device database connections."""
        with self._lock:
            for conn in self._connections.values():
                conn.close()
            self._connections.clear()

    def _resolve_data_dir(self) -> Path:
        return self._data_dir if self._data_dir is not None else decker_paths.home()

    def _get_conn(self, device_id: str) -> sqlite3.Connection:
        """Return (creating if needed) the SQLite connection for device_id."""
        if device_id not in self._connections:
            db_path = self._resolve_data_dir() / f"{_DB_PREFIX}{device_id}{_DB_SUFFIX}"
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            for schema in [_SCHEMA_DEVICES, _SCHEMA_KEY_IMAGES, _SCHEMA_KEY_LABELS]:
                conn.execute(schema)
            _migrate_to_pages(conn, device_id)
            conn.commit()
            self._connections[device_id] = conn
        return self._connections[device_id]

    def _close_device(self, device_id: str) -> None:
        """Close and remove the cached connection for device_id (if open)."""
        conn = self._connections.pop(device_id, None)
        if conn is not None:
            conn.close()

    # ------------------------------------------------------------------
    # Device hardware info
    # ------------------------------------------------------------------

    def save_device(self, info: DeviceHardwareInfo) -> None:
        """Upsert device hardware metadata into its per-device database."""
        if info.id is None:
            return
        key_layout = json.dumps(
            [
                {
                    "row": k.row,
                    "col": k.col,
                    "pixel_width": k.pixel_width,
                    "pixel_height": k.pixel_height,
                    "type": k.type,
                }
                for k in info.keys
            ]
        )
        with self._lock:
            conn = self._get_conn(info.id)
            conn.execute(
                """
                INSERT INTO devices (id, type, vendor_id, product_id, num_keys, serial, path, key_layout, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    type       = excluded.type,
                    vendor_id  = excluded.vendor_id,
                    product_id = excluded.product_id,
                    num_keys   = excluded.num_keys,
                    serial     = excluded.serial,
                    path       = excluded.path,
                    key_layout = excluded.key_layout,
                    last_seen  = CURRENT_TIMESTAMP
                """,
                (
                    info.id,
                    info.type,
                    info.vendor_id,
                    info.product_id,
                    info.num_keys,
                    info.serial,
                    info.path,
                    key_layout,
                ),
            )
            conn.commit()

    def get_device(self, device_id: str) -> DeviceHardwareInfo | None:
        """Return cached hardware info for the given device ID, or None if unknown."""
        db_path = self._resolve_data_dir() / f"{_DB_PREFIX}{device_id}{_DB_SUFFIX}"
        if not db_path.exists():
            return None
        with self._lock:
            row = (
                self._get_conn(device_id)
                .execute(
                    "SELECT type, vendor_id, product_id, num_keys, serial, path, key_layout FROM devices WHERE id = ?",
                    (device_id,),
                )
                .fetchone()
            )
        if row is None:
            return None
        return self._row_to_hw_info(device_id, row)

    def get_all_devices(self) -> list[DeviceHardwareInfo]:
        """Return cached hardware info for all previously seen devices."""
        data_dir = self._resolve_data_dir()
        if not data_dir.exists():
            return []
        result: list[DeviceHardwareInfo] = []
        for db_file in data_dir.glob(f"{_DB_PREFIX}*{_DB_SUFFIX}"):
            device_id = db_file.stem[len(_DB_PREFIX) :]
            info = self.get_device(device_id)
            if info is not None:
                result.append(info)
        return result

    # ------------------------------------------------------------------
    # Key images and labels (per page)
    # ------------------------------------------------------------------

    def save_key_image(self, device_id: str, page_id: str, key_index: int, image: bytes) -> None:
        """Upsert the rendered PNG for a key slot on a page."""
        self._upsert("page_key_images", "image", device_id, page_id, key_index, image)

    def get_key_image(self, device_id: str, page_id: str, key_index: int) -> bytes | None:
        """Return the last persisted PNG for a key slot on a page, or None."""
        value = self._select_one("page_key_images", "image", device_id, page_id, key_index)
        return bytes(value) if value is not None else None

    def get_all_key_images(self, device_id: str, page_id: str) -> list[tuple[int, bytes]]:
        """Return all persisted (key_index, image) pairs for a page."""
        return [(key, bytes(value)) for key, value in self._select_all("page_key_images", "image", device_id, page_id)]

    def save_key_label(self, device_id: str, page_id: str, key_index: int, label: str) -> None:
        """Upsert the display label for a key slot on a page."""
        self._upsert("page_key_labels", "label", device_id, page_id, key_index, label)

    def get_key_label(self, device_id: str, page_id: str, key_index: int) -> str | None:
        """Return the last persisted display label for a key slot on a page, or None."""
        value = self._select_one("page_key_labels", "label", device_id, page_id, key_index)
        return str(value) if value is not None else None

    def get_all_key_labels(self, device_id: str, page_id: str) -> list[tuple[int, str]]:
        """Return all persisted (key_index, label) pairs for a page."""
        return [(key, str(value)) for key, value in self._select_all("page_key_labels", "label", device_id, page_id)]

    def delete_key_state(self, device_id: str, page_id: str, key_index: int) -> None:
        """Remove both the persisted image and label for a key slot on a page."""
        with self._lock:
            conn = self._get_conn(device_id)
            for table in ("page_key_images", "page_key_labels"):
                conn.execute(f"DELETE FROM {table} WHERE page_id = ? AND key_index = ?", (page_id, key_index))
            conn.commit()

    def delete_page_state(self, device_id: str, page_id: str) -> None:
        """Remove every persisted image and label on a page."""
        with self._lock:
            conn = self._get_conn(device_id)
            for table in ("page_key_images", "page_key_labels"):
                conn.execute(f"DELETE FROM {table} WHERE page_id = ?", (page_id,))
            conn.commit()

    # ------------------------------------------------------------------
    # Bulk delete
    # ------------------------------------------------------------------

    def delete_all_key_state_for_device(self, device_id: str) -> None:
        """Delete the per-device database file, wiping all state for that device."""
        with self._lock:
            self._close_device(device_id)
            db_path = self._resolve_data_dir() / f"{_DB_PREFIX}{device_id}{_DB_SUFFIX}"
            db_path.unlink(missing_ok=True)

    def delete_all_key_state(self) -> None:
        """Delete all per-device database files in the data directory."""
        with self._lock:
            for device_id in list(self._connections):
                self._close_device(device_id)
            data_dir = self._resolve_data_dir()
            if data_dir.exists():
                for db_file in data_dir.glob(f"{_DB_PREFIX}*{_DB_SUFFIX}"):
                    db_file.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _upsert(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, table: str, column: str, device_id: str, page_id: str, key_index: int, value: bytes | str
    ) -> None:
        with self._lock:
            conn = self._get_conn(device_id)
            conn.execute(
                f"""
                INSERT INTO {table} (page_id, key_index, {column}, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(page_id, key_index) DO UPDATE SET
                    {column}   = excluded.{column},
                    updated_at = CURRENT_TIMESTAMP
                """,
                (page_id, key_index, value),
            )
            conn.commit()

    def _select_one(self, table: str, column: str, device_id: str, page_id: str, key_index: int) -> Any:
        with self._lock:
            row = (
                self._get_conn(device_id)
                .execute(f"SELECT {column} FROM {table} WHERE page_id = ? AND key_index = ?", (page_id, key_index))
                .fetchone()
            )
        return row[column] if row else None

    def _select_all(self, table: str, column: str, device_id: str, page_id: str) -> list[tuple[int, Any]]:
        with self._lock:
            rows = (
                self._get_conn(device_id)
                .execute(f"SELECT key_index, {column} FROM {table} WHERE page_id = ? ORDER BY key_index", (page_id,))
                .fetchall()
            )
        return [(row["key_index"], row[column]) for row in rows]

    @staticmethod
    def _row_to_hw_info(device_id: str, row: sqlite3.Row) -> DeviceHardwareInfo:
        keys = [
            KeyInfo(
                row=k["row"],
                col=k["col"],
                pixel_width=k["pixel_width"],
                pixel_height=k["pixel_height"],
                type=k["type"],
            )
            for k in json.loads(row["key_layout"])
        ]
        return DeviceHardwareInfo(
            id=device_id,
            type=row["type"],
            vendor_id=row["vendor_id"],
            product_id=row["product_id"],
            num_keys=row["num_keys"],
            keys=keys,
            serial=row["serial"],
            path=row["path"],
        )


def _migrate_to_pages(conn: sqlite3.Connection, device_id: str) -> None:
    """Move key images and labels stored before pages existed onto the device's first page."""
    existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
    for legacy, table, column in _LEGACY_TABLES:
        if legacy not in existing:
            continue
        conn.execute(
            f"""
            INSERT OR IGNORE INTO {table} (page_id, key_index, {column}, updated_at)
            SELECT ?, key_index, {column}, updated_at FROM {legacy}
            """,
            (initial_page_id(device_id),),
        )
        conn.execute(f"DROP TABLE {legacy}")
