"""Main application entry point."""

import argparse
import importlib.metadata
import logging
import os

import decker.common.logging
from decker.server.monitor import ServerMonitor


def create_parser() -> argparse.ArgumentParser:
    """
    Create and configure the command-line argument parser for the Decker server application.

    Returns:
        argparse.ArgumentParser: A fully configured argument parser ready to parse command-line arguments.
    """
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
        help=(
            "Increase logging verbosity. Specify once for INFO, twice for DEBUG. "
            "Defaults to WARNING if not provided."
        ),
    )
    parser.add_argument(
        "-d",
        "--dev",
        action="store_true",
        help="Run the application in development mode.",
    )

    return parser


def main() -> None:
    """Application runtime entry point."""
    parser = create_parser()
    args = parser.parse_args()

    if args.verbose >= 2:
        level = logging.DEBUG
    elif args.verbose == 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    decker.common.logging.configure(level=level, log_directory=os.getcwd())
    logging.debug(args)

    monitor = ServerMonitor()
    try:
        monitor.start()
    except Exception as e:
        logging.error("Error occurred while starting the server monitor: %s", e)
    finally:
        monitor.stop()
