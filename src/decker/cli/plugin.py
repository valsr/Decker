"""Plugin install / remove / list over the server's RPCs (the server owns ~/.decker/plugins/)."""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from decker.cli.connection import CliConnection

INSTALL_WAIT_SECONDS = 900.0
_POLL_SECONDS = 0.5
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


def wait_for_install(
    conn: CliConnection,
    job_id: str,
    report: Callable[[str], None],
    timeout: float = INSTALL_WAIT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Poll an install job until it succeeds or fails, reporting each new progress message."""
    deadline = time.monotonic() + timeout
    last = ""
    while True:
        status = conn.request("plugin_install_status", job_id)
        if not isinstance(status, dict):
            return {"state": "failed", "message": "the server returned an unexpected install status"}
        message = str(status.get("message", ""))
        if message and message != last:
            last = message
            report(message)
        if status.get("state") in ("succeeded", "failed", "unknown"):
            return status
        if time.monotonic() >= deadline:
            return {"state": "failed", "message": f"timed out waiting for the install after {timeout:g}s"}
        sleep(_POLL_SECONDS)
