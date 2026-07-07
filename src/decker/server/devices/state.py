"""Per-device in-memory key state, backed by DeviceStateStore for persistence."""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from decker.common.model import KeyPressState

if TYPE_CHECKING:
    from decker.server.device_state_store import DeviceStateStore


@dataclass
class PerKeyState:
    """Snapshot of runtime state for a single key: image, label, and press gesture."""

    key_index: int
    image: bytes | None = None
    label: str = ""
    press_state: KeyPressState = field(default=KeyPressState.UP)


class DeviceState:
    """Tracks mutable key state for one device and persists changes to the store.

    Call update_key_image / update_key_label on each write-through event.
    Call get_key_state to read a consistent snapshot for any key index.
    """

    def __init__(
        self,
        device_id: str,
        store: "DeviceStateStore | None",
        press_state_getter: Callable[[int], KeyPressState],
    ) -> None:
        self._device_id = device_id
        self._store = store
        self._get_press_state = press_state_getter
        self._lock = threading.Lock()
        self._images: dict[int, bytes] = {}
        self._labels: dict[int, str] = {}

    # ------------------------------------------------------------------
    # Write-through updates
    # ------------------------------------------------------------------

    def update_key_image(self, key_index: int, image: bytes) -> None:
        """Store the rendered PNG for a key in memory and persist it."""
        with self._lock:
            self._images[key_index] = image
        if self._store is not None:
            self._store.save_key_image(self._device_id, key_index, image)

    def update_key_label(self, key_index: int, label: str) -> None:
        """Store the display label for a key in memory and persist it."""
        with self._lock:
            self._labels[key_index] = label
        if self._store is not None:
            self._store.save_key_label(self._device_id, key_index, label)

    def clear_key(self, key_index: int) -> None:
        """Remove in-memory image and label for a key and delete them from the store."""
        with self._lock:
            self._images.pop(key_index, None)
            self._labels.pop(key_index, None)
        if self._store is not None:
            self._store.delete_key_state(self._device_id, key_index)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_key_state(self, key_index: int) -> PerKeyState:
        """Return a snapshot of image, label, and live press state for a key."""
        with self._lock:
            image = self._images.get(key_index)
            label = self._labels.get(key_index, "")
        return PerKeyState(
            key_index=key_index,
            image=image,
            label=label,
            press_state=self._get_press_state(key_index),
        )

    def get_all_images(self) -> list[tuple[int, bytes]]:
        """Return all (key_index, image) pairs currently held in memory."""
        with self._lock:
            return list(self._images.items())

    def get_all_labels(self) -> list[tuple[int, str]]:
        """Return all (key_index, label) pairs currently held in memory."""
        with self._lock:
            return list(self._labels.items())

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    def restore_from_store(self) -> None:
        """Populate in-memory state from persisted images and labels."""
        if self._store is None:
            return
        with self._lock:
            for key_index, image in self._store.get_all_key_images(self._device_id):
                self._images[key_index] = image
            for key_index, label in self._store.get_all_key_labels(self._device_id):
                self._labels[key_index] = label
