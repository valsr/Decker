"""Owns plugin discovery, the action registry, callback execution, and the Elgato bridge."""

import base64
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from decker.asset.renderer import AssetRenderer
from decker.common import config
from decker.common.manager import Manager
from decker.plugin.context import ActionContext, ActionTarget
from decker.plugin.elgato.bridge import DEFAULT_PORT as ELGATO_BRIDGE_PORT
from decker.plugin.elgato.bridge import ElgatoBridge
from decker.plugin.elgato.process import (
    ElgatoPluginProcess,
    ElgatoPluginProcessError,
    ElgatoProcessConfig,
)
from decker.plugin.events import PluginLoadFailedEvent
from decker.plugin.executor import PluginExecutor
from decker.plugin.loader import DiscoveredElgatoPlugin, PluginLoader
from decker.plugin.manifest import PluginManifest
from decker.plugin.native_loader import LoadedNativePlugin
from decker.plugin.registry import ActionRegistry
from decker.plugin.settings_store import PluginSettingsStore

if TYPE_CHECKING:
    from decker.server.server_context import ServerContext

_BUNDLED_PLUGINS_DIR = Path(__file__).parent.parent / "bundled_plugins"


_StateChangedCallback = Callable[[str, int], None]


class _StreamDeckHardwareSink:
    """Applies hardware effects via DeviceManager; falls back gracefully if no device is open.

    set_title is deliberately lightweight — it stores the label in the shared label dict
    for client polling instead of rendering text to hardware (the plugin handles its own
    hardware rendering via set_image).
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

    def set_state(self, device_id: str, key_index: int, state: int) -> None:
        """No-op: multi-state icon rendering is not implemented yet."""
        logging.debug("set_state(%s, %d, %d): not implemented", device_id, key_index, state)

    def show_alert(self, device_id: str, key_index: int) -> None:
        """No-op: indicator rendering is not implemented yet."""
        logging.debug("show_alert(%s, %d): not implemented", device_id, key_index)

    def show_ok(self, device_id: str, key_index: int) -> None:
        """No-op: indicator rendering is not implemented yet."""
        logging.debug("show_ok(%s, %d): not implemented", device_id, key_index)


class PluginManager(Manager):  # pylint: disable=too-many-instance-attributes
    """Owned by the server: discovers plugins at startup and dispatches their callbacks."""

    def __init__(self, plugins_dir: Path | None = None) -> None:
        self._registry = ActionRegistry()
        self._executor = PluginExecutor()
        self._settings_store = PluginSettingsStore()
        self._user_loader = PluginLoader(plugins_dir) if plugins_dir is not None else PluginLoader()
        self._bundled_loader = PluginLoader(_BUNDLED_PLUGINS_DIR)
        self._bridge: ElgatoBridge | None = None
        self._failures: list[PluginLoadFailedEvent] = []
        self._native_plugins: dict[str, LoadedNativePlugin] = {}
        self._elgato_plugins: dict[str, DiscoveredElgatoPlugin] = {}
        self._elgato_processes: dict[str, ElgatoPluginProcess] = {}
        self._elgato_live_contexts: dict[str, set[str]] = {}
        self._device_manager: Any = None
        self._sink: _StreamDeckHardwareSink = _StreamDeckHardwareSink(None, self._set_key_label)

    def create(self, context: "ServerContext") -> None:
        """Wire up the device manager, scan and load plugins, then start the Elgato bridge."""
        self._device_manager = context.device_manager
        self._sink = _StreamDeckHardwareSink(
            self._device_manager,
            self._set_key_label,
            on_state_changed=self._make_state_changed_cb(context),
        )
        self._bridge = ElgatoBridge(self._sink, self._settings_store)
        bundled = self._bundled_loader.scan()
        user = self._user_loader.scan()
        self._failures = bundled.failures + user.failures
        for loaded in bundled.native + user.native:
            self._native_plugins[loaded.manifest.uuid] = loaded
        for discovered in bundled.elgato + user.elgato:
            self._elgato_plugins[discovered.manifest.uuid] = discovered
        self._bridge.start()
        logging.info(
            "PluginManager started: %d native, %d Elgato, %d failed to load",
            len(self._native_plugins),
            len(self._elgato_plugins),
            len(self._failures),
        )

    def destroy(self) -> None:
        """Stop the Elgato bridge, plugin subprocesses, and release resources."""
        for process in self._elgato_processes.values():
            process.stop()
        self._elgato_processes.clear()
        if self._bridge is not None:
            self._bridge.stop()
        self._executor.shutdown()
        self._settings_store.close()

    def load_failures(self) -> list[PluginLoadFailedEvent]:
        """Return the plugins that failed to load at startup."""
        return list(self._failures)

    def list_actions(self) -> list[dict[str, str]]:
        """Return every action declared across all loaded plugin manifests."""
        actions: list[dict[str, str]] = []
        for loaded in self._native_plugins.values():
            actions.extend(self._manifest_actions(loaded.manifest))
        for discovered in self._elgato_plugins.values():
            actions.extend(self._manifest_actions(discovered.manifest))
        return actions

    def get_key_display_states(self, device_id: str) -> list[dict[str, Any]]:
        """Return current display labels for all keys on this device."""
        state = self._device_manager.get_device_state(device_id) if self._device_manager is not None else None
        if state is None:
            return []
        return [{"key_index": k, "label": v} for k, v in state.get_all_labels()]

    def store_settings(self, target: ActionTarget, settings: dict[str, Any]) -> None:
        """Persist settings for an action instance so its plugin reads them on activation."""
        self._settings_store.set_settings(target.plugin_uuid, target.action_uuid, target.context_id, settings)

    def activate_action(self, target: ActionTarget) -> None:
        """Instantiate a native action for this target and dispatch on_will_appear."""
        loaded = self._native_plugins.get(target.plugin_uuid)
        if loaded is None or target.action_uuid not in loaded.action_classes:
            logging.warning("Cannot activate unknown action %s/%s", target.plugin_uuid, target.action_uuid)
            return
        instance = loaded.action_classes[target.action_uuid]()
        self._registry.register(target.plugin_uuid, target.action_uuid, target.context_id, instance)
        ctx = ActionContext(target, self._sink, self._settings_store)
        self._executor.dispatch(target.plugin_uuid, instance.on_will_appear, ctx)

    def deactivate_action(self, target: ActionTarget) -> None:
        """Dispatch on_will_disappear and drop the action instance from the registry."""
        instance = self._registry.get(target.plugin_uuid, target.action_uuid, target.context_id)
        if instance is None:
            return
        ctx = ActionContext(target, self._sink, self._settings_store)
        self._executor.dispatch(target.plugin_uuid, instance.on_will_disappear, ctx)
        self._registry.unregister(target.plugin_uuid, target.action_uuid, target.context_id)

    def activate_elgato_action(self, plugin_uuid: str, context_id: str) -> None:
        """Spawn the plugin's Node.js subprocess if this is its first live action instance."""
        discovered = self._elgato_plugins.get(plugin_uuid)
        if discovered is None:
            logging.warning("Cannot activate unknown Elgato plugin %s", plugin_uuid)
            return

        live_contexts = self._elgato_live_contexts.setdefault(plugin_uuid, set())
        if not live_contexts:
            process = ElgatoPluginProcess(
                ElgatoProcessConfig(
                    plugin_dir=discovered.plugin_dir,
                    entry_point=discovered.manifest.code_path or "app.js",
                    port=ELGATO_BRIDGE_PORT,
                    plugin_uuid=plugin_uuid,
                    node_path=config.get_as_or_default("plugin.nodejs_path", str, "node"),
                )
            )
            try:
                process.start()
            except ElgatoPluginProcessError as exc:
                logging.error("%s", exc)
                return
            self._elgato_processes[plugin_uuid] = process
        live_contexts.add(context_id)

    def deactivate_elgato_action(self, plugin_uuid: str, context_id: str) -> None:
        """Tear down the plugin's Node.js subprocess once its last live action instance is gone."""
        live_contexts = self._elgato_live_contexts.get(plugin_uuid)
        if live_contexts is None:
            return
        live_contexts.discard(context_id)
        if not live_contexts and plugin_uuid in self._elgato_processes:
            self._elgato_processes.pop(plugin_uuid).stop()

    def dispatch_key_down(self, target: ActionTarget) -> None:
        """Dispatch on_key_down to the live action instance for this target."""
        self._dispatch(target, "on_key_down")

    def dispatch_key_up(self, target: ActionTarget) -> None:
        """Dispatch on_key_up to the live action instance for this target."""
        self._dispatch(target, "on_key_up")

    def dispatch_settings_changed(self, target: ActionTarget) -> None:
        """Dispatch on_settings_changed to the live action instance for this target."""
        self._dispatch(target, "on_settings_changed")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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

    def _dispatch(self, target: ActionTarget, handler_name: str) -> None:
        instance = self._registry.get(target.plugin_uuid, target.action_uuid, target.context_id)
        if instance is None:
            logging.warning(
                "No live action instance for %s/%s/%s", target.plugin_uuid, target.action_uuid, target.context_id
            )
            return
        ctx = ActionContext(target, self._sink, self._settings_store)
        self._executor.dispatch(target.plugin_uuid, getattr(instance, handler_name), ctx)

    @staticmethod
    def _manifest_actions(manifest: PluginManifest) -> list[dict[str, str]]:
        return [
            {
                "plugin_uuid": manifest.uuid,
                "plugin_name": manifest.name,
                "action_uuid": plugin_action.uuid,
                "action_name": plugin_action.name,
            }
            for plugin_action in manifest.actions
        ]
