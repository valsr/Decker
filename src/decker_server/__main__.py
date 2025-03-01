import argparse  # Added import
import importlib.metadata
import logging
import signal
import threading
import time

import decker_server.logging
from decker_server.server import Server
from decker_server.theme import primary, warning

APP_THREAD: Server | None = None


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


def create_parser() -> argparse.ArgumentParser:
    metadata = importlib.metadata.metadata("decker_server")
    parser = argparse.ArgumentParser(
        prog=metadata["Name"],
        description=metadata["Description"],
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{metadata['Name']} {metadata['Version']}",
        help="Print the version of the application and exit.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help=(
            "Increase logging verbosity. Specify once for INFO, twice for DEBUG. "
            "Defaults to WARNING if not provided."
        ),
    )
    return parser


def main() -> None:
    # Initialize argument parser to handle --help flag.
    parser = create_parser()
    args = parser.parse_args()

    if args.verbose >= 2:
        level = logging.DEBUG
    elif args.verbose == 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    decker_server.logging.configure(level=level)
    logging.info(primary("Starting server"))
    APP_THREAD = Server()
    APP_THREAD.start()
    forever = threading.Event()
    forever.wait()


signal.signal(signal.SIGINT, handle_interrupt)
if __name__ == "__main__":
    main()
