"""Main application entry point."""

import argparse  # Added import
import importlib.metadata
import logging

import decker_server.command.config as config_command
import decker_server.command.device as device_command
import decker_server.config
import decker_server.logging
from decker_server.server.instance_manager import InstanceManager


def create_parser() -> argparse.ArgumentParser:
    """
    Create and configure the command-line argument parser for the Decker server application.

    This function sets up the main parser with global options and configuration commands. It uses metadata
    from the package to populate program name and description.

    Returns:"run", "app.py", parse.ArgumentParser: A fully configured argument parser ready to parse command-line arguments
    """
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

    parser.add_argument(
        "-d",
        "--dev",
        action="store_true",
        help="Run the application in development mode.",
    )

    # Add subparsers for commands
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Add config command
    config_parser = subparsers.add_parser("config", help="Configuration commands")
    config_subparsers = config_parser.add_subparsers(dest="action", help="Config actions")

    # Add list action to config command
    list_parser = config_subparsers.add_parser("list", help="List application configuration")
    list_parser.add_argument("keywords", nargs="*", help="Keywords to filter configuration keys (optional)")

    # Add get action to config command
    get_parser = config_subparsers.add_parser("get", help="Get a specific configuration value")
    get_parser.add_argument("key", help="The configuration key to retrieve")

    # Add remove action to config command
    remove_parser = config_subparsers.add_parser("remove", help="Remove a specific configuration value")
    remove_parser.add_argument("key", help="The configuration key to remove")

    # Add set action to config command
    set_parser = config_subparsers.add_parser("set", help="Set a specific configuration value")
    set_parser.add_argument("key", help="The configuration key to set")
    set_parser.add_argument("value", nargs="+", help="The value to set for the configuration key")

    # Add devices command
    device_parser = subparsers.add_parser("device", help="Device management commands")
    devices_subparsers = device_parser.add_subparsers(dest="action", help="Device actions")

    # Add list action to devices command
    devices_subparsers.add_parser("list", help="List all devices")

    return parser


def handle_commands(command, args: argparse.Namespace):
    """
    Handles command execution as asked by the user.

    This function acts as a command dispatcher for configuration-related commands.
    It maps command strings to their corresponding handler functions.

    Args:
        command (str): The command to execute.
        args (argparse.Namespace): Parsed command line arguments containing the parameters
            needed for the specific command.
    """
    commands = {
        "config.list": lambda args: config_command.list_config(args.keywords),
        "config.get": lambda args: config_command.get_config(args.key),
        "config.remove": lambda args: config_command.remove_config(args.key),
        "config.set": lambda args: config_command.set_config(args.key, " ".join(args.value)),
        "device.list": lambda _: device_command.list_devices(),
    }

    if command not in commands:
        logging.error("Invalid command: %s", command)
        return

    logging.debug("Handling command: %s", command)
    commands[command](args)


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

    decker_server.logging.configure(level=level)

    logging.debug(args)

    # Handle commands
    if args.command:
        command = f"{args.command}.{args.action}"
        handle_commands(command, args)
        return

    instance_manager = InstanceManager(dev_mode=args.dev or False)
    instance_manager.start_server()
