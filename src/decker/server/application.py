"""Tkinter-based GUI application wrapper."""

import importlib.metadata
import logging
import threading
from typing import Any


class Application:
    """
    Main application class for the Decker application.

    This class serves as the entry point for the application, handling command-line arguments,
    logging configuration, and starting the GUI.
    """

    def __init__(self) -> None:
        self._initial_window_size = (1200, 800)
        self._initial_window_title = importlib.metadata.metadata("decker")["Name"]
        self._window_stack: list[Any] = []
        self._root: Any = None
        self._running = False
        self._thread: threading.Thread | None = None

    def run(self) -> None:
        """Run the application, initializing the GUI event loop."""
        import tkinter as tk

        if self._running:
            logging.warning("Application is already running")
            return

        self._running = True
        logging.info("Starting Decker application")

        self._root = tk.Tk()
        self._root.title(self._initial_window_title)
        # TODO self._root.iconbitmap("src/decker/ui/assets/decker.ico")
        position_right = int(self._root.winfo_screenwidth() / 2 - self._initial_window_size[0] / 2)
        position_down = int(self._root.winfo_screenheight() / 2 - self._initial_window_size[1] / 2)

        self._root.geometry(
            f"{self._initial_window_size[0]}x{self._initial_window_size[1]}+{position_right}+{position_down}"
        )
        self._root.resizable(True, True)

        self._root.protocol("WM_DELETE_WINDOW", self.stop)

        try:
            self._root.mainloop()
        except Exception as e:
            logging.error("Application encountered an error: %s", e)
        finally:
            self._cleanup()

    def run_threaded(self) -> None:
        """Run the application in a separate thread."""
        if self._thread and self._thread.is_alive():
            logging.warning("Application thread is already running")
            return

        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        logging.info("Application started in thread")

    def stop(self) -> None:
        """Stop the application gracefully."""
        if not self._running:
            logging.warning("Application is not running")
            return

        logging.info("Stopping Decker application")
        self._running = False

        if self._root:
            self._root.quit()

    def is_running(self) -> bool:
        """Check if the application is currently running."""
        return self._running and (self._root is not None)

    def _cleanup(self) -> None:
        import tkinter as tk

        logging.info("Cleaning up application resources")
        self._running = False
        if self._root:
            try:
                self._root.destroy()
            except tk.TclError:
                pass
            self._root = None
