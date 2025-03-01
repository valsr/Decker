import threading
import time


class SeverThread(threading.Thread):
    """Main server thread."""

    def __init__(self) -> None:
        """Initializes PingThread.

        Args:
            stop_event (threading.Event): Event used to signal thread termination.

        See:
            - threading.Event
        """
        super().__init__()
        self.stop_event = threading.Event()
        self.daemon = True

    def stop(self) -> None:
        """Stops the thread.

        See:
            - threading.Event.set
        """
        self.stop_event.set()

    def run(self) -> None:
        """Pings every second until the stop event is active.

        See:
            - time.sleep
        """
        while not self.stop_event.is_set():
            print("ping")
            time.sleep(1)
        print("Stopping server.")
