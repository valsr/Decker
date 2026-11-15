"""Owns plugin discovery and runs plugin processes through the supervisor."""

import base64
import binascii
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from decker.asset.renderer import AssetRenderer
from decker.common import config
from decker.common.manager import Manager
from decker.plugin.events import PluginLoadFailedEvent
from decker.plugin.gestures import Gesture, GestureRecognizer
from decker.plugin.icons import read_icon
from decker.plugin.loader import InstalledPlugin, PluginLoader
from decker.plugin.manifest import ActionSpec
from decker.plugin.protocol import Message
from decker.plugin.runtime.launcher import launch_command, launch_env
from decker.plugin.runtime.process import PluginProcess
from decker.plugin.runtime.supervisor import PluginSupervisor, SupervisorPolicy
from decker.plugin.settings_schema import apply_schema, schema_to_json
from decker.plugin.settings_store import PluginSettingsStore
from decker.plugin.target import ActionTarget

if TYPE_CHECKING:
    from decker.server.server_context import ServerContext

_BUNDLED_PLUGINS_DIR = Path(__file__).parent.parent / "bundled_plugins"
_DEFAULT_MEMORY_LIMIT = 256 * 1024 * 1024
_FAILED_LABEL = "Plugin failed"
_OPEN_URL_SCHEMES = ("http", "https")


_StateChangedCallback = Callable[[str, int], None]


class _StreamDeckHardwareSink:
    """Applies hardware effects via DeviceManager; falls back gracefully if no device is open.

    set_title is deliberately lightweight — it stores the label in the shared label dict
    for client polling instead of rendering text to hardware (the plugin renders its own
    image via set_image).
    """

    def __init__(
        self,
        device_manager: Any,  # DeviceManager | None — avoid circular import at module level
        label_setter: Callable[[str, int, str], None],
        on_state_changed: _StateChangedCallback | None = None,
    ) -> None:
        self._device_manager = device_manager
        self._label_setter = label_setter
        self._on_state_changed = on_state_changed
        self._renderer = AssetRenderer()

    def set_image(self, device_id: str, key_index: int, image: bytes) -> None:
        """Render image (SVG/PNG/JPEG bytes) on the given device's key."""
        if self._device_manager is not None:
            self._device_manager.set_image_bytes(device_id, key_index, image)
        else:
            logging.debug("set_image: no DeviceManager available")
        if self._on_state_changed is not None:
            self._on_state_changed(device_id, key_index)

    def set_title(self, device_id: str, key_index: int, title: str) -> None:
        """Store the display label for client polling (hardware text not rendered)."""
        self._label_setter(device_id, key_index, title)
        if self._on_state_changed is not None:
            self._on_state_changed(device_id, key_index)

    def clear_image(self, device_id: str, key_index: int) -> None:
        """Blank the key and drop its stored image."""
        if self._device_manager is not None:
            device = self._device_manager.open_device(device_id)
            if device is not None:
                device.clear_key_image(key_index)
            self._device_manager.clear_key_state(device_id, key_index)
        if self._on_state_changed is not None:
            self._on_state_changed(device_id, key_index)

    def set_state(self, device_id: str, key_index: int, state: int) -> None:
        """No-op: multi-state icon rendering is not implemented yet."""
        logging.debug("set_state(%s, %d, %d): not implemented", device_id, key_index, state)

    def show_alert(self, device_id: str, key_index: int) -> None:
        """No-op: indicator rendering is not implemented yet."""
        logging.debug("show_alert(%s, %d): not implemented", device_id, key_index)

    def show_ok(self, device_id: str, key_index: int) -> None:
        """No-op: indicator rendering is not implemented yet."""
        logging.debug("show_ok(%s, %d): not implemented", device_id, key_index)


@dataclass
class _Live:
    """One active action instance: where it is, what it declared and how its gestures are recognised."""

    target: ActionTarget
    action: ActionSpec
    recognizer: GestureRecognizer
    gestures: frozenset[Gesture]
    settings: dict[str, Any]


