"""Script that starts Decker server instance."""

import argparse
import logging
import os

import decker_server.config
import decker_server.logging


def create_parser():
    parser = argparse.ArgumentParser(description="Decker server")
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
        "device",
        type=str,
        help="Device ID to start server for",
    )

    return parser


def _get_config_log_level(device_id: str, verbose_level: int) -> int:
    level: int | None = None

    if decker_server.config.has(f"server.{device_id}.logging.level"):
        config_level = decker_server.config.get(f"server.{device_id}.logging.level")
        if config_level and isinstance(config_level, (str, int)):
            if isinstance(config_level, str):
                mapping = logging.getLevelNamesMapping()
                level = mapping.get(config_level.upper(), None)
            else:
                level = config_level

    if level is None:
        if verbose_level == 1:
            level = logging.INFO
        elif verbose_level >= 2:
            level = logging.DEBUG

    if level is None:
        level = logging.WARNING

    return level


def configure_logging(device: str, verbose_level: int):
    level = _get_config_log_level(device, verbose_level)
    directory = str(decker_server.config.get("logging.directory") or os.getcwd())
    decker_server.logging.configure(level=level, log_directory=directory, server_id=device)
    logging.debug("Configured logging with level %s and directory %s", logging.getLevelName(level), directory)


def run():
    from time import sleep

    parser = create_parser()
    args = parser.parse_args()

    configure_logging(args.device, args.verbose)

    logging.debug("Starting server")
    sleep(120)
    logging.debug("Stopping server")


if __name__ == "__main__":
    run()
