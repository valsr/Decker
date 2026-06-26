"""Thread-safe push channel broadcasting events to all connected RPyC clients."""

import logging
import threading
from typing import Any

from rpyc.utils.helpers import async_


class EventBus:
    """Registers active RPyC client connections and pushes events to them asynchronously.

    Clients that raise on delivery are silently pruned from the registry.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: list[Any] = []

    def register(self, conn: Any) -> None:
        """Add a client connection to the push list."""
        with self._lock:
            self._clients.append(conn)
        logging.debug("EventBus: client registered (%d total)", len(self._clients))

    def unregister(self, conn: Any) -> None:
        """Remove a client connection from the push list."""
        with self._lock:
            try:
                self._clients.remove(conn)
            except ValueError:
                pass
        logging.debug("EventBus: client unregistered (%d remaining)", len(self._clients))

    def push(self, event_type: str, payload: str) -> None:
        """Async-push event_type+payload to every registered client.

        Each delivery is non-blocking (fire-and-forget via rpyc.async_). Clients that raise
        on delivery are removed from the registry after the current broadcast completes.
        """
        with self._lock:
            clients = list(self._clients)
        dead: list[Any] = []
        for conn in clients:
            try:
                async_(conn.root.on_server_event)(event_type, payload)
            except Exception:  # pylint: disable=broad-except
                dead.append(conn)
        if dead:
            with self._lock:
                for conn in dead:
                    try:
                        self._clients.remove(conn)
                    except ValueError:
                        pass
