"""Connects the window watcher to the app rule engine and to clients, redacting titles for remote peers."""

import json
from dataclasses import asdict
from typing import Any

from decker.common.model import WindowInfo
from decker.server.server_context import ServerContext
from decker.server.window_watcher import WatcherTimings, WindowWatcher
from decker.server.windows.backend import WindowBackend

WINDOW_FOCUSED_EVENT = "window_focused"
WINDOW_DETECTION_CHANGED_EVENT = "window_detection_changed"
WINDOW_PICKED_EVENT = "window_picked"


def window_payload(window: WindowInfo | dict[str, Any] | None, loopback: bool) -> dict[str, Any] | None:
    """The window as a dict; titles may reveal private content, so only loopback peers get them."""
    if window is None:
        return None
    fields = asdict(window) if isinstance(window, WindowInfo) else dict(window)
    if not loopback:
        fields["title"] = ""
    return fields


def status_payload(status: dict[str, Any], loopback: bool) -> dict[str, Any]:
    """A watcher status with its window redacted for non-loopback peers."""
    return {**status, "window": window_payload(status["window"], loopback)}


def build_window_watcher(
    ctx: ServerContext, backend: WindowBackend, timings: WatcherTimings | None = None
) -> WindowWatcher:
    """A watcher feeding the context's rule engine and announcing focus and status changes on its event bus."""
    watcher: WindowWatcher | None = None

    def on_window(window: WindowInfo) -> None:
        if ctx.app_rule_engine is not None:
            ctx.app_rule_engine.on_focus(window)

    def push(_name: str, window: WindowInfo) -> None:
        ctx.event_bus.push_filtered(
            WINDOW_FOCUSED_EVENT, lambda loopback: json.dumps({"window": window_payload(window, loopback)})
        )

    def on_status() -> None:
        if watcher is not None:
            current = watcher.status()
            ctx.event_bus.push_filtered(
                WINDOW_DETECTION_CHANGED_EVENT, lambda loopback: json.dumps(status_payload(current, loopback))
            )

    watcher = WindowWatcher(backend, on_window, push, on_status, timings)
    return watcher
