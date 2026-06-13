"""Server-side GUI application — a PyQt6 window managed by the RPyC service."""

from __future__ import annotations

import importlib.metadata
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QMainWindow


class Application:
    """PyQt6 window launched by the server when a client calls start().

    Window creation and teardown are always scheduled onto the Qt main thread
    via QTimer.singleShot so this class is safe to drive from RPyC service threads.
    """

    _WIDTH = 1200
    _HEIGHT = 800

    def __init__(self) -> None:
        self._title: str = importlib.metadata.metadata("decker")["Name"]
        self._window: "QMainWindow | None" = None
        self._running: bool = False

    def run_threaded(self) -> None:
        """Schedule window creation on the Qt main thread (thread-safe)."""
        from PyQt6.QtCore import QTimer  # pylint: disable=import-outside-toplevel
        from PyQt6.QtWidgets import (
            QApplication,  # pylint: disable=import-outside-toplevel
        )

        if self._running:
            logging.warning("Application is already running")
            return
        QTimer.singleShot(0, QApplication.instance(), self._show)  # type: ignore[call-overload]
        logging.info("Application scheduled to start")

    def stop(self) -> None:
        """Schedule window teardown on the Qt main thread (thread-safe)."""
        from PyQt6.QtCore import QTimer  # pylint: disable=import-outside-toplevel
        from PyQt6.QtWidgets import (
            QApplication,  # pylint: disable=import-outside-toplevel
        )

        if not self._running:
            logging.warning("Application is not running")
            return
        QTimer.singleShot(0, QApplication.instance(), self._close)  # type: ignore[call-overload]
        logging.info("Application scheduled to stop")

    def is_running(self) -> bool:
        """Return True if the window is currently visible."""
        return self._running

    # ------------------------------------------------------------------
    # Main-thread callbacks
    # ------------------------------------------------------------------

    def _show(self) -> None:
        from PyQt6.QtWidgets import (
            QMainWindow,  # pylint: disable=import-outside-toplevel
        )

        window = QMainWindow()
        window.setWindowTitle(self._title)
        window.resize(self._WIDTH, self._HEIGHT)
        window.destroyed.connect(self._on_destroyed)
        window.show()
        self._window = window
        self._running = True
        logging.info("Application window shown")

    def _close(self) -> None:
        if self._window is not None:
            self._window.close()

    def _on_destroyed(self) -> None:
        self._window = None
        self._running = False
        logging.info("Application window closed")
