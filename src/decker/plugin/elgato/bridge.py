"""WebSocket server that Elgato plugin processes register with and exchange events over."""

import asyncio
import logging
import threading

from websockets.asyncio.server import Server, ServerConnection, serve

from decker.plugin.context import ActionTarget, HardwareSink, SettingsStore
from decker.plugin.elgato.protocol import ElgatoEvent, deserialize, serialize
from decker.plugin.elgato.translator import ElgatoEventTranslator

DEFAULT_PORT = 28196


class ElgatoBridge:
    """Hosts the WebSocket server on DEFAULT_PORT; routes events to/from connected plugin processes.

    Runs its own asyncio event loop on a background thread, alongside the synchronous RPyC server.
    """

    def __init__(self, sink: HardwareSink, settings_store: SettingsStore, port: int = DEFAULT_PORT) -> None:
        self._port = port
        self._translator = ElgatoEventTranslator(sink, settings_store)
        self._connections: dict[str, ServerConnection] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server: Server | None = None

    def start(self) -> None:
        """Start the WebSocket server on a background thread."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the WebSocket server and join its thread."""
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
        if self._thread is not None:
            self._thread.join(timeout=5)

    async def _shutdown(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def send_to_plugin(self, plugin_uuid: str, event: ElgatoEvent) -> None:
        """Send an outbound (server -> plugin) event, e.g. keyDown, to a connected plugin process."""
        connection = self._connections.get(plugin_uuid)
        if connection is None:
            logging.warning("No active connection for Elgato plugin %s", plugin_uuid)
            return
        await connection.send(serialize(event))

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        finally:
            self._loop.close()

    async def _serve(self) -> None:
        async with serve(self._handle_connection, "localhost", self._port) as server:
            self._server = server
            try:
                await server.serve_forever()
            except asyncio.CancelledError:
                pass  # expected: server.close() in _shutdown() cancels serve_forever()

    async def _handle_connection(self, connection: ServerConnection) -> None:
        plugin_uuid: str | None = None
        try:
            async for raw in connection:
                try:
                    raw_text = raw if isinstance(raw, str) else raw.decode()
                    plugin_uuid = self._handle_message(connection, raw_text, plugin_uuid)
                except (ValueError, UnicodeDecodeError) as exc:
                    # One malformed message must not drop the plugin's connection.
                    logging.warning("Ignoring malformed message from Elgato plugin %s: %s", plugin_uuid, exc)
        finally:
            if plugin_uuid is not None:
                self._connections.pop(plugin_uuid, None)

    def _handle_message(self, connection: ServerConnection, raw: str, plugin_uuid: str | None) -> str | None:
        event = deserialize(raw)
        if event.event == "registerPlugin":
            registered_uuid = (event.payload or {}).get("pluginUUID")
            if registered_uuid:
                self._connections[registered_uuid] = connection
                return registered_uuid
            return plugin_uuid
        if plugin_uuid is None:
            logging.warning("Received event before plugin registration: %s", event.event)
            return plugin_uuid
        target = ActionTarget(
            plugin_uuid=plugin_uuid,
            action_uuid=event.action or "",
            context_id=event.context or "",
            device_id="",
            key_index=0,
        )
        self._translator.apply(event, target)
        return plugin_uuid
