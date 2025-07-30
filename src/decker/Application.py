import importlib.metadata
import tkinter as tk


class Application:
    """
    Main application class for the Decker application.

    This class serves as the entry point for the application, handling command-line arguments,
    logging configuration, and starting the GUI.
    """
    def __init__(self):
        self._initial_window_size = (1200, 800)  # Default window size
        self._initail_window_title = importlib.metadata.metadata("decker")["Name"]
        self._window_stack = []

    def run(self):
        """
        Run the application.

        This method initializes the application, sets up logging, and starts the GUI event loop.
        """
        root = tk.Tk()
        root.title(self._initail_window_title)
        # TODO root.iconbitmap("src/decker/ui/assets/decker.ico")
        position_right = int(root.winfo_screenwidth() / 2 - self._initial_window_size[0] / 2)
        position_down = int(root.winfo_screenheight() / 2 - self._initial_window_size[1] / 2)

        root.geometry(
            "{}x{}+{}+{}".format(
                self._initial_window_size[0],
                self._initial_window_size[1],
                position_right,
                position_down,
            )
        )
        root.resizable(True, True)

        # activate the main window


        # Start the GUI event loop
        root.mainloop()
