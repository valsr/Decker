import importlib.metadata
import logging
import threading
import tkinter as tk


class Application:
    """
    Main application class for the Decker application.

    This class serves as the entry point for the application, handling command-line arguments,
    logging configuration, and starting the GUI.
    """
    def __init__(self):
        self._initial_window_size = (1200, 800)  # Default window size
        self._initial_window_title = importlib.metadata.metadata("decker")["Name"]
        self._window_stack = []
        self._root: tk.Tk | None = None
        self._running = False
        self._thread: threading.Thread | None = None

    def run(self):
        """
        Run the application.

        This method initializes the application, sets up logging, and starts the GUI event loop.
        """
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
            "{}x{}+{}+{}".format(
                self._initial_window_size[0],
                self._initial_window_size[1],
                position_right,
                position_down,
            )
        )
        self._root.resizable(True, True)

        # Set up close handler
        self._root.protocol("WM_DELETE_WINDOW", self.stop)

        try:
            # Start the GUI event loop
            self._root.mainloop()
        except Exception as e:
            logging.error("Application encountered an error: %s", e)
        finally:
            self._cleanup()

    def run_threaded(self):
        """
        Run the application in a separate thread.

        This is useful when the application needs to be controlled by a daemon.
        """
        if self._thread and self._thread.is_alive():
            logging.warning("Application thread is already running")
            return

        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        logging.info("Application started in thread")

    def stop(self):
        """
        Stop the application gracefully.
        """
        if not self._running:
            logging.warning("Application is not running")
            return

        logging.info("Stopping Decker application")
        self._running = False

        if self._root:
            # Schedule the GUI to close on the main thread
            self._root.quit()

    def is_running(self) -> bool:
        """
        Check if the application is currently running.

        Returns:
            bool: True if the application is running, False otherwise.
        """
        return self._running and (self._root is not None)

    def _cleanup(self):
        """Perform cleanup when the application stops."""
        logging.info("Cleaning up application resources")
        self._running = False
        if self._root:
            try:
                self._root.destroy()
            except tk.TclError:
                # Window was already destroyed
                pass
            self._root = None
