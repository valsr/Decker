"""The server's editable settings as the client sees them. No Qt imports."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ServerSettingsInfo:
    """Result of the server's `server_settings` RPC for this client."""

    port: int
    memory_limit: int
    icon_max_file_size: int
    stop_when_last_client_leaves: bool
    reconfigurable: bool
    last_apply_error: str | None


def parse_server_settings(data: Any) -> ServerSettingsInfo | None:
    """Build a ServerSettingsInfo from the decoded RPC payload; None if it is not a well-formed dict."""
    if not isinstance(data, dict):
        return None
    try:
        error = data.get("last_apply_error")
        return ServerSettingsInfo(
            port=int(data["port"]),
            memory_limit=int(data["memory_limit"]),
            icon_max_file_size=int(data["icon_max_file_size"]),
            stop_when_last_client_leaves=bool(data["stop_when_last_client_leaves"]),
            reconfigurable=bool(data["reconfigurable"]),
            last_apply_error=str(error) if error else None,
        )
    except (KeyError, TypeError, ValueError):
        return None
