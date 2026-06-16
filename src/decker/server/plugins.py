"""Owns plugin discovery, the action registry, callback execution, and the Elgato bridge."""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper

from decker.asset.renderer import AssetRenderer
from decker.common import config
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
from decker.plugin.native_loader import LoadedNativePlugin
from decker.plugin.registry import ActionRegistry
from decker.plugin.settings_store import PluginSettingsStore
from decker.server.devices import device_id_for_serial


class _StreamDeckHardwareSink:
    """Applies hardware effects to a Stream Deck device, opened on demand by its stable id.

    Only image rendering is implemented today — title overlays, multi-state icons, and
    alert/ok indicators require a rendering pipeline beyond plain images, which doesn't
    exist yet.
    """

    def __init__(self) -> None:
        self._renderer = AssetRenderer()

    def set_image(self, device_id: str, key_index: int, image: bytes) -> None:
        """Render image (SVG/PNG/JPEG bytes, or already-native bytes) on the given device's key."""
        self._with_device(device_id, lambda deck: self._render_and_push(deck, key_index, image))

    def _render_and_push(self, deck: Any, key_index: int, image: bytes) -> None:
        pil_image = self._renderer.render_bytes(image, deck.KEY_PIXEL_WIDTH, deck.KEY_PIXEL_HEIGHT)
        if pil_image is None:
            deck.set_key_image(key_index, image)
            return
        scaled = PILHelper.create_scaled_key_image(deck, pil_image)
        native_image = PILHelper.to_native_key_format(deck, scaled)
        deck.set_key_image(key_index, native_image)

    def set_title(self, device_id: str, key_index: int, title: str) -> None:
        """No-op: text rendering is not implemented yet."""
        logging.debug("set_title(%s, %d, %r): no rendering pipeline yet, ignored", device_id, key_index, title)

    def set_state(self, device_id: str, key_index: int, state: int) -> None:
        """No-op: multi-state icon rendering is not implemented yet."""
        logging.debug("set_state(%s, %d, %d): no rendering pipeline yet, ignored", device_id, key_index, state)

    def show_alert(self, device_id: str, key_index: int) -> None:
        """No-op: indicator rendering is not implemented yet."""
        logging.debug("show_alert(%s, %d): no rendering pipeline yet, ignored", device_id, key_index)

    def show_ok(self, device_id: str, key_index: int) -> None:
        """No-op: indicator rendering is not implemented yet."""
        logging.debug("show_ok(%s, %d): no rendering pipeline yet, ignored", device_id, key_index)

    def _with_device(self, device_id: str, apply: Callable[..., None]) -> None:
        try:
            decks = DeviceManager().enumerate()
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Could not enumerate Stream Deck devices: %s", exc)
            return

        for deck in decks:
            try:
                deck.open()
                if device_id_for_serial(deck.get_serial_number()) != device_id:
                    continue
                apply(deck)
                return
            except Exception as exc:  # pylint: disable=broad-except
                logging.error("Hardware operation failed for device %s: %s", device_id, exc)
                return
            finally:
                try:
                    deck.close()
                except Exception:  # pylint: disable=broad-except
                    pass
        logging.warning("Device %s not found", device_id)


class PluginManager:  # pylint: disable=too-many-instance-attributes
    """Owned by the server: discovers plugins at startup and dispatches their callbacks."""

    def __init__(self, plugins_dir: Path | None = None) -> None:
        self._registry = ActionRegistry()
        self._executor = PluginExecutor()
        self._settings_store = PluginSettingsStore()
        self._sink = _StreamDeckHardwareSink()
        self._loader = PluginLoader(plugins_dir) if plugins_dir is not None else PluginLoader()
        self._bridge = ElgatoBridge(self._sink, self._settings_store)
        self._failures: list[PluginLoadFailedEvent] = []
        self._native_plugins: dict[str, LoadedNativePlugin] = {}
        self._elgato_plugins: dict[str, DiscoveredElgatoPlugin] = {}
        self._elgato_processes: dict[str, ElgatoPluginProcess] = {}
        self._elgato_live_contexts: dict[str, set[str]] = {}

    def start(self) -> None:
        """Scan and load plugins, then start the Elgato WebSocket bridge."""
        result = self._loader.scan()
        self._failures = result.failures
        for loaded in result.native:
            self._native_plugins[loaded.manifest.uuid] = loaded
        for discovered in result.elgato:
            self._elgato_plugins[discovered.manifest.uuid] = discovered
        self._bridge.start()
        logging.info(
            "PluginManager started: %d native, %d Elgato, %d failed to load",
            len(result.native),
            len(result.elgato),
            len(result.failures),
        )

    def stop(self) -> None:
        """Stop the Elgato bridge, any running plugin subprocesses, and release plugin resources."""
        for process in self._elgato_processes.values():
            process.stop()
        self._elgato_processes.clear()
        self._bridge.stop()
        self._executor.shutdown()
        self._settings_store.close()

    def load_failures(self) -> list[PluginLoadFailedEvent]:
        """Return the plugins that failed to load at startup."""
        return list(self._failures)

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

    def _dispatch(self, target: ActionTarget, handler_name: str) -> None:
        instance = self._registry.get(target.plugin_uuid, target.action_uuid, target.context_id)
        if instance is None:
            logging.warning(
                "No live action instance for %s/%s/%s", target.plugin_uuid, target.action_uuid, target.context_id
            )
            return
        ctx = ActionContext(target, self._sink, self._settings_store)
        self._executor.dispatch(target.plugin_uuid, getattr(instance, handler_name), ctx)
