"""Starts, watches and restarts plugin processes on demand."""

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from decker.plugin.protocol import Message
from decker.plugin.runtime.process import PluginProcess

logger = logging.getLogger(__name__)

_MAX_QUEUED = 1000
_KILL_TIMEOUT_S = 1.0


@dataclass(frozen=True)
class SupervisorPolicy:
    """Tunable limits for the plugin supervisor."""

    idle_grace_s: float = 10.0
    ping_interval_s: float = 5.0
    ping_timeout_s: float = 10.0
    memory_limit: int = 256 * 1024 * 1024
    max_crashes: int = 3
    crash_window_s: float = 60.0
    backoff_s: tuple[float, ...] = (0.5, 2.0, 5.0)


@dataclass
class _Entry:  # pylint: disable=too-many-instance-attributes
    command: list[str]
    cwd: Path
    env: dict[str, str]
    hello: dict[str, Any]
    refs: int = 0
    process: PluginProcess | None = None
    generation: int = 0
    ready: bool = False
    killing: bool = False
    failed: bool = False
    idle_deadline: float | None = None
    restart_at: float | None = None
    last_ping: float = 0.0
    ping_sent_at: float | None = None
    crashes: list[float] = field(default_factory=list)
    queue: deque[Message] = field(default_factory=lambda: deque(maxlen=_MAX_QUEUED))


