"""Owns the RPyC connection and its background worker thread. No Qt imports."""

import logging
import threading
from typing import Any

import rpyc.utils.factory
from rpyc.core.protocol import Connection

from decker.client.event_hub import EventHub
from decker.client.events import (
    ActionListUpdatedEvent,
    DeviceListUpdatedEvent,
    PluginLoadFailedEvent,
    ServerConnectedEvent,
    ServerDisconnectedEvent,
)

_RETRY_INTERVAL_S = 5.0
_HEARTBEAT_INTERVAL_S = 5.0


class ConnectionManager:
    """Maintains a connection to the Decker server on a background thread.

    Pushes ServerConnectedEvent / ServerDisconnectedEvent / DeviceListUpdatedEvent to
    EventHub as connection state changes. Owns the worker thread's full lifecycle.
    """

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._conn: Connection | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.connected: bool = False
        self._reported_plugin_failures: set[str] = set()

    def start(self) -> None:
        """Start the background connection thread. No-op if already running."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the worker thread to stop and close the connection."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=_HEARTBEAT_INTERVAL_S)
            self._thread = None
        self._close_connection()
        self.connected = False

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self._conn is None:
                self._try_connect()
                if self._conn is None:
                    self._stop_event.wait(_RETRY_INTERVAL_S)
                continue
            self._stop_event.wait(_HEARTBEAT_INTERVAL_S)
            if self._stop_event.is_set():
                break
            self._check_heartbeat()

    def _try_connect(self) -> None:
        try:
            self._conn = rpyc.utils.factory.connect(self._host, self._port)
        except Exception as e:  # pylint: disable=broad-except
            logging.warning("Could not connect to server at %s:%d — %s", self._host, self._port, e)
            return
        logging.info("Connected to server at %s:%d", self._host, self._port)
        self.connected = True
        EventHub.get().push(ServerConnectedEvent(host=self._host, port=self._port))
        self._refresh_devices()
        self._refresh_actions()
        self._check_plugin_failures()

    def _check_heartbeat(self) -> None:
        try:
            response = self._conn.root.heartbeat()  # type: ignore[union-attr]
            if response.get("status") != "healthy":
                raise ValueError(f"unexpected response: {response!r}")
        except Exception as e:  # pylint: disable=broad-except
            logging.warning("Server heartbeat failed: %s", e)
            self._close_connection()
            self.connected = False
            EventHub.get().push(ServerDisconnectedEvent(reason=str(e)))
            return
        self._refresh_devices()
        self._refresh_actions()
        self._check_plugin_failures()

    def _check_plugin_failures(self) -> None:
        if self._conn is None:
            return
        try:
            failures: list[dict[str, Any]] = [dict(f) for f in self._conn.root.plugins_load_failures()]
        except Exception as e:  # pylint: disable=broad-except
            logging.warning("Could not fetch plugin load failures: %s", e)
            return
        for failure in failures:
            plugin_uuid = str(failure.get("plugin_uuid", ""))
            if plugin_uuid in self._reported_plugin_failures:
                continue
            self._reported_plugin_failures.add(plugin_uuid)
            EventHub.get().push(PluginLoadFailedEvent(plugin_uuid=plugin_uuid, error=str(failure.get("error", ""))))

    def _refresh_devices(self) -> None:
        if self._conn is None:
            return
        try:
            devices: list[dict[str, Any]] = [dict(d) for d in self._conn.root.devices_list()]
        except Exception as e:  # pylint: disable=broad-except
            logging.warning("Could not list devices: %s", e)
            return
        EventHub.get().push(DeviceListUpdatedEvent(devices=devices))

    def _refresh_actions(self) -> None:
        if self._conn is None:
            return
        try:
            actions: list[dict[str, Any]] = [dict(a) for a in self._conn.root.plugins_actions_list()]
        except Exception as e:  # pylint: disable=broad-except
            logging.warning("Could not list plugin actions: %s", e)
            return
        EventHub.get().push(ActionListUpdatedEvent(actions=actions))

    def _close_connection(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.close()
        except Exception:  # pylint: disable=broad-except
            pass
        self._conn = None
