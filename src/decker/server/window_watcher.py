"""Debounced, self-retrying watcher over a window backend."""

import logging
import threading
from dataclasses import asdict, dataclass
from typing import Any, Callable

from decker.common.model import WindowInfo
from decker.server.windows.backend import WindowBackend

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WatcherTimings:
    """Injectable delays, in seconds."""

    debounce: float = 0.15
    retry_base: float = 1.0
    retry_cap: float = 30.0
    pick_timeout: float = 60.0


class WindowWatcher:  # pylint: disable=too-many-instance-attributes
    """Runs a window backend: debounces changes, retries failures and manages picks."""

    def __init__(
        self,
        backend: WindowBackend,
        on_window: Callable[[WindowInfo], None],
        push: Callable[[str, WindowInfo], None],
        on_status: Callable[[], None],
        timings: WatcherTimings | None = None,
    ) -> None:
        self._backend = backend
        self._on_window = on_window
        self._push = push
        self._on_status = on_status
        self._timings = timings or WatcherTimings()
        self._lock = threading.RLock()
        self._state = "unavailable"
        self._reason = "not started"
        self._running = False
        self._last: WindowInfo | None = None
        self._pending: WindowInfo | None = None
        self._debounce_timer: threading.Timer | None = None
        self._retry_timer: threading.Timer | None = None
        self._attempts = 0
        self._pick_token: object | None = None
        self._pick_timer: threading.Timer | None = None

    def start(self) -> None:
        """Start the backend; failures retry with backoff."""
        with self._lock:
            self._running = True
        self._launch()

    def stop(self) -> None:
        """Cancel timers and stop the backend."""
        with self._lock:
            self._running = False
            for timer in (self._debounce_timer, self._retry_timer, self._pick_timer):
                if timer is not None:
                    timer.cancel()
            self._debounce_timer = self._retry_timer = self._pick_timer = None
            self._pick_token = None
        self._stop_backend()

    def status(self) -> dict[str, Any]:
        """Report state, reason, backend and the last window."""
        with self._lock:
            window = asdict(self._last) if self._last is not None else None
            return {
                "state": self._state,
                "reason": self._reason,
                "backend": self._backend.name,
                "supports_pick": self._backend.supports_pick,
                "window": window,
            }

    def last_window(self) -> WindowInfo | None:
        """Return the most recent distinct window, if any."""
        with self._lock:
            return self._last

    def pick(self, on_result: Callable[[WindowInfo | None], None]) -> bool:
        """Start a one-shot window pick; False when unsupported, inactive or already picking."""
        token = object()
        with self._lock:
            if not self._backend.supports_pick or self._state != "active" or self._pick_token is not None:
                return False
            self._pick_token = token
            self._pick_timer = threading.Timer(self._timings.pick_timeout, self._finish_pick, (token, None, on_result))
            self._pick_timer.daemon = True
            self._pick_timer.start()
        try:
            self._backend.pick(lambda window: self._finish_pick(token, window, on_result))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            LOGGER.warning("window pick failed: %s", exc)
            self._finish_pick(token, None, None)
            return False
        return True

    def _finish_pick(
        self, token: object, window: WindowInfo | None, on_result: Callable[[WindowInfo | None], None] | None
    ) -> None:
        with self._lock:
            if self._pick_token is not token:
                return
            self._pick_token = None
            if self._pick_timer is not None:
                self._pick_timer.cancel()
                self._pick_timer = None
        if on_result is not None:
            on_result(window)

    def _launch(self) -> None:
        try:
            status = self._backend.available()
            if status.state != "active":
                self._set_state(status.state, status.reason)
                if status.state == "unavailable":
                    self._schedule_retry()
                return
            self._backend.start(self._on_change)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._fail(exc)
            return
        with self._lock:
            self._attempts = 0
        self._set_state("active", "")

    def _set_state(self, state: str, reason: str) -> None:
        with self._lock:
            self._state = state
            self._reason = reason
        self._on_status()

    def _fail(self, exc: Exception) -> None:
        LOGGER.warning("window backend %s failed: %s", self._backend.name, exc)
        self._stop_backend()
        self._set_state("unavailable", str(exc) or type(exc).__name__)
        self._schedule_retry()

    def _stop_backend(self) -> None:
        try:
            self._backend.stop()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            LOGGER.debug("window backend stop failed: %s", exc)

    def _schedule_retry(self) -> None:
        with self._lock:
            if not self._running:
                return
            delay = min(self._timings.retry_base * (2**self._attempts), self._timings.retry_cap)
            self._attempts += 1
            if self._retry_timer is not None:
                self._retry_timer.cancel()
            self._retry_timer = threading.Timer(delay, self._retry)
            self._retry_timer.daemon = True
            self._retry_timer.start()

    def _retry(self) -> None:
        with self._lock:
            if not self._running:
                return
        self._launch()

    def _on_change(self, window: WindowInfo) -> None:
        try:
            with self._lock:
                if not self._running or window == self._last:
                    return
                self._last = window
                self._pending = window
                if self._debounce_timer is not None:
                    self._debounce_timer.cancel()
                self._debounce_timer = threading.Timer(self._timings.debounce, self._evaluate)
                self._debounce_timer.daemon = True
                self._debounce_timer.start()
            self._push("window_changed", window)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._fail(exc)

    def _evaluate(self) -> None:
        with self._lock:
            window, self._pending = self._pending, None
            if window is None or not self._running:
                return
        try:
            self._on_window(window)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._fail(exc)
