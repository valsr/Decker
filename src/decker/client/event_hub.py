"""Thread-safe handoff of application events from background workers to the Qt main thread."""

from queue import SimpleQueue

from decker.client.events import AppEvent


class EventHub:
    """Singleton queue bridging worker threads and the main-thread event loop.

    Workers call push() from any thread. MainWindow drains the queue on the main
    thread via a periodic QTimer — drain() must not be called from a worker thread.
    """

    _instance: "EventHub | None" = None

    def __init__(self) -> None:
        self._queue: SimpleQueue[AppEvent] = SimpleQueue()

    @classmethod
    def get(cls) -> "EventHub":
        """Return the process-wide EventHub instance, creating it on first use."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def push(self, event: AppEvent) -> None:
        """Enqueue an event. Safe to call from any thread."""
        self._queue.put(event)

    def drain(self) -> list[AppEvent]:
        """Return and remove all currently queued events, in order. Main thread only."""
        events: list[AppEvent] = []
        while not self._queue.empty():
            events.append(self._queue.get())
        return events
