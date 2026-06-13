"""Decker CLI client — execute server commands from the terminal."""

import sys
from argparse import ArgumentParser
from typing import Any

from decker.cli.connection import CliConnection
from decker.cli.formatter import format_result
from decker.common import config


def create_parser() -> ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = ArgumentParser(prog="decker-cli", description="Decker CLI client")
    parser.add_argument("--host", default=None, help="Server host (overrides config)")
    parser.add_argument("--port", type=int, default=None, help="Server port (overrides config)")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("command", nargs="*", help="Command path (e.g. status, start, help status)")
    try:
        import argcomplete  # pylint: disable=import-outside-toplevel

        argcomplete.autocomplete(parser)
    except ImportError:
        pass
    return parser


def main() -> None:
    """CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()
    host, port = _resolve_connection_args(args)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == ["help"]:
        parser.print_help()
        sys.exit(0)

    try:
        with CliConnection(host, port) as conn:
            sys.exit(_dispatch(conn, args.command, parser))
    except ConnectionRefusedError:
        print(f"Error: cannot connect to server at {host}:{port}. Is the server running?")
        sys.exit(1)


def _resolve_connection_args(args: Any) -> tuple[str, int]:
    host = args.host or config.get_as("client.server_host", str)
    port = args.port or config.get_as("client.server_port", int)
    return host, port


def _dispatch(conn: CliConnection, command_parts: list[str], parser: ArgumentParser) -> int:
    """Route a parsed command to the appropriate handler."""
    cmd = command_parts[0]
    rest = command_parts[1:]

    if cmd == "list":
        return _cmd_list(conn)
    if cmd == "help":
        return _cmd_help(conn, rest[0] if rest else None, parser)

    cmd_path = ".".join(command_parts)
    rpc_name = cmd_path.replace(".", "_")
    try:
        result = conn.request(rpc_name)
        print(format_result(result))
        return 0
    except AttributeError:
        print(f"Error: unknown command '{cmd_path}'. Run 'decker-cli list' for available commands.")
        return 1
    except Exception as e:  # pylint: disable=broad-except
        print(f"Error: command '{cmd_path}' failed: {e}")
        return 2


def _cmd_list(conn: CliConnection) -> int:
    """Print all server commands sorted alphabetically."""
    cmds = conn.commands()
    if not cmds:
        print("No commands available.")
        return 0
    width = max(len(k) for k in cmds)
    for name in sorted(cmds):
        desc = cmds[name].get("description", "")
        print(f"  {name:<{width}}  {desc}")
    return 0


def _cmd_help(conn: CliConnection | None, cmd_name: str | None, parser: ArgumentParser) -> int:
    """Print general help or detailed help for a specific command."""
    if cmd_name is None:
        parser.print_help()
        return 0

    if conn is None:
        print(f"Error: cannot show help for '{cmd_name}' — no server connection.")
        return 1

    cmds = conn.commands()
    if cmd_name not in cmds:
        print(f"Error: unknown command '{cmd_name}'. Run 'decker-cli list' for available commands.")
        return 1

    info = cmds[cmd_name]
    desc = info.get("description", "(none)")
    params = info.get("params", "") or "(none)"
    ret = info.get("return_type", "unknown")
    print(f"Command: {cmd_name}")
    print(f"  Description: {desc}")
    print(f"  Parameters:  {params}")
    print(f"  Returns:     {ret}")
    return 0
