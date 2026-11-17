"""Installs, upgrades and uninstalls .deckerplugin packages on the server."""

import json
import logging
import shutil
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet

from decker.plugin.environment import EnvironmentBuildError, build_environment
from decker.plugin.loader import InstalledPlugin
from decker.plugin.manifest import PluginManifest
from decker.plugin.package import PackageError, extract, read_manifest
from decker.plugin.runtime.launcher import launch_command
from decker.server.page_controller import PAGES_CHANGED_EVENT

if TYPE_CHECKING:
    from decker.server.server_context import ServerContext

PLUGIN_INSTALL_PROGRESS_EVENT = "plugin_install_progress"
PLUGIN_INSTALL_FINISHED_EVENT = "plugin_install_finished"
PLUGINS_CHANGED_EVENT = "plugins_changed"
_UNINSTALL_WAIT_S = 2.0
_MAX_JOBS = 20
_BUSY = "busy: another plugin install or uninstall is in progress; try again when it has finished"


class PluginInstallError(Exception):
    """A plugin could not be installed or uninstalled."""


@dataclass(frozen=True)
class _Outcome:
    plugin_id: str
    version: str
    previous_version: str | None


@dataclass
class _Swap:
    """What an upgrade needs to put the previous version back."""

    plugin_id: str
    final: Path
    old: Path
    existing: InstalledPlugin | None
    preexisting: bool


