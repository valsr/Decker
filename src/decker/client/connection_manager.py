"""Owns the RPyC connection and its background worker thread. No Qt imports."""

import json
import logging
import threading
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Any

import rpyc.utils.factory
from rpyc.core.protocol import Connection
from rpyc.core.service import Service
from rpyc.utils.helpers import BgServingThread

from decker.client import config as client_config
from decker.client.events import (
    ActionListUpdatedEvent,
    DeviceListUpdatedEvent,
    KeyDisplayStatesUpdatedEvent,
    KeyEvent,
    PluginLoadFailedEvent,
    ServerConnectedEvent,
    ServerDisconnectedEvent,
)
from decker.client.events.event_manager import EventManager
from decker.common.model import DeviceHardwareInfo, KeyInfo

_RETRY_INTERVAL_S = 3.0
_HEARTBEAT_INTERVAL_S = 5.0


class ServerState(StrEnum):
    """Connection state of the client towards the server, as seen by ConnectionManager."""

    DISCONNECTED = "disconnected"  # no connection
    INITIALIZING = "initializing"  # connected, initial data not yet pulled
    UNHEALTHY = "unhealthy"  # connected, but the last heartbeat reported a non-healthy status
    HEALTHY = "healthy"  # connected and the last heartbeat reported healthy


class _ClientService(Service):
    """Exposed to the server so it can push events to this client."""

    def __init__(self, on_event: Callable[[str, str], None]) -> None:
        super().__init__()
        self._on_event = on_event

    def exposed_on_server_event(self, event_type: str, payload: str) -> None:
        """Called by the server to deliver a push event."""
        try:
            self._on_event(event_type, payload)
        except Exception as exc:  # pylint: disable=broad-except
            logging.warning("Error handling server event %s: %s", event_type, exc)


