"""Per-device in-memory key state for the page on the hardware, backed by DeviceStateStore."""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from decker.animation.model import AnimationSpec
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
    """Tracks mutable key state for the page currently shown on one device, persisting changes per page.

    Call update_key_image / update_key_label on each write-through event.
    Call get_key_state to read a consistent snapshot for any key index.
    Call switch_page when the device shows a different page.
    Key animations are kept per page in memory only (the plugin host recomposes them after a restart).
    """

    def __init__(
        self,
        device_id: str,
        store: "DeviceStateStore | None",
        press_state_getter: Callable[[int], KeyPressState],
        page_id: str,
    ) -> None:
        self._device_id = device_id
        self._page_id = page_id
        self._store = store
        self._get_press_state = press_state_getter
        self._lock = threading.Lock()
        self._images: dict[int, bytes] = {}
        self._labels: dict[int, str] = {}
        self._animations: dict[str, dict[int, AnimationSpec]] = {}  # page id -> key index -> spec

    # ------------------------------------------------------------------
    # Write-through updates
    # ------------------------------------------------------------------

    def update_key_image(self, key_index: int, image: bytes) -> None:
        """Store the rendered PNG for a key in memory and persist it."""
        with self._lock:
            unchanged = self._images.get(key_index) == image
            self._images[key_index] = image
        if self._store is not None and not unchanged:
            self._store.save_key_image(self._device_id, self._page_id, key_index, image)

    def has_image(self, key_index: int) -> bool:
        """Whether an image is held for the key."""
        with self._lock:
            return key_index in self._images

    def update_key_label(self, key_index: int, label: str) -> None:
        """Store the display label for a key in memory and persist it."""
        with self._lock:
            self._labels[key_index] = label
        if self._store is not None:
            self._store.save_key_label(self._device_id, self._page_id, key_index, label)

    def set_key_animation(self, key_index: int, spec: AnimationSpec | None) -> None:
        """Record (or with None forget) the animation of a key on the current page, in memory only."""
        with self._lock:
            page = self._animations.setdefault(self._page_id, {})
            if spec is None:
                page.pop(key_index, None)
            else:
                page[key_index] = spec

    def forget_animation(self, page_id: str, key_index: int) -> None:
        """Drop the animation recorded for a key of any page (the page's stored state is deleted separately)."""
        with self._lock:
            self._animations.get(page_id, {}).pop(key_index, None)

    def clear_key(self, key_index: int) -> None:
        """Remove in-memory image, label and animation for a key and delete the image and label from the store."""
        with self._lock:
            self._images.pop(key_index, None)
            self._labels.pop(key_index, None)
            self._animations.get(self._page_id, {}).pop(key_index, None)
        if self._store is not None:
            self._store.delete_key_state(self._device_id, self._page_id, key_index)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    @property
    def page_id(self) -> str:
        """The page whose key state is held in memory (the page shown on the hardware)."""
        return self._page_id

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

    def get_key_animation(self, key_index: int) -> AnimationSpec | None:
        """Return the animation recorded for a key on the current page, or None; a key without an image has none."""
        with self._lock:
            return self._animations.get(self._page_id, {}).get(key_index) if key_index in self._images else None

    def get_all_animations(self) -> dict[int, AnimationSpec]:
        """Return a copy of the current page's recorded animations by key index, for keys that hold an image."""
        with self._lock:
            return {k: spec for k, spec in self._animations.get(self._page_id, {}).items() if k in self._images}

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
        """Populate in-memory state from the current page's persisted images and labels."""
        if self._store is None:
            return
        with self._lock:
            for key_index, image in self._store.get_all_key_images(self._device_id, self._page_id):
                self._images[key_index] = image
            for key_index, label in self._store.get_all_key_labels(self._device_id, self._page_id):
                self._labels[key_index] = label

    def switch_page(self, page_id: str) -> None:
        """Drop the in-memory state and load page_id's persisted images and labels (and its animations) instead."""
        with self._lock:
            self._page_id = page_id
            self._images.clear()
            self._labels.clear()
        self.restore_from_store()
