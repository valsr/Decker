"""The stdio event loop: decode server events, dispatch handlers, write replies."""

import json
import sys
import threading
from collections import deque
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any, BinaryIO, TypeVar

from ._context import MAX_LINE_BYTES, ActionContext, encode_line
from ._gestures import Gesture

WORKERS = 4
PLUGIN_WIDE = "\0plugin"  # queue key for context-less events

_REGISTRY: dict[str, type["DeckerPlugin"]] = {}
_T = TypeVar("_T", bound=type["DeckerPlugin"])


class DeckerPlugin:
    """Base class for actions; override the handlers you need."""

    def on_will_appear(self, ctx: ActionContext) -> None:
        """The key became visible."""

    def on_will_disappear(self, ctx: ActionContext) -> None:
        """The key is no longer visible."""

    def on_key_down(self, ctx: ActionContext) -> None:
        """Raw key down."""

    def on_key_up(self, ctx: ActionContext) -> None:
        """Raw key up."""

    def on_press(self, ctx: ActionContext) -> None:
        """Press gesture."""

    def on_double_press(self, ctx: ActionContext) -> None:
        """Double-press gesture."""

    def on_long_press(self, ctx: ActionContext) -> None:
        """Long-press gesture."""

    def on_settings_changed(self, ctx: ActionContext) -> None:
        """The key's settings changed."""

    def on_global_settings_changed(self, ctx: ActionContext) -> None:
        """The plugin's global settings changed."""

    def gestures(self, settings: dict[str, Any]) -> frozenset[Gesture] | None:  # pylint: disable=unused-argument
        """Gestures for this key; None keeps the manifest's list."""
        return None


def action(action_id: str) -> "Callable[[_T], _T]":
    """Register a DeckerPlugin subclass under a manifest action id."""

    def decorate(cls: _T) -> _T:
        _REGISTRY[action_id] = cls
        return cls

    return decorate


def registered_actions() -> dict[str, type[DeckerPlugin]]:
    """The actions registered so far with @action."""
    return dict(_REGISTRY)


_HANDLERS = {
    "will_appear": "on_will_appear",
    "will_disappear": "on_will_disappear",
    "key_down": "on_key_down",
    "key_up": "on_key_up",
    "press": "on_press",
    "double_press": "on_double_press",
    "long_press": "on_long_press",
    "settings_changed": "on_settings_changed",
    "global_settings_changed": "on_global_settings_changed",
}


def _warn(text: str) -> None:
    print(f"decker_plugin_sdk: {text}", file=sys.stderr, flush=True)


