"""Server-side GUI application — a PyQt6 window managed by the RPyC service."""

import importlib.metadata
import logging

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QMainWindow


class Application(QObject):
    """PyQt6 window launched by the server when a client calls start().

    Must be created in the Qt main thread. Cross-thread invocations of
    run_threaded() and stop() are safe because Qt queues signal emissions
    from non-main threads automatically.
    """

    _WIDTH = 1200
    _HEIGHT = 800

    _show_requested = pyqtSignal()
    _close_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._title: str = importlib.metadata.metadata("decker")["Name"]
        self._window: QMainWindow | None = None
        self._running: bool = False
        self._show_requested.connect(self._do_show)
        self._close_requested.connect(self._do_close)

    def run_threaded(self) -> None:
        """Schedule window creation on the Qt main thread (thread-safe)."""
        if self._running:
            logging.warning("Application is already running")
            return
        self._show_requested.emit()
        logging.info("Application scheduled to start")

    def stop(self) -> None:
        """Schedule window teardown on the Qt main thread (thread-safe)."""
        if not self._running:
            logging.warning("Application is not running")
            return
        self._close_requested.emit()
        logging.info("Application scheduled to stop")

    def is_running(self) -> bool:
        """Return True if the window is currently visible."""
        return self._running

    # ------------------------------------------------------------------
    # Main-thread callbacks (connected via signals — do not call directly)
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _do_show(self) -> None:
        window = QMainWindow()
        window.setWindowTitle(self._title)
        window.resize(self._WIDTH, self._HEIGHT)
        window.destroyed.connect(self._on_destroyed)
        window.show()
        self._window = window
        self._running = True
        logging.info("Application window shown")

    @pyqtSlot()
    def _do_close(self) -> None:
        if self._window is not None:
            self._window.close()

    def _on_destroyed(self) -> None:
        self._window = None
        self._running = False
        logging.info("Application window closed")
