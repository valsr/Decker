"""RPyC connection wrapper for one-shot CLI use."""

# pylint: disable=duplicate-code  # intentionally similar cleanup pattern to client/app.py; no shared base warranted

import json
from typing import Any

import rpyc.utils.factory


class CliConnection:
    """One-shot RPyC connection — context-manager only, no reconnect logic."""

    _TIMEOUT: float = 3.0

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._conn: Any = None

    def __enter__(self) -> "CliConnection":
        self._conn = rpyc.utils.factory.connect(
            self._host,
            self._port,
            config={"sync_request_timeout": self._TIMEOUT},
        )
        return self

    def __exit__(self, *_: Any) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # pylint: disable=broad-except
                pass
            self._conn = None

    def request(self, rpc_name: str, *args: Any) -> Any:
        """Call a remote method by name, decoding JSON responses automatically."""
        if self._conn is None:
            raise RuntimeError("Not connected — use as a context manager")
        result = getattr(self._conn.root, rpc_name)(*args)
        if isinstance(result, str):
            try:
                return json.loads(result)
            except (json.JSONDecodeError, ValueError):
                return result
        return result

    def commands(self) -> dict[str, dict[str, str]]:
        """Fetch command metadata from the server."""
        if self._conn is None:
            raise RuntimeError("Not connected — use as a context manager")
        return json.loads(self._conn.root.commands())
