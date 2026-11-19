"""Counts connected clients and reports when the last one has been gone for a grace period."""

import threading
from collections.abc import Callable


class ClientTracker:
    """Thread-safe client counter; `on_idle` fires once if the count stays at zero for `grace` seconds."""

    def __init__(self, grace: float, on_idle: Callable[[], None]) -> None:
        """Create a tracker that calls `on_idle` after the last client has been gone for `grace` seconds."""
        self._grace = grace
        self._on_idle = on_idle
        self._lock = threading.Lock()
        self._count = 0
        self._seen_client = False
        self._timer: threading.Timer | None = None

    def connected(self) -> None:
        """Record a new client and cancel any pending idle report."""
        with self._lock:
            self._count += 1
            self._seen_client = True
            self._cancel_locked()

    def disconnected(self) -> None:
        """Record a client leaving; start the grace timer when it was the last one."""
        with self._lock:
            self._count = max(0, self._count - 1)
            if self._count == 0 and self._seen_client:
                self._cancel_locked()
                self._timer = threading.Timer(self._grace, self._fire)
                self._timer.daemon = True
                self._timer.start()

    def cancel(self) -> None:
        """Cancel a pending idle report (the server is shutting down anyway)."""
        with self._lock:
            self._cancel_locked()

    def _cancel_locked(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _fire(self) -> None:
        with self._lock:
            if self._count != 0:
                return
            self._timer = None
        self._on_idle()