class PluginSupervisor:
    """Ref-counted lifecycle, readiness queueing, crash restarts and a ping/memory watchdog."""

    def __init__(
        self,
        policy: SupervisorPolicy,
        process_factory: Callable[..., PluginProcess],
        on_message: Callable[[str, Message], None],
        on_failed: Callable[[str, str], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._policy = policy
        self._factory = process_factory
        self._on_message = on_message
        self._on_failed = on_failed
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}
        self._closed = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def register(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, plugin_id: str, command: list[str], cwd: Path, env: dict[str, str], hello: dict[str, Any]
    ) -> None:
        """Make a plugin known to the supervisor; it is not started until acquired."""
        with self._lock:
            self._entries[plugin_id] = _Entry(command, cwd, env, hello)

    def unregister(self, plugin_id: str) -> None:
        """Forget a plugin and stop its process."""
        with self._lock:
            entry = self._entries.pop(plugin_id, None)
            process = self._detach(entry) if entry else None
        if process is not None:
            process.stop()

    def acquire(self, plugin_id: str) -> None:
        """Count one more live context; starts the process on first use."""
        with self._lock:
            entry = self._entries.get(plugin_id)
            if entry is None:
                return
            entry.refs += 1
            entry.idle_deadline = None
            if entry.process is None and entry.restart_at is None and not entry.failed and not self._closed:
                self._start_locked(plugin_id, entry)

    def release(self, plugin_id: str) -> None:
        """Drop one context; the process stops after the idle grace if none remain."""
        with self._lock:
            entry = self._entries.get(plugin_id)
            if entry is None or entry.refs == 0:
                return
            entry.refs -= 1
            if entry.refs == 0:
                entry.idle_deadline = self._clock() + self._policy.idle_grace_s
                entry.restart_at = None

    def send(self, plugin_id: str, message: Message) -> None:
        """Deliver a message now if the plugin is ready, otherwise queue it until it is."""
        with self._lock:
            entry = self._entries.get(plugin_id)
            if entry is None or entry.failed:
                return
            if entry.process is not None and entry.ready:
                entry.process.send(message)
            elif entry.refs > 0:
                entry.queue.append(message)

    def is_failed(self, plugin_id: str) -> bool:
        """True once a plugin crashed too often and was given up on."""
        with self._lock:
            entry = self._entries.get(plugin_id)
            return entry is not None and entry.failed

    def reset_failure(self, plugin_id: str) -> None:
        """Clear the failed state and start the plugin again if it is still in use."""
        with self._lock:
            entry = self._entries.get(plugin_id)
            if entry is None or not entry.failed:
                return
            entry.failed = False
            entry.crashes.clear()
            if entry.refs > 0 and entry.process is None:
                self._start_locked(plugin_id, entry)

    def start(self) -> None:
        """Start the 1 s watchdog thread."""
        with self._lock:
            self._closed = False
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._tick_loop, name="plugin-supervisor", daemon=True)
        self._thread.start()

    def stop_all(self) -> None:
        """Server shutdown: stop the watchdog and every plugin process."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)
        self._thread = None
        with self._lock:
            self._closed = True
            processes = [p for p in (self._detach(e) for e in self._entries.values()) if p is not None]
        self._stop_processes(processes)

    def tick(self, now: float) -> None:
        """Run idle, restart, memory and ping checks as of `now`."""
        to_stop: list[PluginProcess] = []
        to_kill: list[PluginProcess] = []
        with self._lock:
            if self._closed:
                return
            for plugin_id, entry in self._entries.items():
                self._tick_entry(plugin_id, entry, now, to_stop, to_kill)
        self._stop_processes(to_stop)
        for process in to_kill:
            process.stop(timeout=_KILL_TIMEOUT_S)

    def _tick_loop(self) -> None:
        while not self._stop_event.wait(1.0):
            try:
                self.tick(self._clock())
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("supervisor tick failed")

    def _tick_entry(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, plugin_id: str, entry: _Entry, now: float, to_stop: list[PluginProcess], to_kill: list[PluginProcess]
    ) -> None:
        if entry.process is None:
            if entry.restart_at is not None and now >= entry.restart_at and entry.refs > 0 and not entry.failed:
                self._start_locked(plugin_id, entry)
            return
        if entry.refs == 0:
            if entry.idle_deadline is not None and now >= entry.idle_deadline:
                process = self._detach(entry)
                if process is not None:
                    to_stop.append(process)
            return
        if entry.killing:
            return
        reason = self._watchdog_reason(entry, now)
        if reason is not None:
            logger.warning("[%s] killing plugin: %s", plugin_id, reason)
            entry.killing = True
            to_kill.append(entry.process)

    def _watchdog_reason(self, entry: _Entry, now: float) -> str | None:
        assert entry.process is not None
        rss = entry.process.rss_bytes()
        if rss is not None and rss > self._policy.memory_limit:
            return f"memory {rss} exceeds limit {self._policy.memory_limit}"
        if not entry.ready:
            return None
        if entry.ping_sent_at is not None:
            if now - entry.ping_sent_at > self._policy.ping_timeout_s:
                return "ping not answered"
        elif now - entry.last_ping >= self._policy.ping_interval_s:
            entry.ping_sent_at = now
            entry.last_ping = now
            entry.process.send(Message("ping"))
        return None

    def _start_locked(self, plugin_id: str, entry: _Entry) -> None:
        entry.generation += 1
        generation = entry.generation
        entry.ready = False
        entry.killing = False
        entry.restart_at = None
        entry.ping_sent_at = None
        process = self._factory(
            plugin_id,
            entry.command,
            entry.cwd,
            entry.env,
            lambda message: self._handle_message(plugin_id, generation, message),
            lambda code: self._handle_exit(plugin_id, generation, code),
        )
        entry.process = process
        try:
            process.start()
        except OSError as exc:
            logger.error("[%s] failed to start: %s", plugin_id, exc)
            entry.process = None
            entry.restart_at = self._clock() + self._policy.backoff_s[0]
            return
        process.send(Message("hello", payload=entry.hello))

    @staticmethod
    def _detach(entry: _Entry) -> PluginProcess | None:
        """Disown the process so its exit is not treated as a crash; the caller stops it."""
        process = entry.process
        entry.generation += 1
        entry.process = None
        entry.ready = False
        entry.restart_at = None
        entry.queue.clear()
        return process

    @staticmethod
    def _stop_processes(processes: list[PluginProcess]) -> None:
        threads = [threading.Thread(target=p.stop, daemon=True) for p in processes]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    def _handle_message(self, plugin_id: str, generation: int, message: Message) -> None:
        with self._lock:
            entry = self._entries.get(plugin_id)
            if entry is None or entry.generation != generation:
                return
            if message.event == "pong":
                entry.ping_sent_at = None
                return
            if message.event == "ready" and not entry.ready:
                entry.ready = True
                entry.last_ping = self._clock()
                self._flush(entry)
        self._on_message(plugin_id, message)

    @staticmethod
    def _flush(entry: _Entry) -> None:
        assert entry.process is not None
        while entry.queue:
            entry.process.send(entry.queue.popleft())

    def _handle_exit(self, plugin_id: str, generation: int, returncode: int) -> None:
        failure: str | None = None
        with self._lock:
            entry = self._entries.get(plugin_id)
            if entry is None or entry.generation != generation:
                return
            entry.process = None
            entry.ready = False
            if entry.refs == 0:
                return
            failure = self._record_crash(entry, returncode)
        if failure is not None:
            self._on_failed(plugin_id, failure)

    def _record_crash(self, entry: _Entry, returncode: int) -> str | None:
        now = self._clock()
        policy = self._policy
        entry.crashes = [t for t in entry.crashes if now - t < policy.crash_window_s]
        entry.crashes.append(now)
        if len(entry.crashes) >= policy.max_crashes:
            entry.failed = True
            entry.queue.clear()
            return f"crashed {len(entry.crashes)} times within {policy.crash_window_s:g}s (exit code {returncode})"
        index = min(len(entry.crashes) - 1, len(policy.backoff_s) - 1)
        entry.restart_at = now + policy.backoff_s[index]
        return None