def _gestures_from(names: Any) -> frozenset[Gesture]:
    if not isinstance(names, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(Gesture(n) for n in names if n in {g.value for g in Gesture})


def _decker_version() -> str:
    try:
        return metadata.version("decker")
    except metadata.PackageNotFoundError:
        return "0"


class PluginManager(Manager):  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """Owned by the server: discovers plugins, runs them out of process and routes events both ways."""

    def __init__(
        self,
        plugins_dir: Path | None = None,
        policy: SupervisorPolicy | None = None,
        settings_store: PluginSettingsStore | None = None,
    ) -> None:
        self._settings_store = settings_store if settings_store is not None else PluginSettingsStore()
        self._user_loader = PluginLoader(plugins_dir) if plugins_dir is not None else PluginLoader()
        self._bundled_loader = PluginLoader(_BUNDLED_PLUGINS_DIR, bundled=True)
        self._failures: list[PluginLoadFailedEvent] = []
        self._plugins: dict[str, InstalledPlugin] = {}
        self._live: dict[str, _Live] = {}
        self._lock = threading.RLock()
        self._device_manager: Any = None
        self._event_bus: Any = None
        self._icon_cache: dict[tuple[Path, str | None], str] = {}
        self._sink: _StreamDeckHardwareSink = _StreamDeckHardwareSink(None, self._set_key_label)
        self.settings_persister: Callable[[ActionTarget, dict[str, Any]], None] | None = None
        if policy is None:
            limit = int(config.get_or_default("plugin.memory_limit", _DEFAULT_MEMORY_LIMIT))
            policy = SupervisorPolicy(memory_limit=limit)
        self._supervisor = PluginSupervisor(policy, PluginProcess, self._on_plugin_message, self._on_plugin_failed)

    def create(self, context: "ServerContext") -> None:
        """Wire up the device manager, then scan plugins and start the supervisor."""
        self._device_manager = context.device_manager
        self._event_bus = context.event_bus
        self._sink = _StreamDeckHardwareSink(
            self._device_manager,
            self._set_key_label,
            on_state_changed=self._make_state_changed_cb(context),
        )
        self.settings_persister = self._make_settings_persister(context)
        bundled = self._bundled_loader.scan()
        user = self._user_loader.scan()
        with self._lock:
            self._failures = bundled.failures + user.failures
        for plugin in bundled.plugins + user.plugins:
            with self._lock:
                duplicate = plugin.manifest.id in self._plugins
                if duplicate:
                    self._failures.append(PluginLoadFailedEvent(plugin.manifest.id, "duplicate plugin id"))
            if not duplicate:
                self.add_plugin(plugin)
        self._supervisor.start()
        logging.info(
            "PluginManager started: %d loaded, %d failed to load", len(self.plugins()), len(self.load_failures())
        )

    def destroy(self) -> None:
        """Stop every plugin process and release resources."""
        with self._lock:
            live = list(self._live.values())
            self._live.clear()
        for item in live:
            item.recognizer.cancel()
        self._supervisor.stop_all()
        self._settings_store.close()

    def add_plugin(self, plugin: InstalledPlugin) -> None:
        """Make a plugin's actions available; its process starts when the first action appears."""
        manifest = plugin.manifest
        with self._lock:
            self._plugins[manifest.id] = plugin
        if manifest.runtime is None or not manifest.actions:
            return
        try:
            command = launch_command(plugin.plugin_dir, manifest.runtime, plugin.bundled)
        except ValueError as exc:
            with self._lock:
                self._failures.append(PluginLoadFailedEvent(manifest.id, str(exc)))
            return
        hello = {
            "protocol": 1,
            "decker_version": _decker_version(),
            "plugin_id": manifest.id,
            "global_settings": {},
        }
        self._supervisor.register(manifest.id, command, plugin.plugin_dir, launch_env(None), hello)

    def remove_plugin(self, plugin_id: str) -> None:
        """Stop a plugin, drop its live instances and forget it."""
        with self._lock:
            dropped = [c for c, live in self._live.items() if live.target.plugin_uuid == plugin_id]
            recognizers = [self._live.pop(c).recognizer for c in dropped]
        for recognizer in recognizers:
            recognizer.cancel()
        self._supervisor.unregister(plugin_id)
        with self._lock:
            self._plugins.pop(plugin_id, None)
            self._drop_failure(plugin_id)

    def plugins(self) -> list[InstalledPlugin]:
        """Return every known plugin."""
        with self._lock:
            return list(self._plugins.values())

    def live_targets(self, plugin_id: str) -> list[ActionTarget]:
        """Return the action instances currently active for a plugin."""
        with self._lock:
            return [live.target for live in self._live.values() if live.target.plugin_uuid == plugin_id]

    def load_failures(self) -> list[PluginLoadFailedEvent]:
        """Return the plugins that failed to load or run."""
        with self._lock:
            return list(self._failures)

    def list_actions(self) -> list[dict[str, Any]]:
        """Return every action declared across all plugin manifests.

        Each entry carries icon_b64 (the action's icon, base64-encoded, or "" if none), its tooltip and
        its settings schema in the manifest JSON shape.
        """
        actions: list[dict[str, Any]] = []
        for plugin in self.plugins():
            manifest = plugin.manifest
            actions.extend(
                {
                    "plugin_uuid": manifest.id,
                    "plugin_name": manifest.name,
                    "action_uuid": spec.id,
                    "action_name": spec.name,
                    "icon_b64": self._icon_b64(plugin.plugin_dir, spec.icon or manifest.icon),
                    "tooltip": spec.tooltip,
                    "settings_schema": schema_to_json(spec.settings),
                }
                for spec in manifest.actions
            )
        return actions

    def get_key_display_states(self, device_id: str) -> list[dict[str, Any]]:
        """Return current display labels for all keys on this device."""
        state = self._device_manager.get_device_state(device_id) if self._device_manager is not None else None
        if state is None:
            return []
        return [{"key_index": k, "label": v} for k, v in state.get_all_labels()]

    def store_settings(self, target: ActionTarget, settings: dict[str, Any]) -> None:
        """Persist settings for an action instance so its plugin receives them on activation."""
        self._settings_store.set_settings(target.plugin_uuid, target.action_uuid, target.context_id, settings)

    def complete_settings(self, target: ActionTarget, settings: dict[str, Any]) -> dict[str, Any]:
        """Return settings validated against the action's schema with defaults filled in."""
        spec = self._action_spec(target.plugin_uuid, target.action_uuid)
        return apply_schema(spec.settings, settings) if spec is not None else dict(settings)

    def activate_action(self, target: ActionTarget) -> None:
        """Tell the action's plugin that an instance appeared, starting the plugin if needed."""
        spec = self._action_spec(target.plugin_uuid, target.action_uuid)
        with self._lock:
            plugin = self._plugins.get(target.plugin_uuid)
        if spec is None or plugin is None or plugin.manifest.runtime is None:
            logging.warning("Cannot activate unknown action %s/%s", target.plugin_uuid, target.action_uuid)
            return
        with self._lock:
            previous = self._live.get(target.context_id)
        if previous is not None:
            self.deactivate_action(previous.target)
        stored = self._settings_store.get_settings(target.plugin_uuid, target.action_uuid, target.context_id)
        live = _Live(
            target=target,
            action=spec,
            recognizer=GestureRecognizer(self._gesture_emitter(target.context_id)),
            gestures=_gestures_from(sorted(spec.gestures)),
            settings=apply_schema(spec.settings, stored),
        )
        with self._lock:
            self._live[target.context_id] = live
        self._supervisor.acquire(target.plugin_uuid)
        if self._supervisor.is_failed(target.plugin_uuid):
            self._mark_failed(live)
        elif self._supervisor.is_ready(target.plugin_uuid):
            self._send_will_appear(live)

    def deactivate_action(self, target: ActionTarget) -> None:
        """Tell the plugin the instance is gone and release its process."""
        with self._lock:
            live = self._live.pop(target.context_id, None)
        if live is None:
            return
        live.recognizer.cancel()
        plugin_id = target.plugin_uuid
        if self._supervisor.is_ready(plugin_id):
            self._supervisor.send(plugin_id, Message("will_disappear", target.context_id))
        self._supervisor.release(plugin_id)

    def dispatch_key_down(self, target: ActionTarget) -> None:
        """Forward the raw key down, then feed the press to the instance's gesture recognizer."""
        live = self._live.get(target.context_id)
        if live is None:
            return
        self._send_context(live, "key_down")
        live.recognizer.key_down(live.gestures)

    def dispatch_key_up(self, target: ActionTarget) -> None:
        """Forward the raw key up, then feed the release to the instance's gesture recognizer."""
        live = self._live.get(target.context_id)
        if live is None:
            return
        self._send_context(live, "key_up")
        live.recognizer.key_up()

    def dispatch_settings_changed(self, target: ActionTarget) -> None:
        """Send the instance its new settings; re-saving settings retries a failed plugin."""
        plugin_id = target.plugin_uuid
        if self._supervisor.is_failed(plugin_id):
            with self._lock:
                self._drop_failure(plugin_id)
            self._supervisor.reset_failure(plugin_id)
        live = self._live.get(target.context_id)
        if live is None:
            return
        stored = self._settings_store.get_settings(target.plugin_uuid, target.action_uuid, target.context_id)
        live.settings = apply_schema(live.action.settings, stored)
        self._send_context(live, "settings_changed", {"settings": live.settings})

    # ------------------------------------------------------------------
    # Server -> plugin helpers
    # ------------------------------------------------------------------

    def _send_context(self, live: _Live, event: str, payload: dict[str, Any] | None = None) -> None:
        self._supervisor.send(live.target.plugin_uuid, Message(event, live.target.context_id, payload or {}))

    def _send_will_appear(self, live: _Live) -> None:
        target = live.target
        column, row = self._key_position(target)
        payload = {
            "action": target.action_uuid,
            "device": target.device_id,
            "key": {"index": target.key_index, "column": column, "row": row},
            "settings": live.settings,
            "state": 0,
        }
        self._supervisor.send(target.plugin_uuid, Message("will_appear", target.context_id, payload))

    def _key_position(self, target: ActionTarget) -> tuple[int, int]:
        try:
            device = self._device_manager.open_device(target.device_id)
            key = device.get_hw_info().keys[target.key_index]
            if isinstance(key.col, int) and isinstance(key.row, int):
                return key.col, key.row
        except Exception:  # pylint: disable=broad-except
            logging.debug("No key layout for %s key %d", target.device_id, target.key_index)
        return target.key_index, 0

    def _gesture_emitter(self, context_id: str) -> Callable[[Gesture], None]:
        def _emit(gesture: Gesture) -> None:
            live = self._live.get(context_id)
            if live is not None:
                self._send_context(live, gesture.value)

        return _emit

    def _device_ids(self) -> list[str]:
        if self._device_manager is None:
            return []
        try:
            return [info.id for info in self._device_manager.list_devices() if isinstance(info.id, str)]
        except Exception:  # pylint: disable=broad-except
            logging.debug("Could not list devices for plugin announcement", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Plugin -> server handling
    # ------------------------------------------------------------------

    def _on_plugin_message(self, plugin_id: str, message: Message) -> None:
        try:
            self._route_message(plugin_id, message)
        except Exception:  # pylint: disable=broad-except
            logging.exception("[%s] failed to handle %s", plugin_id, message.event)

    def _route_message(self, plugin_id: str, message: Message) -> None:
        event = message.event
        if event == "ready":
            self._on_ready(plugin_id)
        elif event == "log":
            self._on_log(plugin_id, message.payload)
        elif event == "open_url":
            self._on_open_url(plugin_id, message.payload)
        elif event == "set_global_settings":
            logging.debug("[%s] global settings are not stored yet", plugin_id)
        else:
            self._route_context_message(plugin_id, message)

    def _route_context_message(self, plugin_id: str, message: Message) -> None:
        # The lock spans the liveness check and the sink call, so once deactivate_action returns no
        # further hardware effect for that context can happen. Sink calls are short local writes.
        with self._lock:
            live = self._live.get(message.context or "")
            if live is None or live.target.plugin_uuid != plugin_id:
                logging.debug("[%s] dropped %s for inactive context %s", plugin_id, message.event, message.context)
                return
            if self._apply_sink_event(live, message):
                return
        if message.event == "set_settings":
            self._on_set_settings(live, message.payload)
        elif message.event == "set_gestures":
            self._on_set_gestures(live, message.payload)

    def _apply_sink_event(self, live: _Live, message: Message) -> bool:
        target, payload = live.target, message.payload
        if message.event == "set_image":
            self._on_set_image(live, payload)
        elif message.event == "set_title":
            self._sink.set_title(target.device_id, target.key_index, str(payload.get("title", "")))
        elif message.event == "set_state":
            state = payload.get("state")
            self._sink.set_state(target.device_id, target.key_index, state if isinstance(state, int) else 0)
        elif message.event == "show_alert":
            self._sink.show_alert(target.device_id, target.key_index)
        elif message.event == "show_ok":
            self._sink.show_ok(target.device_id, target.key_index)
        else:
            return False
        return True

    def _on_ready(self, plugin_id: str) -> None:
        with self._lock:
            lives = [live for live in self._live.values() if live.target.plugin_uuid == plugin_id]
        for live in lives:
            self._send_will_appear(live)
        for device_id in self._device_ids():
            self._supervisor.send(plugin_id, Message("device_connected", payload={"device": device_id}))

    def _on_set_image(self, live: _Live, payload: dict[str, Any]) -> None:
        target = live.target
        image = payload.get("image")
        if image is None:
            self._sink.clear_image(target.device_id, target.key_index)
            return
        try:
            data = base64.b64decode(str(image), validate=True)
        except (binascii.Error, ValueError):
            logging.warning("[%s] set_image with invalid base64 dropped", target.plugin_uuid)
            return
        self._sink.set_image(target.device_id, target.key_index, data)

    def _on_set_settings(self, live: _Live, payload: dict[str, Any]) -> None:
        raw = payload.get("settings")
        if not isinstance(raw, dict):
            logging.warning("[%s] set_settings without a settings object dropped", live.target.plugin_uuid)
            return
        settings = apply_schema(live.action.settings, raw)
        live.settings = settings
        self.store_settings(live.target, settings)
        if self.settings_persister is not None:
            self.settings_persister(live.target, settings)

    def _on_set_gestures(self, live: _Live, payload: dict[str, Any]) -> None:
        gestures = _gestures_from(payload.get("gestures"))
        if not gestures:
            logging.warning("[%s] set_gestures without valid gestures ignored", live.target.plugin_uuid)
            return
        live.gestures = gestures

    @staticmethod
    def _on_log(plugin_id: str, payload: dict[str, Any]) -> None:
        levels = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}
        level = levels.get(str(payload.get("level", "info")).lower(), logging.INFO)
        logging.log(level, "[%s] %s", plugin_id, payload.get("message", ""))

    def _on_open_url(self, plugin_id: str, payload: dict[str, Any]) -> None:
        url = payload.get("url")
        parsed = urlparse(url) if isinstance(url, str) else None
        if parsed is None or parsed.scheme.lower() not in _OPEN_URL_SCHEMES or not parsed.netloc:
            logging.warning("[%s] open_url with unsupported url dropped: %r", plugin_id, url)
            return
        self._push("open_url", {"plugin_id": plugin_id, "url": url})

    def _on_plugin_failed(self, plugin_id: str, reason: str) -> None:
        logging.error("Plugin %s failed: %s", plugin_id, reason)
        event = PluginLoadFailedEvent(plugin_uuid=plugin_id, error=reason)
        with self._lock:
            self._drop_failure(plugin_id)
            self._failures.append(event)
            lives = [live for live in self._live.values() if live.target.plugin_uuid == plugin_id]
        for live in lives:
            self._mark_failed(live)
        self._push("plugin_failed", {"plugin_id": plugin_id, "error": reason})

    def _mark_failed(self, live: _Live) -> None:
        target = live.target
        with self._lock:
            if self._live.get(target.context_id) is not live:
                return
            self._sink.clear_image(target.device_id, target.key_index)
            self._sink.set_title(target.device_id, target.key_index, _FAILED_LABEL)

    def _drop_failure(self, plugin_id: str) -> None:
        self._failures = [f for f in self._failures if f.plugin_uuid != plugin_id]

    def _push(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._event_bus is not None:
            self._event_bus.push(event_type, json.dumps(payload))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _action_spec(self, plugin_id: str, action_id: str) -> ActionSpec | None:
        with self._lock:
            plugin = self._plugins.get(plugin_id)
        if plugin is None:
            return None
        return next((a for a in plugin.manifest.actions if a.id == action_id), None)

    @staticmethod
    def _make_settings_persister(context: "ServerContext") -> Callable[[ActionTarget, dict[str, Any]], None]:
        def _persist(target: ActionTarget, settings: dict[str, Any]) -> None:
            page_id = context.page_controller.active_page_id(target.device_id)
            context.key_assignment_store.update_settings(target.device_id, page_id, target.key_index, settings)

        return _persist

    def _make_state_changed_cb(self, context: "ServerContext") -> _StateChangedCallback:
        def _on_state_changed(device_id: str, key_index: int) -> None:
            device_state = context.device_manager.get_device_state(device_id)
            if device_state is None:
                return
            per_key = device_state.get_key_state(key_index)
            image_b64 = base64.b64encode(per_key.image).decode("ascii") if per_key.image else None
            context.event_bus.push(
                "key_state_changed",
                json.dumps(
                    {"device_id": device_id, "key_index": key_index, "image_b64": image_b64, "label": per_key.label}
                ),
            )

        return _on_state_changed

    def _set_key_label(self, device_id: str, key_index: int, label: str) -> None:
        if self._device_manager is None:
            return
        state = self._device_manager.get_device_state(device_id)
        if state is not None:
            state.update_key_label(key_index, label)

    def _icon_b64(self, plugin_dir: Path, icon: str | None) -> str:
        key = (plugin_dir, icon)
        if key not in self._icon_cache:
            data = read_icon(plugin_dir, icon)
            self._icon_cache[key] = base64.b64encode(data).decode("ascii") if data else ""
        return self._icon_cache[key]
