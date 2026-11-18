"""Per-device key writer: one thread serialises static key images and deadline-scheduled animation frames."""

import itertools
import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from decker.animation.model import Animation

logger = logging.getLogger(__name__)

WriteFn = Callable[[int, bytes | None], None]

# Floor for any returned deadline, so a caller never gets a deadline at or before "now" and never spins.
_MIN_WAIT = 1e-6
# Absorbs float error when converting clock seconds to whole milliseconds at frame boundaries.
_MS_EPSILON = 1e-6


@dataclass
class _Slot:
    animation: Animation
    start: float
    fps_cap: int | None
    ends_ms: tuple[int, ...]
    deadline: float | None
    shown_index: int | None = None
    shown_data: bytes | None = None


@dataclass
class _StaticJob:
    key_index: int
    data: bytes | None
    done: threading.Event = field(default_factory=threading.Event)
    ok: bool = False


@dataclass(frozen=True)
class _FrameWrite:
    key_index: int
    slot: _Slot
    index: int


_Action = _StaticJob | _FrameWrite


class KeyWriter:
    """Serialises all image writes of one device: queued static writes first, then animation frames by deadline."""

    def __init__(self, write: WriteFn, clock: Callable[[], float] = time.monotonic) -> None:
        self._write: WriteFn = write
        self._clock: Callable[[], float] = clock
        self._condition: threading.Condition = threading.Condition()
        self._statics: deque[_StaticJob] = deque()
        self._slots: dict[int, _Slot] = {}
        self._in_flight: _StaticJob | None = None
        self._wake: bool = False
        self._closing: bool = False
        self._thread: threading.Thread | None = None

    def submit_static(self, key_index: int, data: bytes | None, timeout: float = 5.0) -> bool:
        """Write data (None blanks) to the key ahead of animations; True once written, False on timeout or error."""
        with self._condition:
            if self._closing:
                return False
            job = _StaticJob(key_index, data)
            self._statics.append(job)
            # A timed-out job still runs: it is the newest image for a key whose animation is already cancelled.
            self._slots.pop(key_index, None)
            self._notify()
        return job.done.wait(timeout) and job.ok

    def play(self, key_index: int, animation: Animation, fps_cap: int | None = None) -> None:
        """Start (or replace) the key's animation from now, capped at fps_cap frames per second if given."""
        now = self._clock()
        ends_ms = tuple(itertools.accumulate(frame.delay_ms for frame in animation.frames))
        with self._condition:
            self._slots[key_index] = _Slot(animation, now, fps_cap, ends_ms, deadline=now)
            self._notify()

    def stop(self, key_index: int) -> None:
        """Stop the key's animation, leaving its last written frame on the key."""
        with self._condition:
            self._slots.pop(key_index, None)
            self._notify()

    def stop_all(self) -> None:
        """Stop every animation."""
        with self._condition:
            self._slots.clear()
            self._notify()

    def step(self, now: float) -> float | None:
        """Perform at most one due write and return the clock time of the next deadline, or None when idle."""
        action = self._next_action(now)
        if action is not None:
            self._complete(action, self._perform(action), now)
        with self._condition:
            return self._next_deadline(now)

    def start(self) -> None:
        """Launch the daemon worker thread that drives step on the real clock."""
        with self._condition:
            if self._thread is not None or self._closing:
                return
            self._thread = threading.Thread(target=self._run, name="decker-key-writer", daemon=True)
            self._thread.start()

    def close(self, timeout: float = 2.0) -> None:
        """Stop the worker within timeout, abandoning a blocked write and failing pending static writes."""
        with self._condition:
            self._closing = True
            self._slots.clear()
            pending = list(self._statics)
            self._statics.clear()
            if self._in_flight is not None:
                pending.append(self._in_flight)
            self._notify()
            thread = self._thread
        for job in pending:
            job.done.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def _notify(self) -> None:
        self._wake = True
        self._condition.notify_all()

    def _run(self) -> None:
        while True:
            deadline = self.step(self._clock())
            with self._condition:
                if self._closing:
                    return
                if not self._wake:
                    self._condition.wait(None if deadline is None else max(0.0, deadline - self._clock()))
                self._wake = False

    def _next_action(self, now: float) -> _Action | None:
        with self._condition:
            if self._closing:
                return None
            if self._statics:
                self._in_flight = self._statics.popleft()
                return self._in_flight
            due = sorted(
                (slot.deadline, key_index)
                for key_index, slot in self._slots.items()
                if slot.deadline is not None and slot.deadline <= now
            )
            for _, key_index in due:
                slot = self._slots[key_index]
                index = slot.animation.frame_index_at(self._elapsed_ms(slot, now)) if slot.ends_ms[-1] > 0 else 0
                if index != slot.shown_index and slot.animation.frames[index].data != slot.shown_data:
                    return _FrameWrite(key_index, slot, index)
                slot.shown_index = index
                slot.deadline = self._deadline_after(slot, now, None)
            return None

    def _perform(self, action: _Action) -> bool:
        if isinstance(action, _StaticJob):
            key_index, data = action.key_index, action.data
        else:
            key_index, data = action.key_index, action.slot.animation.frames[action.index].data
        try:
            self._write(key_index, data)
        except Exception:  # pylint: disable=broad-exception-caught
            # The write callable is hardware I/O; any failure must leave the worker and other keys running.
            logger.exception("Key %d image write failed", key_index)
            return False
        return True

    def _complete(self, action: _Action, ok: bool, now: float) -> None:
        with self._condition:
            if isinstance(action, _StaticJob):
                self._in_flight = None
                if not action.done.is_set():
                    action.ok = ok
                    action.done.set()
                return
            slot = action.slot
            if self._slots.get(action.key_index) is not slot:
                return
            if not ok:
                del self._slots[action.key_index]
                return
            slot.shown_index = action.index
            slot.shown_data = slot.animation.frames[action.index].data
            slot.deadline = self._deadline_after(slot, now, now)

    def _next_deadline(self, now: float) -> float | None:
        if self._closing:
            return None
        if self._statics:
            return now + _MIN_WAIT
        deadlines = [slot.deadline for slot in self._slots.values() if slot.deadline is not None]
        if not deadlines:
            return None
        return max(min(deadlines), now + _MIN_WAIT)

    @staticmethod
    def _elapsed_ms(slot: _Slot, now: float) -> int:
        return math.floor((now - slot.start) * 1000 + _MS_EPSILON)

    def _deadline_after(self, slot: _Slot, now: float, written_at: float | None) -> float | None:
        total_ms = slot.ends_ms[-1]
        if total_ms <= 0 or len(slot.ends_ms) == 1:
            return None
        elapsed_ms = self._elapsed_ms(slot, now)
        index = slot.animation.frame_index_at(elapsed_ms)
        frame_change = slot.start + (elapsed_ms - elapsed_ms % total_ms + slot.ends_ms[index]) / 1000
        if written_at is not None and slot.fps_cap is not None:
            return max(frame_change, written_at + 1 / slot.fps_cap)
        return frame_change
