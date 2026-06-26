"""Decker client entry point — startup sequencing for the connection manager and main window."""

import argparse
import logging
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

import decker.common.logging
from decker.client.connection_manager import ConnectionManager
from decker.client.tray import TrayIcon
from decker.client.window import MainWindow
from decker.common import config
from decker.common import paths as decker_paths


def _create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="decker-client", description="Decker GUI client")
    parser.add_argument(
        "--prefix",
        default=None,
        metavar="DIR",
        help="Override the home directory used to locate the .decker folder (default: user home).",
    )
    return parser


def main() -> None:
    """Client entry point."""
    args = _create_parser().parse_args()

    if args.prefix is not None:
        decker_paths.configure(Path(args.prefix))

    decker.common.logging.configure(level=logging.WARNING)
    app = QApplication(sys.argv)

    host: str = config.get_as("client.server_host", str)
    port: int = config.get_as("client.server_port", int)

    connection_manager = ConnectionManager(host, port)
    connection_manager.start()

    window = MainWindow(connection_manager)
    window.check_initial_view()

    tray_icon = TrayIcon(window)
    tray_icon.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
