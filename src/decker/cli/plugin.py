"""Local filesystem operations for installing, listing, and removing plugins.

Unlike other CLI commands, these never talk to the server — they only touch
~/.decker/plugins/. A server restart is required to pick up the change.
"""

import shutil
from pathlib import Path

from decker.common import paths as decker_paths
from decker.plugin.manifest import ManifestValidationError, PluginManifest


class PluginCliError(Exception):
    """A plugin CLI operation failed."""


def install(source: str | Path) -> Path:
    """Validate the plugin at source and copy it into ~/.decker/plugins/. Returns the install path."""
    source_dir = Path(source)
    manifest_path = source_dir / "manifest.json"
    if not manifest_path.exists():
        raise PluginCliError(f"{manifest_path} not found")
    try:
        manifest = PluginManifest.load(manifest_path)
    except ManifestValidationError as exc:
        raise PluginCliError(str(exc)) from exc

    plugins_dir = decker_paths.plugins()
    dest_dir = plugins_dir / manifest.uuid
    if dest_dir.exists():
        raise PluginCliError(f"a plugin is already installed at {dest_dir}")

    plugins_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, dest_dir)
    return dest_dir


def list_installed() -> list[dict[str, str]]:
    """Return metadata for every plugin in ~/.decker/plugins/: uuid and status."""
    plugins_dir = decker_paths.plugins()
    if not plugins_dir.exists():
        return []

    entries: list[dict[str, str]] = []
    for entry in sorted(plugins_dir.iterdir()):
        if not entry.is_dir():
            continue
        try:
            manifest = PluginManifest.load(entry / "manifest.json")
            entries.append({"uuid": manifest.uuid, "status": "ok"})
        except ManifestValidationError as exc:
            entries.append({"uuid": entry.name, "status": f"invalid: {exc}"})
    return entries


def remove(uuid: str) -> None:
    """Remove the installed plugin matching uuid. Raises PluginCliError if not found."""
    candidate = decker_paths.plugins() / uuid
    if candidate.exists():
        shutil.rmtree(candidate)
        return
    raise PluginCliError(f"no installed plugin found with uuid {uuid!r}")
