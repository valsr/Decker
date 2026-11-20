"""Asks plugins for variable values off-thread and pushes variable changes to running plugins."""

import logging
import threading
import uuid
from collections.abc import Mapping, Sequence
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
    done: threading.Event = field(default_factory=threading.Event)
    stopped: bool = False
    value: str | None = None
    error: str = "no answer"


class VariableRunner:
    """Fills the VariableStore from plugin getters and keeps every ready plugin's copy of the variables current."""

    def __init__(self, supervisor: PluginSupervisor, store: VariableStore, timeout: float = DEFAULT_TIMEOUT_S) -> None:
        self._supervisor: PluginSupervisor = supervisor
        self._store: VariableStore = store
        self._timeout: float = timeout
        self._lock: threading.Lock = threading.Lock()
        self._push_lock: threading.Lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}

    def ask(self, plugin_id: str, name: str) -> None:
        """Ask the plugin for a value without waiting; the answer lands in the store."""
        threading.Thread(target=self._ask, args=(plugin_id, name), name="ask-variable", daemon=True).start()

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
            waiting = [p for p in self._pending.values() if p.plugin_id == plugin_id]
        for pending in waiting:
            pending.stopped = True
            pending.done.set()

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

    def _ask(self, plugin_id: str, name: str) -> None:
        request = uuid.uuid4().hex
        pending = _Pending(plugin_id)
        with self._lock:
            self._pending[request] = pending
        try:
            self._supervisor.send(plugin_id, Message("get_variable", None, {"request": request, "name": name}))
            answered = pending.done.wait(self._timeout)
        finally:
            with self._lock:
                self._pending.pop(request, None)
        if pending.stopped:
            logging.debug("[%s] variable %s: the plugin stopped before answering", plugin_id, name)
        elif not answered:
            logging.warning("[%s] variable %s: the getter timed out", plugin_id, name)
        elif pending.error:
            logging.warning("[%s] variable %s: %s", plugin_id, name, pending.error)
        else:
            self._store.set_value(plugin_id, name, pending.value)