class PluginInstaller:
    """Validates and installs plugin packages, replacing an installed version without losing its live keys."""

    def __init__(self, plugins_dir: Path, context: "ServerContext", decker_version: str) -> None:
        self._plugins_dir = plugins_dir
        self._context = context
        self._decker_version = decker_version
        self._op_lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._jobs_lock = threading.Lock()

    def install(self, filename: str, data: bytes) -> str:
        """Start installing a package in the background and return the job id; raises if one is already running."""
        if not self._op_lock.acquire(blocking=False):
            raise PluginInstallError(_BUSY)
        job_id = uuid.uuid4().hex
        try:
            self._update_job(job_id, state="running", message=f"Checking {filename}")
            threading.Thread(target=self._run_install, args=(job_id, filename, data), daemon=True).start()
        except BaseException:
            self._op_lock.release()
            raise
        return job_id

    def status(self, job_id: str) -> dict[str, Any]:
        """Return an install job's state: running, succeeded or failed (unknown for an id the server never saw)."""
        with self._jobs_lock:
            job = self._jobs.get(job_id)
            return dict(job) if job is not None else {"job_id": job_id, "state": "unknown", "message": "unknown job"}

    def uninstall(self, plugin_id: str) -> None:
        """Remove a user-installed plugin (or a broken plugin folder), its key assignments, settings and folder."""
        if not self._op_lock.acquire(timeout=_UNINSTALL_WAIT_S):
            raise PluginInstallError(_BUSY)
        try:
            devices = self._uninstall_locked(plugin_id)
        finally:
            self._op_lock.release()
        self._push(PLUGINS_CHANGED_EVENT, {})
        for device_id in sorted(devices):
            self._push(PAGES_CHANGED_EVENT, {"device_id": device_id})

    def _uninstall_locked(self, plugin_id: str) -> set[str]:
        plugin = self._find(plugin_id)
        plugins = self._context.plugin_manager
        if plugin is None:
            folder = self._broken_folder(plugin_id)
            if folder is None:
                raise PluginInstallError(f"plugin {plugin_id} is not installed")
            plugins.remove_plugin(plugin_id)
            shutil.rmtree(folder, ignore_errors=True)
            return set()
        if plugin.bundled:
            raise PluginInstallError(f"{plugin_id} is bundled with Decker and cannot be uninstalled")
        for target in plugins.live_targets(plugin_id):
            plugins.deactivate_action(target)
        plugins.remove_plugin(plugin_id)
        devices = self._clear_assignments(plugin_id)
        plugins.delete_plugin_settings(plugin_id)
        shutil.rmtree(plugin.plugin_dir, ignore_errors=True)
        return devices

    def _broken_folder(self, name: str) -> Path | None:
        """A user plugin folder that failed to load (it has no registered plugin), addressed by folder name."""
        if not name or name.startswith(".") or "/" in name or "\\" in name or "\0" in name:
            return None
        folder = self._plugins_dir / name
        return folder if folder.is_dir() and not folder.is_symlink() else None

    def usage(self, plugin_id: str) -> int:
        """Return how many keys, across all devices and pages, use the plugin's actions."""
        return len(self._context.key_assignment_store.assignments_for_plugin(plugin_id))

    # ------------------------------------------------------------------
    # Install
    # ------------------------------------------------------------------

    def _run_install(self, job_id: str, filename: str, data: bytes) -> None:
        def progress(message: str) -> None:
            self._update_job(job_id, message=message)
            self._push("plugin_install_progress", {"job_id": job_id, "message": message})

        try:
            progress(f"Checking {filename}")
            outcome = self._install(job_id, data, progress)
        except (PackageError, EnvironmentBuildError, PluginInstallError, OSError) as exc:
            self._op_lock.release()
            self._finish(job_id, None, str(exc))
            return
        except Exception:  # pylint: disable=broad-except
            logging.exception("Unexpected failure installing %s", filename)
            self._op_lock.release()
            self._finish(job_id, None, "unexpected error while installing the plugin")
            return
        self._op_lock.release()
        self._finish(job_id, outcome, f"Installed {outcome.plugin_id} {outcome.version}")
        self._push(PLUGINS_CHANGED_EVENT, {})

    def _install(self, job_id: str, data: bytes, progress: Callable[[str], None]) -> _Outcome:
        manifest = read_manifest(data)
        existing = self._find(manifest.id)
        if existing is not None and existing.bundled:
            raise PluginInstallError(f"{manifest.id} is bundled with Decker and cannot be replaced")
        self._check_decker_version(manifest)
        self._plugins_dir.mkdir(parents=True, exist_ok=True)
        staging = self._plugins_dir / f".staging-{job_id}"
        try:
            progress("Extracting package")
            extract(data, staging)
            self._make_entry_executable(manifest, staging)
            if manifest.runtime is not None and manifest.runtime.type == "python":
                progress("Building the plugin environment")
                build_environment(staging, manifest.runtime, progress)
            self._check_launchable(manifest, staging)
            previous = self._swap_in(job_id, manifest, staging, existing)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return _Outcome(manifest.id, manifest.version, previous)

    @staticmethod
    def _check_launchable(manifest: PluginManifest, staging: Path) -> None:
        runtime = manifest.runtime
        if runtime is None:
            return
        try:
            launch_command(staging, runtime, bundled=False)
        except ValueError as exc:
            raise PluginInstallError(str(exc)) from exc
        if not (staging / runtime.entry).is_file():
            raise PluginInstallError(f"runtime entry '{runtime.entry}' is missing from the package")
        if runtime.type == "python" and not (staging / ".venv" / "bin" / "python").exists():
            raise PluginInstallError("the plugin environment has no Python interpreter")

    @staticmethod
    def _make_entry_executable(manifest: PluginManifest, staging: Path) -> None:
        # extract() does not keep zip file modes, and an executable runtime is launched directly.
        if manifest.runtime is not None and manifest.runtime.type == "executable":
            entry = staging / manifest.runtime.entry
            if entry.is_file():
                entry.chmod(entry.stat().st_mode | 0o111)

    def _check_decker_version(self, manifest: PluginManifest) -> None:
        if manifest.decker is None:
            return
        try:
            compatible = SpecifierSet(manifest.decker).contains(self._decker_version, prereleases=True)
        except InvalidSpecifier as exc:
            raise PluginInstallError(f"invalid Decker version requirement {manifest.decker!r}") from exc
        if not compatible:
            raise PluginInstallError(
                f"requires Decker {manifest.decker} (this server runs Decker {self._decker_version})"
            )

    def _swap_in(
        self, job_id: str, manifest: PluginManifest, staging: Path, existing: InstalledPlugin | None
    ) -> str | None:
        plugins = self._context.plugin_manager
        targets = plugins.live_targets(manifest.id)
        final = existing.plugin_dir if existing is not None else self._plugins_dir / manifest.id
        swap = _Swap(
            plugin_id=manifest.id,
            final=final,
            old=self._plugins_dir / f".old-{job_id}",
            existing=existing,
            preexisting=final.exists(),
        )
        for target in targets:
            plugins.deactivate_action(target)
        if existing is not None:
            plugins.remove_plugin(manifest.id)
        try:
            if swap.preexisting:
                swap.final.rename(swap.old)
            staging.rename(swap.final)
            plugins.add_plugin(InstalledPlugin(manifest, swap.final, False))
            self._reactivate(manifest.id)
        except Exception:
            self._roll_back(swap)
            raise
        shutil.rmtree(swap.old, ignore_errors=True)
        return existing.manifest.version if existing is not None else None

    def _reactivate(self, plugin_id: str) -> None:
        # Recomputed from current state: a page switch may have landed since the old targets were deactivated.
        ctx = self._context
        for device_id, page_id, _key_index, assignment in ctx.key_assignment_store.assignments_for_plugin(plugin_id):
            if ctx.page_controller.active_page_id(device_id) == page_id:
                ctx.plugin_manager.store_settings(assignment.target, assignment.settings)
                ctx.plugin_manager.activate_action(assignment.target, assignment.appearance)

    def _roll_back(self, swap: _Swap) -> None:
        plugins = self._context.plugin_manager
        try:
            for target in plugins.live_targets(swap.plugin_id):
                plugins.deactivate_action(target)
            plugins.remove_plugin(swap.plugin_id)
            if swap.old.exists():
                shutil.rmtree(swap.final, ignore_errors=True)
                swap.old.rename(swap.final)
            elif not swap.preexisting:
                shutil.rmtree(swap.final, ignore_errors=True)
            if swap.existing is not None:
                plugins.add_plugin(swap.existing)
                self._reactivate(swap.plugin_id)
        except Exception:  # pylint: disable=broad-except
            logging.exception("Could not fully restore the previous plugin version")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find(self, plugin_id: str) -> InstalledPlugin | None:
        return next((p for p in self._context.plugin_manager.plugins() if p.manifest.id == plugin_id), None)

    def _clear_assignments(self, plugin_id: str) -> set[str]:
        ctx = self._context
        devices: set[str] = set()
        for device_id, page_id, key_index, _assignment in ctx.key_assignment_store.assignments_for_plugin(plugin_id):
            ctx.key_assignment_store.unassign(device_id, page_id, key_index)
            if ctx.page_controller.active_page_id(device_id) == page_id:
                ctx.device_manager.clear_key_state(device_id, key_index)
            else:
                ctx.device_state_store.delete_key_state(device_id, page_id, key_index)
            devices.add(device_id)
        return devices

    def _update_job(self, job_id: str, **fields: Any) -> None:
        with self._jobs_lock:
            job = self._jobs.setdefault(job_id, {"job_id": job_id})
            job.update(fields)
            while len(self._jobs) > _MAX_JOBS:
                self._jobs.pop(next(iter(self._jobs)))

    def _finish(self, job_id: str, outcome: _Outcome | None, message: str) -> None:
        self._update_job(
            job_id,
            state="succeeded" if outcome is not None else "failed",
            message=message,
            plugin_id=outcome.plugin_id if outcome else None,
            version=outcome.version if outcome else None,
        )
        self._push(
            PLUGIN_INSTALL_FINISHED_EVENT,
            {
                "job_id": job_id,
                "ok": outcome is not None,
                "plugin_id": outcome.plugin_id if outcome else None,
                "version": outcome.version if outcome else None,
                "previous_version": outcome.previous_version if outcome else None,
                "message": message,
            },
        )

    def _push(self, event_type: str, payload: dict[str, Any]) -> None:
        self._context.event_bus.push(event_type, json.dumps(payload))
