"""Per-device screensaver runtime: idle scheduling, activation, waking and gallery rotation."""

import io
import logging
import threading
import time
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Callable, Protocol

from PIL import Image

from decker.common.manager import Manager
from decker.common.model import DeviceHardwareInfo, ScreensaverSettings
from decker.server.screensaver.compose import CanvasLayout, canvas_layout, compose
from decker.server.screensaver.screensaver_store import ScreensaverStore
from decker.server.screensaver.source import (
    GalleryCursor,
    ScreensaverImageError,
    load_image,
)

if TYPE_CHECKING:
    from decker.server.server_context import ServerContext

_LOGGER = logging.getLogger(__name__)
_TICK_S = 1.0
_JOIN_S = 5.0
_MAX_GALLERY_TRIES = 64


class _HwInfoSource(Protocol):  # pylint: disable=too-few-public-methods
    def get_hw_info(self) -> DeviceHardwareInfo:
        """Hardware metadata, including the key layout."""


class ScreensaverDevices(Protocol):
    """The DeviceManager surface the engine drives."""

    def opened_device_ids(self) -> list[str]:
        """Ids of the open devices."""

    def open_device(self, device_id: str) -> _HwInfoSource | None:
        """The device, opened if needed."""

    def set_overlay(self, device_id: str, active: bool) -> None:
        """Hold back or release page writes and key events."""

    def overlay_active(self, device_id: str) -> bool:
        """Whether the overlay is set."""

    def set_brightness(self, device_id: str, percent: int) -> None:
        """Set the deck brightness."""

    def write_overlay(self, device_id: str, images: list[bytes] | None) -> bool:
        """Write one PNG per key, or blank all keys."""

    def show_page(self, device_id: str, page_id: str) -> bool:
        """Redraw a page from cached state."""

    def set_activity_hook(self, hook: Callable[[str], None] | None) -> None:
        """Register the key activity hook."""

    def set_wake_hook(self, hook: Callable[[str], None] | None) -> None:
        """Register the wake hook."""


@dataclass(frozen=True)
class ScreensaverStatus:
    """A device's runtime screensaver state."""

    active: bool
    last_error: str


@dataclass
class _Runtime:
    last_activity: float
    op_lock: threading.RLock = field(default_factory=threading.RLock)  # serialises activate/deactivate writes
    generation: int = 0  # bumped by every activation, wake and key press; a stale render never writes
    active: bool = False
    last_error: str = ""
    cursor: GalleryCursor = field(default_factory=GalleryCursor)
    next_gallery: float | None = None
    warned: bool = False


