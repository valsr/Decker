"""Scans a plugins directory for plugin folders and validates their manifests."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from decker.common import paths as decker_paths
from decker.plugin.events import PluginLoadFailedEvent
from decker.plugin.manifest import ManifestValidationError, PluginManifest


@dataclass(frozen=True)
class InstalledPlugin:
    """A plugin folder with a valid manifest."""

    manifest: PluginManifest
    plugin_dir: Path
    bundled: bool


@dataclass
class PluginScanResult:
    """Outcome of one plugin directory scan."""

    plugins: list[InstalledPlugin] = field(default_factory=list)
    failures: list[PluginLoadFailedEvent] = field(default_factory=list)


class PluginLoader:  # pylint: disable=too-few-public-methods
    """Discovers the plugin folders in one directory."""

    def __init__(self, plugins_dir: str | Path | None = None, bundled: bool = False) -> None:
        self._plugins_dir = Path(plugins_dir) if plugins_dir is not None else decker_paths.plugins()
        self._bundled = bundled

    def scan(self) -> PluginScanResult:
        """Validate the manifest of every folder in the plugins directory."""
        result = PluginScanResult()
        if not self._plugins_dir.exists():
            return result
        for entry in sorted(self._plugins_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            try:
                manifest = PluginManifest.load(entry / "manifest.json")
            except ManifestValidationError as exc:
                logging.error("Failed to load plugin %s: %s", entry.name, exc)
                result.failures.append(PluginLoadFailedEvent(plugin_uuid=entry.name, error=str(exc)))
                continue
            result.plugins.append(InstalledPlugin(manifest, entry, self._bundled))
            logging.info("Found plugin %s", manifest.id)
        return result
