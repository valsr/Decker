"""Decker CLI client — execute server commands from the terminal."""

import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from decker.cli import plugin as plugin_cli
from decker.cli import plugin_scaffold
from decker.cli.connection import CliConnection
from decker.cli.formatter import format_result
from decker.common import config
from decker.common import paths as decker_paths


def create_parser() -> ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = ArgumentParser(prog="decker-cli", description="Decker CLI client")
    parser.add_argument("--host", default=None, help="Server host (overrides config)")
    parser.add_argument("--port", type=int, default=None, help="Server port (overrides config)")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument(
        "--prefix",
        default=None,
        metavar="DIR",
        help="Override the home directory used to locate the .decker folder (default: user home).",
    )
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

    if args.prefix is not None:
        decker_paths.configure(Path(args.prefix))

    host, port = _resolve_connection_args(args)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == ["help"]:
        parser.print_help()
        sys.exit(0)

    if args.command[0] == "plugin":
        sys.exit(_dispatch_plugin(args.command[1:], host, port))

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


_INSTALL_TIMEOUT = 120.0
_PLUGIN_USAGE = "Usage: decker-cli plugin <new|pack|install|remove|list> ..."


def _dispatch_plugin(rest: list[str], host: str, port: int) -> int:
    """Route a 'plugin' subcommand — new/pack are local; install/remove/list go to the server over RPC."""
    if not rest:
        print(_PLUGIN_USAGE)
        return 1
    sub, *sub_args = rest
    local = {"new": _cmd_plugin_new, "pack": _cmd_plugin_pack}
    remote = {"install": _cmd_plugin_install, "list": _cmd_plugin_list, "remove": _cmd_plugin_remove}
    if sub in local:
        return local[sub](sub_args)
    handler = remote.get(sub)
    if handler is None:
        print(f"Error: unknown plugin subcommand '{sub}'. Use new, pack, install, remove, or list.")
        return 1
    if sub != "list" and not sub_args:
        print(f"Usage: decker-cli plugin {sub} <{'path' if sub == 'install' else 'plugin-id'}>")
        return 1
    try:
        timeout = _INSTALL_TIMEOUT if sub == "install" else None
        with CliConnection(host, port, timeout=timeout) as conn:
            return handler(conn, sub_args)
    except ConnectionRefusedError:
        print(f"Error: cannot connect to server at {host}:{port}. Is the server running?")
        return 1


def _cmd_plugin_new(args: list[str]) -> int:
    if not args:
        print("Usage: decker-cli plugin new <plugin-id>")
        return 1
    try:
        folder = plugin_scaffold.scaffold(args[0], Path.cwd())
    except plugin_cli.PluginCliError as e:
        print(f"Error: {e}")
        return 1
    print(f"Created plugin template in {folder}")
    return 0


def _cmd_plugin_pack(args: list[str]) -> int:
    if not args:
        print("Usage: decker-cli plugin pack <folder> [out-dir]")
        return 1
    try:
        out = plugin_scaffold.pack(Path(args[0]), Path(args[1]) if len(args) > 1 else None)
    except plugin_cli.PluginCliError as e:
        print(f"Error: {e}")
        return 1
    print(f"Wrote {out}")
    return 0


def _cmd_plugin_install(conn: CliConnection, args: list[str]) -> int:
    try:
        job_id = plugin_cli.install(conn, Path(args[0]))
    except plugin_cli.PluginCliError as e:
        print(f"Error: {e}")
        return 1
    except Exception as e:  # pylint: disable=broad-except
        print(f"Error: install failed: {e}")
        return 2
    print(f"Install started (job {job_id}); progress appears in the client and the server log")
    return 0


def _cmd_plugin_list(conn: CliConnection, _args: list[str]) -> int:
    plugins = plugin_cli.list_plugins(conn)
    if not plugins:
        print("No plugins installed.")
        return 0
    width = max(len(p["id"]) for p in plugins)
    for p in plugins:
        suffix = " (bundled)" if p.get("bundled") else ""
        print(f"  {p['id']:<{width}}  {p.get('version', ''):<10}  {p.get('name', '')}{suffix}")
    return 0


def _cmd_plugin_remove(conn: CliConnection, args: list[str]) -> int:
    try:
        plugin_cli.remove(conn, args[0])
    except plugin_cli.PluginCliError as e:
        print(f"Error: {e}")
        return 1
    except Exception as e:  # pylint: disable=broad-except
        print(f"Error: remove failed: {e}")
        return 2
    print(f"Removed plugin {args[0]}.")
    return 0
