"""Singleton event bus: thread-safe push from any thread, synchronous dispatch on the main thread."""

from __future__ import annotations

from collections import defaultdict
from queue import SimpleQueue
from typing import Callable, TypeVar

from decker.client.events import AppEvent

_T = TypeVar("_T")


class EventManager:
    """Central event bus connecting all client components.

    Push from any thread via push(); all dispatch is synchronous on the main thread.
    MainWindow's QTimer calls drain_and_dispatch() every 16 ms to flush queued events.
    Components can also call emit() directly for immediate in-thread dispatch (e.g., view lifecycle).

    Handlers receive a typed event and return True to stop propagation, or None/False to continue.
    Registration order determines dispatch order — register high-priority handlers first.
    """

    _instance: EventManager | None = None

    def __init__(self) -> None:
        self._queue: SimpleQueue[AppEvent] = SimpleQueue()
        self._subscribers: dict[type, list[Callable[[AppEvent], bool | None]]] = defaultdict(list)

    @classmethod
    def get(cls) -> EventManager:
        """Return the process-wide singleton, creating it on first use."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Discard the singleton and all subscriptions. Test use only."""
        cls._instance = None

    def subscribe(self, event_type: type[_T], handler: Callable[[_T], bool | None]) -> Callable[[_T], bool | None]:
        """Register a handler for events of the given type.

        Handlers are called in registration order. Return True from a handler to stop propagation.
        Returns the handler so callers can store a reference for later unsubscription.
        """
        self._subscribers[event_type].append(handler)  # type: ignore[arg-type]
        return handler

    def unsubscribe(self, event_type: type[_T], handler: Callable[[_T], bool | None]) -> None:
        """Remove a previously registered handler. No-op if not found."""
        handlers = self._subscribers.get(event_type)
        if handlers is None:
            return
        try:
            handlers.remove(handler)  # type: ignore[arg-type]
        except ValueError:
            pass

    def push(self, event: AppEvent) -> None:
        """Enqueue an event from any thread. Dispatched on the next drain_and_dispatch() call."""
        self._queue.put(event)

    def emit(self, event: AppEvent) -> bool:
        """Dispatch an event synchronously to all registered handlers. Main-thread only.

        Returns True if a handler consumed the event and stopped propagation.
        """
        for handler in list(self._subscribers.get(type(event), [])):
            if handler(event):
                return True
        return False

    def drain(self) -> list[AppEvent]:
        """Return and remove all currently queued events without dispatching them.

        Useful in tests to inspect pushed events without triggering side effects.
        """
        events: list[AppEvent] = []
        while not self._queue.empty():
            events.append(self._queue.get())
        return events

    def drain_and_dispatch(self) -> None:
        """Drain the thread-safe queue and emit each event. Call from the main thread via QTimer."""
        while not self._queue.empty():
            self.emit(self._queue.get())
