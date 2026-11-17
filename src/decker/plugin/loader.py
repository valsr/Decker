"""Scans a plugins directory for plugin folders and validates their manifests."""

import json
import logging
import shutil
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


class PluginLoader:
    """Discovers the plugin folders in one directory."""

    def __init__(self, plugins_dir: str | Path | None = None, bundled: bool = False) -> None:
        self._plugins_dir = Path(plugins_dir) if plugins_dir is not None else decker_paths.plugins()
        self._bundled = bundled

    @property
    def plugins_dir(self) -> Path:
        """The folder this loader scans."""
        return self._plugins_dir

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


def recover_interrupted_installs(plugins_dir: Path) -> None:
    """Clean up after an install that was cut short: drop staging folders, put a moved-aside version back."""
    if not plugins_dir.is_dir():
        return
    for entry in sorted(plugins_dir.iterdir()):
        if not entry.is_dir() or entry.is_symlink():
            continue
        if entry.name.startswith(".staging-"):
            shutil.rmtree(entry, ignore_errors=True)
        elif entry.name.startswith(".old-"):
            _restore_or_drop(plugins_dir, entry)


def _restore_or_drop(plugins_dir: Path, old: Path) -> None:
    try:
        plugin_id = json.loads((old / "manifest.json").read_text(encoding="utf-8")).get("id")
    except (OSError, ValueError, AttributeError):
        plugin_id = None
    target = plugins_dir / plugin_id if isinstance(plugin_id, str) and plugin_id and "/" not in plugin_id else None
    if target is not None and not target.exists():
        old.rename(target)
        logging.warning("Restored plugin %s from an interrupted install", plugin_id)
    else:
        shutil.rmtree(old, ignore_errors=True)