class ScreensaverEngine(Manager):  # pylint: disable=too-many-instance-attributes
    """Activates each open device's screensaver when idle and wakes it on a key press, RPC or reopen."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        store: ScreensaverStore,
        devices: ScreensaverDevices,
        active_page: Callable[[str], str],
        on_change: Callable[[str, bool], None],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._devices = devices
        self._active_page = active_page
        self._on_change = on_change
        self._clock = clock
        self._lock = threading.Lock()  # guards _runtimes and every _Runtime field except op_lock
        self._runtimes: dict[str, _Runtime] = {}
        self._wake = threading.Condition(threading.Lock())
        self._pending: set[str] = set()
        self._stopping = False
        self._thread: threading.Thread | None = None

    def create(self, context: "ServerContext") -> None:
        """Register the key hooks and start the scheduler thread."""
        self._devices.set_activity_hook(self.note_activity)
        self._devices.set_wake_hook(self.request_wake)
        with self._wake:
            self._stopping = False
        self._thread = threading.Thread(target=self._run, name="screensaver", daemon=True)
        self._thread.start()

    def destroy(self) -> None:
        """Stop the scheduler thread and wake every active device."""
        self._devices.set_activity_hook(None)
        self._devices.set_wake_hook(None)
        with self._wake:
            self._stopping = True
            self._wake.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=_JOIN_S)
            self._thread = None
        with self._lock:
            active = [device_id for device_id, rt in self._runtimes.items() if rt.active]
        for device_id in active:
            self._safely(partial(self.deactivate, device_id), f"waking {device_id}")

    def note_activity(self, device_id: str) -> None:
        """Push the idle deadline out and cancel an activation being rendered; cheap, safe on the HID thread."""
        now = self._clock()
        with self._lock:
            rt = self._runtime_locked(device_id, now)
            rt.last_activity = now
            rt.generation += 1

    def request_wake(self, device_id: str) -> None:
        """Ask the scheduler thread to deactivate the device; returns at once (called on the HID thread)."""
        with self._lock:
            self._runtime_locked(device_id, self._clock()).generation += 1
        with self._wake:
            self._pending.add(device_id)
            self._wake.notify_all()

    def is_active(self, device_id: str) -> bool:
        """Whether the device's screensaver is showing."""
        with self._lock:
            rt = self._runtimes.get(device_id)
            return rt is not None and rt.active

    def status(self, device_id: str) -> ScreensaverStatus:
        """The device's active flag and last error."""
        with self._lock:
            rt = self._runtimes.get(device_id)
            return ScreensaverStatus(rt.active, rt.last_error) if rt is not None else ScreensaverStatus(False, "")

    def activate(self, device_id: str) -> bool:
        """Show the screensaver now (whatever the timeout); False if the device is not open or it was cancelled."""
        with self._lock:
            rt = self._runtime_locked(device_id, self._clock())
            rt.generation += 1
            generation = rt.generation
        settings = self._settings(device_id)
        layout = self._layout(device_id, settings)
        if layout is None:
            return False
        images, error = self._render(settings, layout, rt)
        with rt.op_lock:
            with self._lock:
                if rt.generation != generation:
                    return False
            self._devices.set_overlay(device_id, True)  # also stops the device's animations
            self._write(device_id, images)
            self._devices.set_brightness(device_id, settings.saver_brightness)
            with self._lock:
                rt.active = True
                rt.last_error = error
                rt.next_gallery = self._next_gallery(settings)
            self._notify(device_id, True)
        return True

    def deactivate(self, device_id: str) -> bool:
        """Wake the device: release the overlay, restore brightness and redraw the active page; False if awake."""
        with self._lock:
            rt = self._runtime_locked(device_id, self._clock())
            rt.generation += 1
        with rt.op_lock:
            overlay = self._devices.overlay_active(device_id)
            with self._lock:
                was_active = rt.active or overlay
                rt.active = False
                rt.next_gallery = None
                rt.last_activity = self._clock()
            if not was_active:
                return False
            settings = self._settings(device_id)
            self._devices.set_overlay(device_id, False)
            self._devices.set_brightness(device_id, settings.brightness)
            self._devices.show_page(device_id, self._active_page(device_id))
            self._notify(device_id, False)
        return True

    def apply_settings(self, device_id: str) -> None:
        """Re-apply normal brightness when awake and restart the idle countdown."""
        settings = self._settings(device_id)
        now = self._clock()
        with self._lock:
            rt = self._runtime_locked(device_id, now)
            rt.last_activity = now
            active = rt.active
            if active:
                rt.next_gallery = self._next_gallery(settings)
        if not active:
            self._devices.set_brightness(device_id, settings.brightness)

    def device_opened(self, device_id: str) -> None:
        """Apply normal brightness to a (re)opened device and treat it as activity, waking an active overlay."""
        now = self._clock()
        with self._lock:
            rt = self._runtime_locked(device_id, now)
            rt.last_activity = now
            active = rt.active
        if active or self._devices.overlay_active(device_id):
            self.deactivate(device_id)
        else:
            self._devices.set_brightness(device_id, self._settings(device_id).brightness)

    def tick(self, now: float | None = None) -> None:
        """One scheduler pass: activate idle devices and advance interval galleries."""
        current = self._clock() if now is None else now
        for device_id in self._devices.opened_device_ids():
            settings = self._settings(device_id)
            with self._lock:
                rt = self._runtime_locked(device_id, current)
                idle_due = (
                    not rt.active
                    and settings.timeout_minutes > 0
                    and current >= rt.last_activity + settings.timeout_minutes * 60
                )
                gallery_due = rt.active and rt.next_gallery is not None and current >= rt.next_gallery
                if gallery_due:
                    rt.next_gallery = current + settings.gallery_minutes * 60
            if idle_due:
                self._safely(partial(self.activate, device_id), f"activating {device_id}")
            elif gallery_due:
                self._safely(partial(self._refresh, device_id), f"gallery advance of {device_id}")

    def _refresh(self, device_id: str) -> None:
        with self._lock:
            rt = self._runtime_locked(device_id, self._clock())
            generation = rt.generation
        settings = self._settings(device_id)
        layout = self._layout(device_id, settings)
        if layout is None:
            return
        images, error = self._render(settings, layout, rt)
        with rt.op_lock:
            with self._lock:
                if rt.generation != generation or not rt.active:
                    return
                rt.last_error = error
            self._write(device_id, images)

    def _run(self) -> None:
        next_tick = time.monotonic()
        while True:
            with self._wake:
                while not self._stopping and not self._pending and time.monotonic() < next_tick:
                    self._wake.wait(max(0.0, next_tick - time.monotonic()))
                if self._stopping:
                    return
                pending = sorted(self._pending)
                self._pending.clear()
            for device_id in pending:
                self._safely(partial(self.deactivate, device_id), f"waking {device_id}")
            if time.monotonic() >= next_tick:
                self._safely(self.tick, "scheduler tick")
                next_tick = time.monotonic() + _TICK_S

    def _runtime_locked(self, device_id: str, now: float) -> _Runtime:
        rt = self._runtimes.get(device_id)
        if rt is None:
            rt = self._runtimes[device_id] = _Runtime(last_activity=now)
        return rt

    def _settings(self, device_id: str) -> ScreensaverSettings:
        try:
            settings = self._store.get(device_id)
        except ValueError as exc:
            with self._lock:
                rt = self._runtime_locked(device_id, self._clock())
                warn, rt.warned = not rt.warned, True
            if warn:
                _LOGGER.warning("screensaver settings of %s are invalid, using defaults: %s", device_id, exc)
            return ScreensaverSettings()
        with self._lock:
            self._runtime_locked(device_id, self._clock()).warned = False
        return settings

    def _next_gallery(self, settings: ScreensaverSettings) -> float | None:
        if settings.content != "gallery" or settings.gallery_mode != "interval":
            return None
        return self._clock() + settings.gallery_minutes * 60

    def _layout(self, device_id: str, settings: ScreensaverSettings) -> CanvasLayout | None:
        device = self._devices.open_device(device_id)
        if device is None:
            return None
        keys = [key for key in device.get_hw_info().keys if key.type == "key"]
        if not keys:
            return None
        rows = max(key.row for key in keys) + 1
        cols = max(key.col for key in keys) + 1
        return canvas_layout(rows, cols, keys[0].pixel_width, settings.bezel, settings.key_mm, settings.gap_mm)

    def _render(
        self, settings: ScreensaverSettings, layout: CanvasLayout, rt: _Runtime
    ) -> tuple[list[bytes] | None, str]:
        try:
            image, error = self._load(settings, layout, rt)
            if image is None:
                return None, error
            return [_png_bytes(face) for face in compose(_on_black(image), layout, settings.scaling)], ""
        except Exception:  # pylint: disable=broad-exception-caught
            _LOGGER.exception("screensaver rendering failed")
            return None, "the screensaver image could not be rendered"

    @staticmethod
    def _load(settings: ScreensaverSettings, layout: CanvasLayout, rt: _Runtime) -> tuple[Image.Image | None, str]:
        if settings.content == "none":
            return None, ""
        if settings.content == "image":
            if not settings.image_path:
                return None, "no image selected"
            try:
                return load_image(settings.image_path, layout.width, layout.height), ""
            except ScreensaverImageError as exc:
                return None, str(exc)
        return _load_gallery(settings.folder_path, layout, rt.cursor)

    def _write(self, device_id: str, images: list[bytes] | None) -> None:
        if not self._devices.write_overlay(device_id, images):
            _LOGGER.warning("screensaver: writing the overlay to %s was not confirmed", device_id)

    def _notify(self, device_id: str, active: bool) -> None:
        self._safely(partial(self._on_change, device_id, active), f"change callback for {device_id}")

    @staticmethod
    def _safely(action: Callable[[], object], what: str) -> None:
        try:
            action()
        except Exception:  # pylint: disable=broad-exception-caught
            _LOGGER.exception("screensaver: %s failed", what)


def _load_gallery(folder: str, layout: CanvasLayout, cursor: GalleryCursor) -> tuple[Image.Image | None, str]:
    error = "the gallery folder has no readable images"
    first: str | None = None
    for _ in range(_MAX_GALLERY_TRIES):
        path = cursor.next_path(folder) if folder else None
        if path is None or path == first:
            break
        first = first or path
        try:
            return load_image(path, layout.width, layout.height), ""
        except ScreensaverImageError as exc:
            _LOGGER.warning("screensaver: skipping gallery image: %s", exc)
            error = f"the gallery folder has no readable images ({exc})"
    return None, error


def _on_black(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    background.alpha_composite(rgba)
    return background.convert("RGB")


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
