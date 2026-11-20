"""Asks plugins for variable values off-thread and pushes variable changes to running plugins."""

import logging
import threading
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from decker.common.variables import value_text
from decker.plugin.protocol import Message
from decker.plugin.runtime.supervisor import PluginSupervisor
from decker.server.variables import VariableStore

DEFAULT_TIMEOUT_S = 5.0


@dataclass
class _Pending:
    plugin_id: str
    epoch: int
    done: threading.Event = field(default_factory=threading.Event)
    stopped: bool = False
    value: str | None = None
    error: str = "no answer"


class VariableRunner:  # pylint: disable=too-many-instance-attributes
    """Fills the VariableStore from plugin getters and keeps every ready plugin's copy of the variables current."""

    def __init__(self, supervisor: PluginSupervisor, store: VariableStore, timeout: float = DEFAULT_TIMEOUT_S) -> None:
        self._supervisor: PluginSupervisor = supervisor
        self._store: VariableStore = store
        self._timeout: float = timeout
        self._lock: threading.Lock = threading.Lock()
        self._push_lock: threading.Lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        self._inflight: set[tuple[str, str]] = set()
        self._dirty: set[tuple[str, str]] = set()
        self._failing: set[tuple[str, str]] = set()
        self._epochs: dict[str, int] = {}  # per plugin id, bumped whenever its process stops; survives restarts
        self._closed: bool = False

    def ask(self, plugin_id: str, name: str) -> None:
        """Ask the plugin for a value without waiting; repeats during an ask collapse into one more ask after it."""
        key = (plugin_id, name)
        with self._lock:
            if self._closed:
                return
            if key in self._inflight:
                self._dirty.add(key)
                return
            self._inflight.add(key)
            request, pending = self._new_request_locked(plugin_id)
        threading.Thread(target=self._ask_loop, args=(key, request, pending), name="ask-variable", daemon=True).start()

    def on_value(self, plugin_id: str, payload: Mapping[str, Any]) -> None:
        """A plugin answered a ``get_variable`` request."""
        request = payload.get("request")
        with self._lock:
            pending = self._pending.get(request) if isinstance(request, str) else None
            if pending is not None and pending.plugin_id == plugin_id:
                del self._pending[str(request)]  # only the first answer counts
            else:
                pending = None
        if pending is None:
            logging.debug("[%s] dropped a variable value for an unknown request", plugin_id)
            return
        if payload.get("ok") is True:
            try:
                pending.value = value_text(payload.get("value"))
                pending.error = ""
            except ValueError as exc:
                pending.error = str(exc)
        else:
            pending.error = str(payload.get("error") or "the getter failed")
        pending.done.set()

    def plugin_stopped(self, plugin_id: str) -> None:
        """Wake every ask waiting on the plugin; they end without changing the store."""
        with self._lock:
            self._epochs[plugin_id] = self._epochs.get(plugin_id, 0) + 1
            self._release_locked(lambda pid: pid == plugin_id)

    def stop_all(self) -> None:
        """Server shutdown: wake every waiting ask and refuse new ones."""
        with self._lock:
            self._closed = True
            self._release_locked(lambda _pid: True)

    def _release_locked(self, matches: Callable[[str], bool]) -> None:
        for pending in self._pending.values():
            if matches(pending.plugin_id):
                pending.stopped = True
                pending.done.set()
        self._dirty = {key for key in self._dirty if not matches(key[0])}
        self._failing = {key for key in self._failing if not matches(key[0])}

    def push(self, plugin_id: str | None, changed: Mapping[str, str], removed: Sequence[str]) -> None:
        """Send ``variables_changed`` to one ready plugin, or to every ready plugin when plugin_id is None."""
        with self._push_lock:
            self._send(plugin_id, dict(changed), list(removed))

    def changed(self, names: frozenset[str]) -> None:
        """Push the current state of the changed names to every ready plugin (the store's change callback)."""
        with self._push_lock:
            values = self._store.snapshot()
            self._send(None, {n: values[n] for n in names if n in values}, sorted(n for n in names if n not in values))

    def send_snapshot(self, plugin_id: str) -> None:
        """Send every set value to one ready plugin."""
        with self._push_lock:
            self._send(plugin_id, self._store.snapshot(), [])

    def _send(self, plugin_id: str | None, changed: dict[str, str], removed: list[str]) -> None:
        message = Message("variables_changed", None, {"set": changed, "removed": removed})
        targets = [plugin_id] if plugin_id is not None else self._supervisor.plugin_ids()
        for target in targets:
            self._supervisor.send_if_ready(target, message)

    def _new_request_locked(self, plugin_id: str) -> tuple[str, _Pending]:
        request = uuid.uuid4().hex
        pending = _Pending(plugin_id, self._epochs.get(plugin_id, 0))
        self._pending[request] = pending
        return request, pending

    def _ask_loop(self, key: tuple[str, str], request: str, pending: _Pending) -> None:
        while True:
            self._ask_once(key, request, pending)
            with self._lock:
                if key not in self._dirty or self._closed:
                    self._inflight.discard(key)
                    return
                self._dirty.discard(key)
                request, pending = self._new_request_locked(key[0])

    def _ask_once(self, key: tuple[str, str], request: str, pending: _Pending) -> None:
        plugin_id, name = key
        try:
            if not pending.stopped:
                self._supervisor.send(plugin_id, Message("get_variable", None, {"request": request, "name": name}))
            answered = pending.done.wait(self._timeout)
        finally:
            with self._lock:
                self._pending.pop(request, None)
        if pending.stopped:
            logging.debug("[%s] variable %s: the plugin stopped before answering", plugin_id, name)
        elif not answered:
            self._failed(key, "the getter timed out")
        elif pending.error:
            self._failed(key, pending.error)
        else:
            with self._lock:
                self._failing.discard(key)
            self._store.set_value(plugin_id, name, pending.value, lambda: self._current(pending))

    def _current(self, pending: _Pending) -> bool:
        # Runs under the store lock: an answer from a process that stopped since the ask was sent is dropped.
        with self._lock:
            return not self._closed and self._epochs.get(pending.plugin_id, 0) == pending.epoch

    def _failed(self, key: tuple[str, str], error: str) -> None:
        with self._lock:
            first = key not in self._failing
            self._failing.add(key)
        level = logging.WARNING if first else logging.DEBUG
        logging.log(level, "[%s] variable %s: %s", key[0], key[1], error)
