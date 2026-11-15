"""Owns plugin discovery, the action registry, and callback execution."""

import base64
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from decker.asset.renderer import AssetRenderer
from decker.common.manager import Manager
from decker.plugin.context import ActionContext, ActionTarget
from decker.plugin.events import PluginLoadFailedEvent
from decker.plugin.executor import PluginExecutor
from decker.plugin.gestures import Gesture, GestureRecognizer
from decker.plugin.icons import read_icon
from decker.plugin.legacy_manifest import PluginManifest
from decker.plugin.loader import PluginLoader
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
        self._failures: list[PluginLoadFailedEvent] = []
        self._native_plugins: dict[str, LoadedNativePlugin] = {}
        self._device_manager: Any = None
        self._icon_cache: dict[tuple[Path, str | None], str] = {}
        self._recognizers: dict[str, GestureRecognizer] = {}
        self._sink: _StreamDeckHardwareSink = _StreamDeckHardwareSink(None, self._set_key_label)

    def create(self, context: "ServerContext") -> None:
        """Wire up the device manager, then scan and load plugins."""
        self._device_manager = context.device_manager
        self._sink = _StreamDeckHardwareSink(
            self._device_manager,
            self._set_key_label,
            on_state_changed=self._make_state_changed_cb(context),
        )
        bundled = self._bundled_loader.scan()
        user = self._user_loader.scan()
        self._failures = bundled.failures + user.failures
        for loaded in bundled.native + user.native:
            self._native_plugins[loaded.manifest.uuid] = loaded
        logging.info(
            "PluginManager started: %d loaded, %d failed to load",
            len(self._native_plugins),
            len(self._failures),
        )

    def destroy(self) -> None:
        """Stop plugin callbacks and release resources."""
        self._executor.shutdown()
        self._settings_store.close()

    def load_failures(self) -> list[PluginLoadFailedEvent]:
        """Return the plugins that failed to load at startup."""
        return list(self._failures)

    def list_actions(self) -> list[dict[str, str]]:
        """Return every action declared across all loaded plugin manifests.

        Each entry carries icon_b64: the action's icon image, base64-encoded, or "" if it has none.
        """
        actions: list[dict[str, str]] = []
        for loaded in self._native_plugins.values():
            actions.extend(self._manifest_actions(loaded.manifest, loaded.plugin_dir))
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
        self._recognizers[target.context_id] = GestureRecognizer(self._gesture_dispatcher(target))
        ctx = ActionContext(target, self._sink, self._settings_store)
        self._executor.dispatch(target.plugin_uuid, instance.on_will_appear, ctx)

    def deactivate_action(self, target: ActionTarget) -> None:
        """Dispatch on_will_disappear and drop the action instance from the registry."""
        instance = self._registry.get(target.plugin_uuid, target.action_uuid, target.context_id)
        if instance is None:
            return
        recognizer = self._recognizers.pop(target.context_id, None)
        if recognizer is not None:
            recognizer.cancel()
        ctx = ActionContext(target, self._sink, self._settings_store)
        self._executor.dispatch(target.plugin_uuid, instance.on_will_disappear, ctx)
        self._registry.unregister(target.plugin_uuid, target.action_uuid, target.context_id)

    def dispatch_key_down(self, target: ActionTarget) -> None:
        """Dispatch on_key_down, then feed the press to the action's gesture recognizer."""
        self._dispatch(target, "on_key_down")
        recognizer = self._recognizers.get(target.context_id)
        if recognizer is not None:
            recognizer.key_down(self._registered_gestures(target))

    def dispatch_key_up(self, target: ActionTarget) -> None:
        """Dispatch on_key_up, then feed the release to the action's gesture recognizer."""
        self._dispatch(target, "on_key_up")
        recognizer = self._recognizers.get(target.context_id)
        if recognizer is not None:
            recognizer.key_up()

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

    def _gesture_dispatcher(self, target: ActionTarget) -> Callable[[Gesture], None]:
        def _emit(gesture: Gesture) -> None:
            self._dispatch(target, f"on_{gesture.value}")

        return _emit

    def _registered_gestures(self, target: ActionTarget) -> frozenset[Gesture]:
        instance = self._registry.get(target.plugin_uuid, target.action_uuid, target.context_id)
        if instance is None:
            return frozenset()
        settings = self._settings_store.get_settings(target.plugin_uuid, target.action_uuid, target.context_id)
        try:
            return frozenset(Gesture(g) for g in instance.gestures(settings))
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Plugin %s gestures() failed, using press only: %s", target.plugin_uuid, exc)
            return frozenset({Gesture.PRESS})

    def _dispatch(self, target: ActionTarget, handler_name: str) -> None:
        instance = self._registry.get(target.plugin_uuid, target.action_uuid, target.context_id)
        if instance is None:
            logging.warning(
                "No live action instance for %s/%s/%s", target.plugin_uuid, target.action_uuid, target.context_id
            )
            return
        ctx = ActionContext(target, self._sink, self._settings_store)
        self._executor.dispatch(target.plugin_uuid, getattr(instance, handler_name), ctx)

    def _manifest_actions(self, manifest: PluginManifest, plugin_dir: Path) -> list[dict[str, str]]:
        return [
            {
                "plugin_uuid": manifest.uuid,
                "plugin_name": manifest.name,
                "action_uuid": plugin_action.uuid,
                "action_name": plugin_action.name,
                "icon_b64": self._icon_b64(plugin_dir, plugin_action.icon),
            }
            for plugin_action in manifest.actions
        ]

    def _icon_b64(self, plugin_dir: Path, icon: str | None) -> str:
        key = (plugin_dir, icon)
        if key not in self._icon_cache:
            data = read_icon(plugin_dir, icon)
            self._icon_cache[key] = base64.b64encode(data).decode("ascii") if data else ""
        return self._icon_cache[key]
