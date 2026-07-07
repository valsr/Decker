"""Scans ~/.decker/plugins/ at startup, discriminating native plugins from Elgato plugins."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from decker.common import paths as decker_paths
from decker.plugin.events import PluginLoadFailedEvent
from decker.plugin.manifest import ManifestValidationError, PluginManifest
from decker.plugin.native_loader import (
    LoadedNativePlugin,
    NativePluginLoadError,
    load_native_plugin,
)


@dataclass(frozen=True)
class DiscoveredElgatoPlugin:
    """An Elgato plugin found on disk — manifest only, subprocess not started yet."""

    manifest: PluginManifest
    plugin_dir: Path


@dataclass
class PluginScanResult:
    """Outcome of one plugin directory scan."""

    native: list[LoadedNativePlugin] = field(default_factory=list)
    elgato: list[DiscoveredElgatoPlugin] = field(default_factory=list)
    failures: list[PluginLoadFailedEvent] = field(default_factory=list)


class PluginLoader:
    """Discovers plugins in the plugins directory. Native plugins import immediately;

    Elgato plugins are only manifest-parsed here — their Node.js subprocess starts lazily.
    """

    def __init__(self, plugins_dir: str | Path | None = None) -> None:
        self._plugins_dir = Path(plugins_dir) if plugins_dir is not None else decker_paths.plugins()

    def scan(self) -> PluginScanResult:
        """Scan the plugins directory and load every entry found there."""
        result = PluginScanResult()
        if not self._plugins_dir.exists():
            return result

        for entry in sorted(self._plugins_dir.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.endswith(".sdPlugin"):
                self._load_elgato(entry, result)
            else:
                self._load_native(entry, result)
        return result

    def _load_native(self, entry: Path, result: PluginScanResult) -> None:
        try:
            loaded = load_native_plugin(entry)
        except NativePluginLoadError as exc:
            logging.error("Failed to load native plugin %s: %s", entry.name, exc)
            result.failures.append(PluginLoadFailedEvent(plugin_uuid=entry.name, error=str(exc)))
            return
        result.native.append(loaded)
        logging.info("Loaded native plugin %s", loaded.manifest.uuid)

    def _load_elgato(self, entry: Path, result: PluginScanResult) -> None:
        try:
            manifest = PluginManifest.load(entry / "manifest.json")
        except ManifestValidationError as exc:
            logging.error("Failed to load Elgato plugin %s: %s", entry.name, exc)
            result.failures.append(PluginLoadFailedEvent(plugin_uuid=entry.name, error=str(exc)))
            return
        result.elgato.append(DiscoveredElgatoPlugin(manifest=manifest, plugin_dir=entry))
        logging.info("Discovered Elgato plugin %s (subprocess deferred until activated)", manifest.uuid)