class _Runtime:  # pylint: disable=too-many-instance-attributes
    def __init__(self, actions: Mapping[str, type[DeckerPlugin]], stdout: BinaryIO) -> None:
        self._actions = actions
        self._stdout = stdout
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="decker-sdk")
        self._queues: dict[str, deque[dict[str, Any]]] = {}
        self._contexts: dict[str, tuple[DeckerPlugin, ActionContext]] = {}
        self._global_settings: dict[str, Any] = {}

    def send(self, event: str, context: str | None = None, payload: dict[str, Any] | None = None) -> None:
        line = encode_line(event, context, payload)
        with self._write_lock:
            try:
                self._stdout.write(line)
                self._stdout.flush()
            except (BrokenPipeError, ValueError, OSError):
                pass  # server went away; the reader will see EOF

    def log_error(self, message: str) -> None:
        _warn(message)
        self.send("log", None, {"level": "error", "message": message})

    def serve(self, stdin: BinaryIO) -> int:
        try:
            while True:
                line = stdin.readline(MAX_LINE_BYTES + 1)
                if not line:
                    return 0
                if not line.strip():
                    continue
                if not self._handle_line(line):
                    return 0
        finally:
            self._pool.shutdown(wait=False, cancel_futures=True)

    def _handle_line(self, line: bytes) -> bool:
        """Process one line; False means stop the loop."""
        try:
            if len(line) > MAX_LINE_BYTES:
                raise ValueError("line too long")
            data = json.loads(line.decode("utf-8"))
        except (ValueError, RecursionError) as exc:  # includes JSON and Unicode decode errors
            _warn(f"skipping malformed line: {exc}")
            return True
        event = data.get("event") if isinstance(data, dict) else None
        context = data.get("context") if isinstance(data, dict) else None
        payload = data.get("payload") if isinstance(data, dict) else None
        if not isinstance(event, str) or not isinstance(payload or {}, dict) or not isinstance(context or "", str):
            _warn("skipping message with invalid event/context/payload")
            return True
        payload = payload or {}
        if event == "shutdown":
            return False
        if event == "ping":
            self.send("pong", context)
        elif event == "hello":
            self._on_hello(payload)
        elif event == "global_settings_changed":
            self._on_global_settings(payload)
        elif event in _HANDLERS:
            self._enqueue(context or PLUGIN_WIDE, {"event": event, "context": context, "payload": payload})
        return True

    def _on_hello(self, payload: dict[str, Any]) -> None:
        settings = payload.get("global_settings")
        self._global_settings = settings if isinstance(settings, dict) else {}
        self.send("ready")

    def _enqueue(self, key: str, item: dict[str, Any]) -> None:
        with self._state_lock:
            queue = self._queues.get(key)
            if queue is not None:
                queue.append(item)
                return
            self._queues[key] = deque([item])
        try:
            self._pool.submit(self._drain, key)
        except RuntimeError:
            pass  # pool already shut down

    def _drain(self, key: str) -> None:
        while True:
            with self._state_lock:
                queue = self._queues[key]
                if not queue:
                    del self._queues[key]
                    return
                item = queue.popleft()
            try:
                self._dispatch(item)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self.log_error(f"handler for {item['event']} failed: {type(exc).__name__}: {exc}")

    def _dispatch(self, item: dict[str, Any]) -> None:
        event, context, payload = item["event"], item["context"], item["payload"]
        if context is None:
            return
        if event == "will_appear":
            self._create(context, payload)
        entry = self._contexts.get(context)
        if entry is None:
            _warn(f"ignoring {event} for unknown context {context}")
            return
        plugin, ctx = entry
        if event == "settings_changed":
            ctx.settings = self._dict(payload.get("settings"))
        elif event in ("key_down", "key_up", "press", "double_press", "long_press"):
            ctx.state = payload.get("state", ctx.state) if isinstance(payload.get("state"), int) else ctx.state
        try:
            getattr(plugin, _HANDLERS[event])(ctx)
        finally:
            if event == "will_disappear":
                self._contexts.pop(context, None)
        if event in ("will_appear", "settings_changed"):
            self._send_gestures(plugin, ctx)

    @staticmethod
    def _dict(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    def _create(self, context: str, payload: dict[str, Any]) -> None:
        action_id = payload.get("action")
        cls = self._actions.get(action_id) if isinstance(action_id, str) else None
        if cls is None:
            _warn(f"no action registered for {action_id!r}")
            return
        key = self._dict(payload.get("key"))
        state = payload.get("state")
        ctx = ActionContext(
            context=context,
            action=str(action_id),
            device=str(payload.get("device", "")),
            key_index=int(key.get("index", 0)),
            column=int(key.get("column", 0)),
            row=int(key.get("row", 0)),
            settings=self._dict(payload.get("settings")),
            global_settings=self._global_settings,
            state=state if isinstance(state, int) else 0,
            _send=self.send,
        )
        self._contexts[context] = (cls(), ctx)

    def _on_global_settings(self, payload: dict[str, Any]) -> None:
        settings = self._dict(payload.get("global_settings", payload.get("settings")))
        self._global_settings = settings
        for context, (_, ctx) in list(self._contexts.items()):
            ctx.global_settings = settings
            self._enqueue(context, {"event": "global_settings_changed", "context": context, "payload": payload})

    def _send_gestures(self, plugin: DeckerPlugin, ctx: ActionContext) -> None:
        gestures = plugin.gestures(ctx.settings)
        if gestures is not None:
            self.send("set_gestures", ctx.context, {"gestures": sorted(str(g) for g in gestures)})


def run(actions: Mapping[str, type[DeckerPlugin]], stdin: BinaryIO, stdout: BinaryIO) -> int:
    """Serve the protocol on the given streams until shutdown or EOF; returns the exit code."""
    return _Runtime(actions, stdout).serve(stdin)
