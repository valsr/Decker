"""Main application entry point."""

import argparse  # Added import
import importlib.metadata
import logging
import os
import tkinter.ttk as ttk

from decker.Application import Application
import decker.command.config as config_command
import decker.command.device as device_command
import decker.config
import decker.logging


def create_parser() -> argparse.ArgumentParser:
    """
    Create and configure the command-line argument parser for the Decker server application.

    This function sets up the main parser with global options and configuration commands. It uses metadata
    from the package to populate program name and description.

    Returns:
        parse.ArgumentParser: A fully configured argument parser ready to parse command-line arguments
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

    log_directory = decker.config.get("logging.directory") or os.getcwd()
    decker.logging.configure(level=level, log_directory=str(log_directory))
    logging.debug("Logging directory: %s", log_directory)
    logging.debug(args)

    # Start the application
    app = Application()
    app.run()
