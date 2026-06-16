"""Applies inbound (plugin -> server) Elgato events to Decker's hardware sink and settings store."""

import base64
import logging

from decker.plugin.context import ActionTarget, HardwareSink, SettingsStore
from decker.plugin.elgato.protocol import ElgatoEvent


class ElgatoEventTranslator:
    """Routes Elgato WebSocket events to the shared HardwareSink / SettingsStore.

    target is supplied by the caller (the bridge), since the wire protocol only
    carries the action's context id, not its device/key location.
    """

    def __init__(self, sink: HardwareSink, settings_store: SettingsStore) -> None:
        self._sink = sink
        self._settings_store = settings_store
        self._handlers = {
            "setTitle": self._set_title,
            "setImage": self._set_image,
            "setState": self._set_state,
            "showAlert": self._show_alert,
            "showOk": self._show_ok,
            "setSettings": self._set_settings,
        }

    def apply(self, event: ElgatoEvent, target: ActionTarget) -> None:
        """Apply one inbound plugin event. Unknown event names are logged and ignored."""
        handler = self._handlers.get(event.event)
        if handler is None:
            logging.warning("Unhandled Elgato event from plugin %s: %s", target.plugin_uuid, event.event)
            return
        handler(event, target)

    def _set_title(self, event: ElgatoEvent, target: ActionTarget) -> None:
        self._sink.set_title(target.device_id, target.key_index, (event.payload or {}).get("title", ""))

    def _set_image(self, event: ElgatoEvent, target: ActionTarget) -> None:
        encoded = (event.payload or {}).get("image", "")
        image = base64.b64decode(encoded) if encoded else b""
        self._sink.set_image(target.device_id, target.key_index, image)

    def _set_state(self, event: ElgatoEvent, target: ActionTarget) -> None:
        self._sink.set_state(target.device_id, target.key_index, (event.payload or {}).get("state", 0))

    def _show_alert(self, _event: ElgatoEvent, target: ActionTarget) -> None:
        self._sink.show_alert(target.device_id, target.key_index)

    def _show_ok(self, _event: ElgatoEvent, target: ActionTarget) -> None:
        self._sink.show_ok(target.device_id, target.key_index)

    def _set_settings(self, event: ElgatoEvent, target: ActionTarget) -> None:
        self._settings_store.set_settings(
            target.plugin_uuid, target.action_uuid, target.context_id, event.payload or {}
        )
