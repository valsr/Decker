"""Plugin install / remove / list over the server's RPCs (the server owns ~/.decker/plugins/)."""

from pathlib import Path
from typing import Any

from decker.cli.connection import CliConnection

DENIED_MESSAGE = "Installing plugins is only allowed from the server's own machine"


class PluginCliError(Exception):
    """A plugin CLI operation failed."""


def install(conn: CliConnection, path: Path) -> str:
    """Send a .deckerplugin file to the server; returns the install job id."""
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise PluginCliError(f"cannot read {path}: {exc}") from exc
    try:
        return str(conn.request("plugin_install", Path(path).name, data))
    except PermissionError as exc:
        raise PluginCliError(DENIED_MESSAGE) from exc


def remove(conn: CliConnection, plugin_id: str) -> None:
    """Uninstall a plugin on the server."""
    try:
        conn.request("plugin_uninstall", plugin_id)
    except PermissionError as exc:
        raise PluginCliError(DENIED_MESSAGE.replace("Installing", "Removing")) from exc


def list_plugins(conn: CliConnection) -> list[dict[str, Any]]:
    """Return the server's installed plugins."""
    result = conn.request("plugins_list")
    return result if isinstance(result, list) else []