class ConnectionManager:
    """Maintains a connection to the Decker server on a background thread.

    Pushes events to EventManager as connection state changes. Owns the worker thread's full lifecycle.
    Server-initiated push events are received via _ClientService / BgServingThread.
    """

    def __init__(self) -> None:
        self._conn: Connection | None = None
        self._bg_server: BgServingThread | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.state: ServerState = ServerState.DISCONNECTED
        self._reported_plugin_failures: set[str] = set()

    @property
    def is_connected(self) -> bool:
        """True while a connection to the server is open, regardless of its health."""
        return self.state != ServerState.DISCONNECTED

    @property
    def is_ready(self) -> bool:
        """True once the initial data pull has completed on the current connection."""
        return self.state in (ServerState.HEALTHY, ServerState.UNHEALTHY)

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

    def _run(self) -> None:
        last_heartbeat = 0.0
        while not self._stop_event.is_set():
            if self._conn is None:
                self._try_connect()
                if self._conn is None:
                    self._stop_event.wait(_RETRY_INTERVAL_S)
                continue
            self._stop_event.wait(_HEARTBEAT_INTERVAL_S)
            if self._stop_event.is_set():
                break
            now = time.monotonic()
            if now - last_heartbeat >= _HEARTBEAT_INTERVAL_S:
                self._check_heartbeat()
                last_heartbeat = now

    def _try_connect(self) -> None:
        host: str = ""
        port: int = -1
        try:
            host = client_config.get_server_host()
            port = client_config.get_server_port()
            self._conn = rpyc.utils.factory.connect(
                host,
                port,
                service=_ClientService(self._on_server_event),
            )
        except Exception as e:  # pylint: disable=broad-except
            logging.warning("Could not connect to server at %s:%d — %s", host, port, e)
            return
        logging.info("Connected to server at %s:%d", host, port)
        self.state = ServerState.INITIALIZING
        self._bg_server = BgServingThread(self._conn)
        EventManager.get().push(ServerConnectedEvent(host=host, port=port))
        self._refresh_all()
        self._refresh_key_display_states()
        if self._conn is not None:
            self.state = ServerState.HEALTHY

    def _refresh_all(self) -> None:
        self._refresh_devices()
        self._refresh_actions()
        self._check_plugin_failures()

    def _call_json(self, method: str, *args: Any) -> Any:
        """Call an RPC method that returns a JSON string and decode it."""
        if self._conn is None:
            return None
        result = getattr(self._conn.root, method)(*args)
        return json.loads(result)

    def _check_heartbeat(self) -> None:
        try:
            response: dict[str, Any] = self._call_json("heartbeat")
        except Exception as e:  # pylint: disable=broad-except
            logging.warning("Server heartbeat failed: %s", e)
            self._close_connection()
            EventManager.get().push(ServerDisconnectedEvent(reason=str(e)))
            return
        if response.get("status") == "healthy":
            self.state = ServerState.HEALTHY
        else:
            logging.warning("Server reported unhealthy status: %r", response)
            self.state = ServerState.UNHEALTHY
        self._refresh_all()

    def _check_plugin_failures(self) -> None:
        if self._conn is None:
            return
        try:
            failures: list[dict[str, Any]] = self._call_json("plugins_load_failures")
        except Exception as e:  # pylint: disable=broad-except
            logging.warning("Could not fetch plugin load failures: %s", e)
            return
        for failure in failures:
            plugin_uuid = str(failure.get("plugin_uuid", ""))
            if plugin_uuid in self._reported_plugin_failures:
                continue
            self._reported_plugin_failures.add(plugin_uuid)
            EventManager.get().push(PluginLoadFailedEvent(plugin_uuid=plugin_uuid, error=str(failure.get("error", ""))))

    def _refresh_devices(self) -> None:
        if self._conn is None:
            return
        try:
            raw: list[dict[str, Any]] = self._call_json("devices_list")
        except Exception as e:  # pylint: disable=broad-except
            logging.warning("Could not list devices: %s", e)
            return
        devices = [_parse_hw_info(d) for d in raw]
        EventManager.get().push(DeviceListUpdatedEvent(devices=devices))

    def _refresh_actions(self) -> None:
        if self._conn is None:
            return
        try:
            actions: list[dict[str, Any]] = self._call_json("plugins_actions_list")
        except Exception as e:  # pylint: disable=broad-except
            logging.warning("Could not list plugin actions: %s", e)
            return
        EventManager.get().push(ActionListUpdatedEvent(actions=actions))

    def call(self, method: str, *args: Any) -> Any:
        """Call an RPC method on the server and return the result. Returns None on error."""
        if self._conn is None:
            return None
        try:
            return getattr(self._conn.root, method)(*args)
        except Exception as exc:  # pylint: disable=broad-except
            logging.warning("RPC %s failed: %s", method, exc)
            return None

    def _refresh_key_display_states(self) -> None:
        if self._conn is None:
            return
        from decker.client.context import (
            AppContext,  # pylint: disable=import-outside-toplevel
        )

        device_id = AppContext.get().active_device_id
        if device_id is None:
            return
        try:
            states: list[dict[str, Any]] = self._call_json("key_get_states", device_id)
        except Exception as exc:  # pylint: disable=broad-except
            logging.warning("Could not fetch key display states: %s", exc)
            return
        EventManager.get().push(KeyDisplayStatesUpdatedEvent(device_id=device_id, states=states))

    def _on_server_event(self, event_type: str, payload: str) -> None:
        """Dispatch a push event received from the server to the local EventManager."""
        try:
            data: dict[str, Any] = json.loads(payload)
        except (ValueError, TypeError) as exc:
            logging.warning("Malformed server event payload for %s: %s", event_type, exc)
            return

        if event_type == "key_event":
            EventManager.get().push(
                KeyEvent(
                    device_id=str(data["device_id"]),
                    key_index=int(data["key_index"]),
                    pressed=bool(data["pressed"]),
                )
            )
        elif event_type == "key_state_changed":
            device_id = str(data["device_id"])
            states: list[dict[str, Any]] = [
                {
                    "key_index": data["key_index"],
                    "image_b64": data.get("image_b64"),
                    "label": data.get("label", ""),
                }
            ]
            EventManager.get().push(KeyDisplayStatesUpdatedEvent(device_id=device_id, states=states))
        else:
            logging.debug("Unknown server event type: %s", event_type)

    def _close_connection(self) -> None:
        self.state = ServerState.DISCONNECTED
        if self._bg_server is not None:
            try:
                self._bg_server.stop()
            except Exception:  # pylint: disable=broad-except
                pass
            self._bg_server = None
        if self._conn is None:
            return
        try:
            self._conn.close()
        except Exception:  # pylint: disable=broad-except
            pass
        self._conn = None


def _parse_hw_info(data: dict[str, Any]) -> DeviceHardwareInfo:
    """Deserialise a raw device dict (from the JSON transport) into a DeviceHardwareInfo."""
    keys = [
        KeyInfo(
            row=k.get("row", 0),
            col=k.get("col", 0),
            pixel_width=k.get("pixel_width", 0),
            pixel_height=k.get("pixel_height", 0),
            type=k.get("type", "key"),
        )
        for k in data.get("keys") or []
    ]
    return DeviceHardwareInfo(
        id=data.get("id") or None,
        type=str(data.get("type", "")),
        vendor_id=int(data.get("vendor_id") or 0),
        product_id=int(data.get("product_id") or 0),
        num_keys=int(data.get("num_keys") or 0),
        keys=keys,
        serial=data.get("serial") or None,
        path=str(data.get("path") or ""),
        firmware=data.get("firmware") or None,
    )
