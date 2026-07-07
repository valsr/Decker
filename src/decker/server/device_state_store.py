"""SQLite-backed persistence for device hardware info, key images, and key labels.

Each device gets its own database file: ~/.decker/device-<id>.db
"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from decker.common import paths as decker_paths
from decker.common.manager import Manager
from decker.common.model import DeviceHardwareInfo, KeyInfo

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
CREATE TABLE IF NOT EXISTS key_images (
    key_index   INTEGER PRIMARY KEY,
    image       BLOB NOT NULL,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

_SCHEMA_KEY_LABELS = """
CREATE TABLE IF NOT EXISTS key_labels (
    key_index   INTEGER PRIMARY KEY,
    label       TEXT NOT NULL,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

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
    # Key images
    # ------------------------------------------------------------------

    def save_key_image(self, device_id: str, key_index: int, image: bytes) -> None:
        """Upsert the rendered PNG for a key slot."""
        with self._lock:
            conn = self._get_conn(device_id)
            conn.execute(
                """
                INSERT INTO key_images (key_index, image, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key_index) DO UPDATE SET
                    image      = excluded.image,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key_index, image),
            )
            conn.commit()

    def get_key_image(self, device_id: str, key_index: int) -> bytes | None:
        """Return the last persisted PNG for a key slot, or None."""
        with self._lock:
            row = (
                self._get_conn(device_id)
                .execute(
                    "SELECT image FROM key_images WHERE key_index = ?",
                    (key_index,),
                )
                .fetchone()
            )
        return bytes(row["image"]) if row else None

    def get_all_key_images(self, device_id: str) -> list[tuple[int, bytes]]:
        """Return all persisted (key_index, image) pairs for a device."""
        with self._lock:
            rows = self._get_conn(device_id).execute("SELECT key_index, image FROM key_images").fetchall()
        return [(row["key_index"], bytes(row["image"])) for row in rows]

    def delete_key_image(self, device_id: str, key_index: int) -> None:
        """Remove the persisted image for a key slot."""
        with self._lock:
            conn = self._get_conn(device_id)
            conn.execute("DELETE FROM key_images WHERE key_index = ?", (key_index,))
            conn.commit()

    # ------------------------------------------------------------------
    # Key labels
    # ------------------------------------------------------------------

    def save_key_label(self, device_id: str, key_index: int, label: str) -> None:
        """Upsert the display label for a key slot."""
        with self._lock:
            conn = self._get_conn(device_id)
            conn.execute(
                """
                INSERT INTO key_labels (key_index, label, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key_index) DO UPDATE SET
                    label      = excluded.label,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key_index, label),
            )
            conn.commit()

    def get_key_label(self, device_id: str, key_index: int) -> str | None:
        """Return the last persisted display label for a key slot, or None."""
        with self._lock:
            row = (
                self._get_conn(device_id)
                .execute(
                    "SELECT label FROM key_labels WHERE key_index = ?",
                    (key_index,),
                )
                .fetchone()
            )
        return row["label"] if row else None

    def get_all_key_labels(self, device_id: str) -> list[tuple[int, str]]:
        """Return all persisted (key_index, label) pairs for a device."""
        with self._lock:
            rows = self._get_conn(device_id).execute("SELECT key_index, label FROM key_labels").fetchall()
        return [(row["key_index"], row["label"]) for row in rows]

    def delete_key_label(self, device_id: str, key_index: int) -> None:
        """Remove the persisted label for a key slot."""
        with self._lock:
            conn = self._get_conn(device_id)
            conn.execute("DELETE FROM key_labels WHERE key_index = ?", (key_index,))
            conn.commit()

    # ------------------------------------------------------------------
    # Bulk delete
    # ------------------------------------------------------------------

    def delete_key_state(self, device_id: str, key_index: int) -> None:
        """Remove both the persisted image and label for a key slot."""
        self.delete_key_image(device_id, key_index)
        self.delete_key_label(device_id, key_index)

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
