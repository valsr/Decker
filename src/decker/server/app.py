"""Main application entry point."""

import argparse
import importlib.metadata
import logging
import os

import decker.common.logging
from decker.common.context import ServerAppContext
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
        help=("Increase logging verbosity. Specify once for INFO, twice for DEBUG. Defaults to WARNING."),
    )

    return parser


def main() -> None:
    """Application runtime entry point."""
    parser = create_parser()
    args = parser.parse_args()

    # map to context
    appContext = ServerAppContext()

    if args.verbose > 2:
        appContext.log_others = True
    if args.verbose >= 2:
        appContext.verbosity = logging.DEBUG
    elif args.verbose == 1:
        appContext.verbosity = logging.INFO

    decker.common.logging.configure(
        level=appContext.verbosity, log_directory=os.getcwd(), log_others=appContext.log_others
    )
    logging.debug("Arguments received: %s", args)

    monitor = ServerMonitor(appContext)
    try:
        monitor.start()
    except Exception as e:
        logging.error("Error occurred while starting the server monitor: %s", e)
    finally:
        monitor.stop()
