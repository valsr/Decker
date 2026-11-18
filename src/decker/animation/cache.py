"""A thread-safe LRU cache bounded by the total byte size of its entries."""

import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Build:
    done: threading.Event = field(default_factory=threading.Event)
    waiters: int = 0
    value: Any = None
    error: BaseException | None = None


class SizedLru:
    """LRU cache that evicts least recently used entries to stay within max_bytes."""

    def __init__(self, max_bytes: int) -> None:
        self._max_bytes: int = max_bytes
        self._entries: OrderedDict[Hashable, tuple[Any, int]] = OrderedDict()
        self._size: int = 0
        self._lock: threading.Lock = threading.Lock()
        self._builds: dict[Hashable, _Build] = {}

    @property
    def size_bytes(self) -> int:
        """Total size of the stored entries."""
        with self._lock:
            return self._size

    def get(self, key: Hashable) -> Any | None:
        """Return the cached value (marking it recently used), or None."""
        with self._lock:
            return self._get_locked(key)

    def put(self, key: Hashable, value: Any, size: int) -> None:
        """Store value, evicting old entries; a value larger than the budget is not stored."""
        with self._lock:
            self._put_locked(key, value, size)

    def waiters(self, key: Hashable) -> int:
        """Number of callers waiting on an in-flight build of key."""
        with self._lock:
            build = self._builds.get(key)
            return build.waiters if build is not None else 0

    def get_or_build(self, key: Hashable, build: Callable[[], tuple[Any, int]]) -> Any:
        """Return the cached value or build it once; concurrent callers for key wait for that build.

        If the build raises, every caller waiting on it gets the same exception and nothing is cached,
        so the next call builds again.
        """
        with self._lock:
            if key in self._entries:
                return self._get_locked(key)
            pending = self._builds.get(key)
            if pending is None:
                pending = self._builds[key] = _Build()
                owner = True
            else:
                pending.waiters += 1
                owner = False
        if owner:
            self._run_build(key, pending, build)
        else:
            pending.done.wait()
        if pending.error is not None:
            raise pending.error
        return pending.value

    def _run_build(self, key: Hashable, pending: _Build, build: Callable[[], tuple[Any, int]]) -> None:
        try:
            pending.value, size = build()
            with self._lock:
                self._put_locked(key, pending.value, size)
        except BaseException as exc:  # pylint: disable=broad-exception-caught
            pending.error = exc
        finally:
            with self._lock:
                del self._builds[key]
            pending.done.set()

    def _get_locked(self, key: Hashable) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        self._entries.move_to_end(key)
        return entry[0]

    def _put_locked(self, key: Hashable, value: Any, size: int) -> None:
        old = self._entries.pop(key, None)
        if old is not None:
            self._size -= old[1]
        if size > self._max_bytes:
            return
        self._entries[key] = (value, size)
        self._size += size
        while self._size > self._max_bytes:
            _, (_, evicted) = self._entries.popitem(last=False)
            self._size -= evicted
