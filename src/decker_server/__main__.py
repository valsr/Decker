import argparse  # Added import
import importlib.metadata
import logging
import signal
import threading
import time

import decker_server.command.config as config_command
import decker_server.config
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
    set_parser.add_argument("value", nargs='+', help="The value to set for the configuration key")

    return parser


def handle_commands(command, args: argparse.Namespace) -> None:
    commands = {
        "config.list": lambda args: config_command.list_config(args.keywords),
        "config.get": lambda args: config_command.get_config(args.key),
        "config.remove": lambda args: config_command.remove_config(args.key),
        "config.set": lambda args: config_command.set_config(args.key, " ".join(args.value)),
    }

    if command not in commands:
        logging.error("Invalid command: %s", command)
        return

    logging.debug("Handling command: %s", command)
    commands[command](args)


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

    # Handle commands
    if hasattr(args, "command"):
        command = f"{args.command}.{args.action}"
        handle_commands(command, args)
        return

    logging.info(primary("Starting server"))
    global APP_THREAD
    APP_THREAD = Server()
    APP_THREAD.start()
    forever = threading.Event()
    forever.wait()


signal.signal(signal.SIGINT, handle_interrupt)
if __name__ == "__main__":
    main()
