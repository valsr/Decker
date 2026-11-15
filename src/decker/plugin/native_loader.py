"""Imports a native plugin's plugin.py and discovers its action classes."""

import importlib.util
import inspect
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from decker.plugin.base import DeckerPlugin
from decker.plugin.manifest import ManifestValidationError, PluginManifest


class NativePluginLoadError(Exception):
    """A native plugin's manifest.json or plugin.py failed to load."""


@dataclass(frozen=True)
class LoadedNativePlugin:
    """A successfully imported native plugin: its manifest and discovered action classes."""

    manifest: PluginManifest
    action_classes: dict[str, type[DeckerPlugin]]
    plugin_dir: Path


def load_native_plugin(plugin_dir: Path) -> LoadedNativePlugin:
    """Validate manifest.json, import plugin.py, and match declared actions to @action classes.

    Raises NativePluginLoadError on any failure — manifest invalid, plugin.py missing or
    raising on import, or a declared action with no matching class.
    """
    try:
        manifest = PluginManifest.load(plugin_dir / "manifest.json")
    except ManifestValidationError as exc:
        raise NativePluginLoadError(str(exc)) from exc

    module = _import_plugin_module(plugin_dir, manifest.uuid)
    action_classes = _discover_action_classes(module)

    declared_uuids = {plugin_action.uuid for plugin_action in manifest.actions}
    missing = declared_uuids - action_classes.keys()
    if missing:
        missing_str = ", ".join(sorted(missing))
        raise NativePluginLoadError(f"plugin.py does not implement action(s): {missing_str}")

    return LoadedNativePlugin(manifest=manifest, action_classes=action_classes, plugin_dir=plugin_dir)


def _import_plugin_module(plugin_dir: Path, plugin_uuid: str) -> ModuleType:
    plugin_py = plugin_dir / "plugin.py"
    if not plugin_py.exists():
        raise NativePluginLoadError(f"{plugin_py} does not exist")

    sanitized_uuid = plugin_uuid.replace(".", "_")
    module_name = f"decker_plugin_{sanitized_uuid}"
    spec = importlib.util.spec_from_file_location(module_name, plugin_py)
    if spec is None or spec.loader is None:
        raise NativePluginLoadError(f"could not create import spec for {plugin_py}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pylint: disable=broad-except
        raise NativePluginLoadError(f"error importing {plugin_py}: {exc}") from exc
    return module


def _discover_action_classes(module: ModuleType) -> dict[str, type[DeckerPlugin]]:
    action_classes: dict[str, type[DeckerPlugin]] = {}
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, DeckerPlugin) and obj is not DeckerPlugin and obj.action_uuid:
            action_classes[obj.action_uuid] = obj
    return action_classes
