import logging
import threading
import signal
import time

from decker_server.ServerThread import SeverThread
from decker_server.theme import primary, warning
import decker_server.logging

APP_THREAD: threading.Thread|None = None

def handle_interrupt(signal, frame):
    if APP_THREAD is not None:
        APP_THREAD.stop()
        APP_THREAD.join(timeout=5)
        if APP_THREAD.is_alive():
            print(warning("Forcing thread termination"))
            APP_THREAD._stop()
    time.sleep(1)
    logging.info(primary("Exiting"))
    exit(0)

def main() -> None:
    logging.info(primary("Starting server"))
    decker_server.logging.configure()
    APP_THREAD = SeverThread()
    APP_THREAD.start()
    forever = threading.Event()
    forever.wait()

signal.signal(signal.SIGINT, handle_interrupt)
if __name__ == "__main__":
    main()
