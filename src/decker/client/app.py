"""Decker client entry point — startup sequencing for the connection manager and main window."""

import logging
import sys

from PyQt6.QtWidgets import QApplication

import decker.common.logging
from decker.client.connection_manager import ConnectionManager
from decker.client.window import MainWindow
from decker.common import config


def main() -> None:
    """Client entry point."""
    decker.common.logging.configure(level=logging.WARNING)
    app = QApplication(sys.argv)

    host: str = config.get_as("client.server_host", str)
    port: int = config.get_as("client.server_port", int)

    connection_manager = ConnectionManager(host, port)
    connection_manager.start()

    window = MainWindow(connection_manager)
    window.check_initial_view()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
