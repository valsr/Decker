"""SQLite-backed persistence for device hardware info, key images, and key labels."""

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
    device_id   TEXT NOT NULL,
    key_index   INTEGER NOT NULL,
    image       BLOB NOT NULL,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (device_id, key_index)
)
"""

_SCHEMA_KEY_LABELS = """
CREATE TABLE IF NOT EXISTS key_labels (
    device_id   TEXT NOT NULL,
    key_index   INTEGER NOT NULL,
    label       TEXT NOT NULL,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (device_id, key_index)
)
"""


class DeviceStateStore(Manager):
    """Persists device hardware info, per-key images, and per-key labels to decker.db."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._lock = threading.Lock()
        self._db_path = Path(db_path) if db_path is not None else decker_paths.db()
        self._conn: sqlite3.Connection | None = None

    def create(self, context: "ServerContext") -> None:
        """Open the SQLite connection and initialise the schema."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        for schema in [_SCHEMA_DEVICES, _SCHEMA_KEY_IMAGES, _SCHEMA_KEY_LABELS]:
            self._db.execute(schema)
        self._db.commit()

    def destroy(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def _db(self) -> sqlite3.Connection:
        assert self._conn is not None, "DeviceStateStore.create() must be called before use"
        return self._conn

    # ------------------------------------------------------------------
    # Device hardware info
    # ------------------------------------------------------------------

    def save_device(self, info: DeviceHardwareInfo) -> None:
        """Upsert device hardware metadata."""
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
            self._db.execute(
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
            self._db.commit()

    def get_device(self, device_id: str) -> DeviceHardwareInfo | None:
        """Return cached hardware info for the given device ID, or None if unknown."""
        with self._lock:
            row = self._db.execute(
                "SELECT type, vendor_id, product_id, num_keys, serial, path, key_layout FROM devices WHERE id = ?",
                (device_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_hw_info(device_id, row)

    def get_all_devices(self) -> list[DeviceHardwareInfo]:
        """Return cached hardware info for all previously seen devices."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, type, vendor_id, product_id, num_keys, serial, path, key_layout FROM devices"
            ).fetchall()
        return [self._row_to_hw_info(row["id"], row) for row in rows]

    # ------------------------------------------------------------------
    # Key images
    # ------------------------------------------------------------------

    def save_key_image(self, device_id: str, key_index: int, image: bytes) -> None:
        """Upsert the rendered PNG for a key slot."""
        with self._lock:
            self._db.execute(
                """
                INSERT INTO key_images (device_id, key_index, image, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(device_id, key_index) DO UPDATE SET
                    image      = excluded.image,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (device_id, key_index, image),
            )
            self._db.commit()

    def get_key_image(self, device_id: str, key_index: int) -> bytes | None:
        """Return the last persisted PNG for a key slot, or None."""
        with self._lock:
            row = self._db.execute(
                "SELECT image FROM key_images WHERE device_id = ? AND key_index = ?",
                (device_id, key_index),
            ).fetchone()
        return bytes(row["image"]) if row else None

    def get_all_key_images(self, device_id: str) -> list[tuple[int, bytes]]:
        """Return all persisted (key_index, image) pairs for a device."""
        with self._lock:
            rows = self._db.execute(
                "SELECT key_index, image FROM key_images WHERE device_id = ?",
                (device_id,),
            ).fetchall()
        return [(row["key_index"], bytes(row["image"])) for row in rows]

    def delete_key_image(self, device_id: str, key_index: int) -> None:
        """Remove the persisted image for a key slot."""
        with self._lock:
            self._db.execute(
                "DELETE FROM key_images WHERE device_id = ? AND key_index = ?",
                (device_id, key_index),
            )
            self._db.commit()

    # ------------------------------------------------------------------
    # Key labels
    # ------------------------------------------------------------------

    def save_key_label(self, device_id: str, key_index: int, label: str) -> None:
        """Upsert the display label for a key slot."""
        with self._lock:
            self._db.execute(
                """
                INSERT INTO key_labels (device_id, key_index, label, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(device_id, key_index) DO UPDATE SET
                    label      = excluded.label,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (device_id, key_index, label),
            )
            self._db.commit()

    def get_key_label(self, device_id: str, key_index: int) -> str | None:
        """Return the last persisted display label for a key slot, or None."""
        with self._lock:
            row = self._db.execute(
                "SELECT label FROM key_labels WHERE device_id = ? AND key_index = ?",
                (device_id, key_index),
            ).fetchone()
        return row["label"] if row else None

    def get_all_key_labels(self, device_id: str) -> list[tuple[int, str]]:
        """Return all persisted (key_index, label) pairs for a device."""
        with self._lock:
            rows = self._db.execute(
                "SELECT key_index, label FROM key_labels WHERE device_id = ?",
                (device_id,),
            ).fetchall()
        return [(row["key_index"], row["label"]) for row in rows]

    def delete_key_label(self, device_id: str, key_index: int) -> None:
        """Remove the persisted label for a key slot."""
        with self._lock:
            self._db.execute(
                "DELETE FROM key_labels WHERE device_id = ? AND key_index = ?",
                (device_id, key_index),
            )
            self._db.commit()

    def delete_key_state(self, device_id: str, key_index: int) -> None:
        """Remove both the persisted image and label for a key slot."""
        self.delete_key_image(device_id, key_index)
        self.delete_key_label(device_id, key_index)

    def delete_all_key_state_for_device(self, device_id: str) -> None:
        """Remove all persisted images and labels for a device."""
        with self._lock:
            self._db.execute("DELETE FROM key_images WHERE device_id = ?", (device_id,))
            self._db.execute("DELETE FROM key_labels WHERE device_id = ?", (device_id,))
            self._db.commit()

    def delete_all_key_state(self) -> None:
        """Remove all persisted images and labels for every device."""
        with self._lock:
            self._db.execute("DELETE FROM key_images")
            self._db.execute("DELETE FROM key_labels")
            self._db.commit()

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
