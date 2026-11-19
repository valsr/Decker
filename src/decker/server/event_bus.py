"""Thread-safe push channel broadcasting events to all connected RPyC clients."""

import logging
import threading
from collections.abc import Callable
from typing import Any

from rpyc.utils.helpers import async_


class EventBus:
    """Registers active RPyC client connections and pushes events to them asynchronously.

    Clients that raise on delivery are silently pruned from the registry.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: list[Any] = []
        self._senders: dict[Any, Callable[[str, str], Any]] = {}  # each client's resolved, non-blocking sender
        self._loopback: dict[Any, bool] = {}

    def register(self, conn: Any, *, loopback: bool) -> None:
        """Add a client connection to the push list; loopback says whether it runs on the server's machine."""
        with self._lock:
            self._clients.append(conn)
            self._loopback[conn] = loopback
        logging.debug("EventBus: client registered (%d total)", len(self._clients))

    def unregister(self, conn: Any) -> None:
        """Remove a client connection from the push list."""
        with self._lock:
            self._forget(conn)
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
                self._sender(conn)(event_type, payload)
            except Exception:  # pylint: disable=broad-except
                dead.append(conn)
        self._forget_all(dead)

    def push_filtered(self, event_type: str, make_payload: Callable[[bool], str]) -> None:
        """Push to every client the payload made for its own loopback flag."""
        with self._lock:
            clients = [(conn, self._loopback.get(conn, False)) for conn in self._clients]
        dead: list[Any] = []
        for conn, loopback in clients:
            try:
                payload = make_payload(loopback)
            except Exception:  # pylint: disable=broad-except
                logging.exception("EventBus: building the %s payload failed", event_type)
                continue
            try:
                self._sender(conn)(event_type, payload)
            except Exception:  # pylint: disable=broad-except
                dead.append(conn)
        self._forget_all(dead)

    def push_to(self, conn: Any, event_type: str, payload: str) -> None:
        """Push to one client only."""
        try:
            self._sender(conn)(event_type, payload)
        except Exception:  # pylint: disable=broad-except
            self._forget_all([conn])

    def _forget_all(self, conns: list[Any]) -> None:
        if conns:
            with self._lock:
                for conn in conns:
                    self._forget(conn)

    def _sender(self, conn: Any) -> Callable[[str, str], Any]:
        """The client's fire-and-forget ``on_server_event``; looking it up asks the client, so it is done once."""
        sender = self._senders.get(conn)
        if sender is None:
            sender = async_(conn.root.on_server_event)
            self._senders[conn] = sender
        return sender

    def _forget(self, conn: Any) -> None:
        try:
            self._clients.remove(conn)
        except ValueError:
            pass
        self._senders.pop(conn, None)
        self._loopback.pop(conn, None)
