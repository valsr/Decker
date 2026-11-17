"""Scheduled checks of plugin repositories for updates and missing plugins."""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from packaging.version import InvalidVersion, Version

from decker.common import config
from decker.common.version import is_compatible
from decker.plugin.repository_index import IndexVersion, latest_compatible
from decker.server.key_assignments import KeyAssignmentStore
from decker.server.plugins import PluginManager
from decker.server.repositories import RepositoryStore

logger = logging.getLogger(__name__)

SCHEDULES: dict[str, int | None] = {"daily": 1, "weekly": 7, "monthly": 30, "manual": None}
EVENT_NAME = "plugin_updates_available"
CHECK_FINISHED_EVENT = "repositories_check_finished"
_CONFIG_KEY = "plugin.update_check"
_STOP_JOIN_SECONDS = 5.0  # how long stop() waits for each background thread
_WAKE_SECONDS = 3600.0
_DAY_SECONDS = 86400.0


@dataclass(frozen=True)
class UpdateReport:
    """Installed plugins with newer versions and plugins used by keys but not installed."""

    updates: tuple[dict[str, Any], ...] = ()
    missing: tuple[dict[str, Any], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        """Return the `plugin_updates_available` event payload."""
        return {"updates": [dict(item) for item in self.updates], "missing": [dict(item) for item in self.missing]}

    def is_empty(self) -> bool:
        """Return whether there is nothing to report."""
        return not self.updates and not self.missing


def _latest_compatible(versions: tuple[IndexVersion, ...]) -> str | None:
    best = latest_compatible(versions)
    return best.version if best is not None else None


def _is_newer(candidate: str, installed: str) -> bool:
    try:
        return Version(candidate) > Version(installed)
    except InvalidVersion:
        return False


class UpdateChecker:
    """Computes update reports from the repository cache and refreshes it on a schedule."""

    def __init__(
        self,
        store: RepositoryStore,
        plugin_manager: PluginManager,
        key_store: KeyAssignmentStore,
        push: Callable[[str, dict[str, Any]], None],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store: RepositoryStore = store
        self._plugins: PluginManager = plugin_manager
        self._keys: KeyAssignmentStore = key_store
        self._push: Callable[[str, dict[str, Any]], None] = push
        self._clock: Callable[[], float] = clock
        self._lock: threading.Lock = threading.Lock()
        self._check_lock: threading.Lock = threading.Lock()
        self._build_lock: threading.Lock = threading.Lock()
        self._async_running: bool = False
        self._report: UpdateReport = UpdateReport()
        self._stop: threading.Event = threading.Event()
        self._thread: threading.Thread | None = None
        self._async_thread: threading.Thread | None = None

    def start(self) -> None:
        """Report from the cached indexes (no network), then check hourly whether a refresh is due."""
        if self._thread is not None:
            return
        self._recompute(push_if_changed=False)
        if not self._report.is_empty():
            self._push(EVENT_NAME, self._report.to_payload())
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="plugin-update-check", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the scheduler and wait for a running manual check, so the stores can be destroyed safely after."""
        self._stop.set()
        thread, self._thread = self._thread, None
        with self._lock:
            manual, self._async_thread = self._async_thread, None
        for running in (thread, manual):
            if running is not None and running is not threading.current_thread():
                running.join(timeout=_STOP_JOIN_SECONDS)

    def report(self) -> UpdateReport:
        """Return the most recently computed report."""
        return self._report

    def schedule(self) -> str:
        """Return the configured schedule name, falling back to weekly."""
        value = str(config.get_or_default(_CONFIG_KEY, "weekly"))
        return value if value in SCHEDULES else "weekly"

    def set_schedule(self, name: str) -> None:
        """Persist the schedule; raises ValueError for an unknown name."""
        if name not in SCHEDULES:
            raise ValueError(f"Unknown update schedule: {name}")
        config.set(_CONFIG_KEY, name)

    def check_if_due(self) -> bool:
        """Run a check when the schedule says it is due. Returns whether one ran."""
        days = SCHEDULES[self.schedule()]
        if days is None:
            return False
        last = self._store.last_check()
        if last is not None and 0 <= self._clock() - last < days * _DAY_SECONDS:
            return False
        self.check_now()
        return True

    def check_now(self) -> UpdateReport:
        """Refresh every repository, record the check time and report any change."""
        with self._check_lock:
            infos = self._store.refresh_all()
            if not infos or any(info.error is None for info in infos):
                self._store.mark_checked(self._clock())
            return self._recompute(push_if_changed=True)

    def check_async(self) -> bool:
        """Run a check on a background thread; returns False when one is already running."""
        with self._lock:
            if self._async_running or self._check_lock.locked():
                return False
            self._async_running = True
            self._async_thread = threading.Thread(target=self._run_async_check, name="plugin-manual-check", daemon=True)
            self._async_thread.start()
        return True

    def refresh_local(self) -> UpdateReport:
        """Recompute from the cached indexes (no network) and push the report if it changed."""
        return self._recompute(push_if_changed=True)

    def _run_async_check(self) -> None:
        try:
            self.check_now()
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Plugin update check failed")
        finally:
            with self._lock:
                self._async_running = False
            repositories = [info.to_payload() for info in self._store.list_repositories()]
            self._push(CHECK_FINISHED_EVENT, {"repositories": repositories})

    def _run(self) -> None:
        self._scheduled_check()
        while not self._stop.wait(_WAKE_SECONDS):
            self._scheduled_check()

    def _scheduled_check(self) -> None:
        try:
            self.check_if_due()
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Scheduled plugin update check failed")

    def _recompute(self, push_if_changed: bool) -> UpdateReport:
        with self._build_lock:
            report = self._build()
            with self._lock:
                changed = report != self._report
                self._report = report
            if push_if_changed and changed:
                self._push(EVENT_NAME, report.to_payload())
        return report

    def _build(self) -> UpdateReport:
        installed = {plugin.manifest.id: plugin.manifest for plugin in self._plugins.plugins()}
        updates: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        referenced = self._keys.plugin_ids()
        for entry in self._store.catalog():
            if entry.shadowed_by is not None or self._plugins.is_builtin(entry.plugin.id):
                continue
            plugin = entry.plugin
            latest = _latest_compatible(plugin.versions)
            if latest is None:
                continue
            manifest = installed.get(plugin.id)
            if manifest is not None:
                if _is_newer(latest, manifest.version):
                    updates.append(
                        {"id": plugin.id, "name": manifest.name, "installed": manifest.version, "available": latest}
                    )
            elif plugin.id in referenced:
                keys = len(self._keys.assignments_for_plugin(plugin.id))
                missing.append({"id": plugin.id, "name": plugin.name, "version": latest, "keys": keys})
        return UpdateReport(tuple(updates), tuple(missing))
