"""Runs blocking calls on worker threads and delivers their results on the Qt thread."""

import logging
import threading
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal


class CallBridge(QObject):
    """Create on the UI thread; `submit` work runs on a worker and `done(result)` runs on the UI thread."""

    _delivered = pyqtSignal(object, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._delivered.connect(lambda done, result: done(result))
        self._threads: list[threading.Thread] = []

    def submit(self, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        """Run work on a new thread; an exception raised by work is passed to done as the result."""

        def target() -> None:
            try:
                result: Any = work()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logging.exception("Background call failed")
                result = exc
            try:
                self._delivered.emit(done, result)
            except RuntimeError:  # the owner was deleted while the call ran; nobody is waiting for the result
                logging.debug("Call result dropped: its bridge is gone")

        self._threads = [t for t in self._threads if t.is_alive()]
        thread = threading.Thread(target=target, daemon=True)
        self._threads.append(thread)
        thread.start()

    def join(self, timeout: float = 5.0) -> None:
        """Wait for running calls (tests)."""
        for thread in list(self._threads):
            thread.join(timeout)
