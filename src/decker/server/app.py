"""Main application entry point."""

import argparse
import importlib.metadata
import logging
import os
from pathlib import Path

import decker.common.logging
from decker.common import paths as decker_paths
from decker.common.context import ServerAppContext
from decker.server.monitor import ServerMonitor


def create_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser for the Decker server application."""
    metadata = importlib.metadata.metadata("decker")
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
        help="Increase logging verbosity. Specify once for INFO, twice for DEBUG. Defaults to WARNING.",
    )
    parser.add_argument(
        "--prefix",
        default=None,
        metavar="DIR",
        help="Override the home directory used to locate the .decker folder (default: user home).",
    )
    parser.add_argument(
        "--device",
        default=None,
        metavar="ID_OR_PATH",
        help="Device ID or USB path to use. Server fails to start if the device is not found.",
    )
    parser.add_argument(
        "--reset-device-data",
        action="store_true",
        default=False,
        help="Clear persisted key images and labels before starting (for the target device if --device is set).",
    )

    return parser


def main() -> None:
    """Application runtime entry point."""
    parser = create_parser()
    args = parser.parse_args()

    app_context = ServerAppContext()

    if args.prefix is not None:
        app_context.prefix = Path(args.prefix)
        decker_paths.configure(app_context.prefix)

    if args.verbose > 2:
        app_context.log_others = True
    if args.verbose >= 2:
        app_context.verbosity = logging.DEBUG
    elif args.verbose == 1:
        app_context.verbosity = logging.INFO

    app_context.target_device = args.device
    app_context.reset_device_data = args.reset_device_data

    decker.common.logging.configure(
        level=app_context.verbosity, log_directory=os.getcwd(), log_others=app_context.log_others
    )
    logging.debug("Arguments received: %s", args)

    monitor = ServerMonitor(app_context)
    try:
        monitor.start()
    except Exception as e:
        logging.error("Error occurred while starting the server monitor: %s", e)
    finally:
        monitor.stop()
