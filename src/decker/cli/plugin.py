"""Local filesystem operations for installing, listing, and removing plugins.

Unlike other CLI commands, these never talk to the server — they only touch
~/.decker/plugins/. A server restart is required to pick up the change.
"""

import shutil
from pathlib import Path

from decker.plugin.manifest import ManifestValidationError, PluginManifest

_PLUGINS_DIR = Path.home() / ".decker" / "plugins"


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

    dest_dir = _PLUGINS_DIR / _install_dir_name(manifest)
    if dest_dir.exists():
        raise PluginCliError(f"a plugin is already installed at {dest_dir}")

    _PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, dest_dir)
    return dest_dir


def list_installed() -> list[dict[str, str]]:
    """Return metadata for every plugin in ~/.decker/plugins/: uuid, type, and status."""
    if not _PLUGINS_DIR.exists():
        return []

    entries: list[dict[str, str]] = []
    for entry in sorted(_PLUGINS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        plugin_type = "elgato" if entry.name.endswith(".sdPlugin") else "native"
        try:
            manifest = PluginManifest.load(entry / "manifest.json")
            entries.append({"uuid": manifest.uuid, "type": plugin_type, "status": "ok"})
        except ManifestValidationError as exc:
            entries.append({"uuid": entry.name, "type": plugin_type, "status": f"invalid: {exc}"})
    return entries


def remove(uuid: str) -> None:
    """Remove the installed plugin matching uuid (native or .sdPlugin). Raises PluginCliError if not found."""
    for candidate in (_PLUGINS_DIR / uuid, _PLUGINS_DIR / f"{uuid}.sdPlugin"):
        if candidate.exists():
            shutil.rmtree(candidate)
            return
    raise PluginCliError(f"no installed plugin found with uuid {uuid!r}")


def _install_dir_name(manifest: PluginManifest) -> str:
    return f"{manifest.uuid}.sdPlugin" if manifest.code_path else manifest.uuid
