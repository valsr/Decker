"""Per-device key writer: one thread serialises static key images and deadline-scheduled animation frames."""

import itertools
import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from decker.animation.controller import (
    LADDER,
    LAG_LIMIT_S,
    STEP_DOWN_BUSY,
    Demand,
    Level,
    LevelController,
    LoadSample,
)
from decker.animation.encode import KeyFormat
from decker.animation.load import LoadMonitor
from decker.animation.model import Animation, AnimationSpec

logger = logging.getLogger(__name__)

WriteFn = Callable[[int, bytes | None], None]

# How often a pending factory build (first frames or a new quality) is polled; keeps step from spinning.
POLL_S: float = 0.050
TICK_S: float = 1.0
LAG_SUSTAIN_S: float = 1.0
SHORT_WINDOW_S: float = 5.0
LONG_WINDOW_S: float = 20.0
# A key-set change that lowers the cost is planned once the set has been stable this long (page switches).
REPLAN_SETTLE_S: float = 0.250

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
    spec: AnimationSpec | None = None


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
    deadline: float


_Action = _StaticJob | _FrameWrite


class FrameSource(Protocol):
    """Non-blocking source of encoded animations, such as AnimationFactory."""

    def frames_for(self, spec: AnimationSpec, fmt: KeyFormat, quality: int) -> Animation | None:
        """Return the animation for spec in fmt at quality, or None while it is not available (starts a build)."""

    def cached_frames(self, spec: AnimationSpec, fmt: KeyFormat, quality: int) -> Animation | None:
        """Return the animation only if it is already built; never starts a build."""


@dataclass(frozen=True)
class AdaptiveConfig:
    """Optional parts that let a KeyWriter adapt quality and frame rate to its measured write load."""

    controller: LevelController | None = None
    monitor: LoadMonitor | None = None
    factory: FrameSource | None = None
    fmt: KeyFormat | None = None


def _ends_ms(animation: Animation) -> tuple[int, ...]:
    return tuple(itertools.accumulate(frame.delay_ms for frame in animation.frames))


def _new_slot(animation: Animation, now: float, fps_cap: int | None, spec: AnimationSpec | None = None) -> _Slot:
    return _Slot(animation, now, fps_cap, _ends_ms(animation), deadline=now, spec=spec)


def _native_fps(animation: Animation) -> float:
    total_ms = animation.total_ms
    if total_ms <= 0 or len(animation.frames) < 2:
        return 0.0
    return 1000 * len(animation.frames) / total_ms


def _mean_reports(animation: Animation, quality: int) -> float:
    estimate = animation.reports_by_quality.get(quality)
    if estimate is not None:
        return estimate
    return sum(frame.reports for frame in animation.frames) / len(animation.frames)


class _Adapter:
    """Level control for one writer; every method is called with the writer's lock held."""

    def __init__(self, config: AdaptiveConfig) -> None:
        self.controller: LevelController | None = config.controller
        self.monitor: LoadMonitor = config.monitor if config.monitor is not None else LoadMonitor()
        self.factory: FrameSource | None = config.factory
        self.fmt: KeyFormat | None = config.fmt
        # Keys whose animation waits for its first frames from the factory.
        self.waiting: dict[int, AnimationSpec] = {}
        self.next_tick: float | None = None
        self.next_poll: float = -math.inf
        self.replanned_at: float | None = None
        # Clock time of the latest key-set change not yet re-planned, and the cost the current plan was made for.
        self.changed_at: float | None = None
        self.planned_cost: float = 0.0

    @property
    def level(self) -> Level:
        """The controller's level, or the top level without a controller."""
        return self.controller.level if self.controller is not None else LADDER[0]

    def cap_for(self, animation: Animation, requested: int | None) -> int | None:
        """The level's frame-rate cap if it is below the animation's native rate; requested without a controller."""
        if self.controller is None:
            return requested
        cap = self.controller.level.fps_cap
        return cap if cap is not None and cap < _native_fps(animation) else None

    def demand(self, slots: dict[int, _Slot]) -> Demand:
        """Reports per second the playing slots need at a level (mean reports per frame x capped frame rate)."""
        animations = [slot.animation for slot in slots.values()]

        def reports_per_second(level: Level) -> float:
            total = 0.0
            for animation in animations:
                native = _native_fps(animation)
                fps = native if level.fps_cap is None else min(native, level.fps_cap)
                total += _mean_reports(animation, level.quality) * fps
            return total

        return reports_per_second

    def changed(self, now: float) -> None:
        """Note a key-set change; the worker re-plans on its next step (see replan_if_due)."""
        self.changed_at = now

    def poll_due(self, now: float) -> bool:
        """True (and the next poll scheduled) when the factory may be polled now."""
        if now < self.next_poll or self.factory is None or self.fmt is None:
            return False
        self.next_poll = now + POLL_S
        return True

    def replan_if_due(self, slots: dict[int, _Slot], now: float) -> None:
        """Re-plan a pending key-set change: at once if it costs more, after REPLAN_SETTLE_S if it costs less."""
        if self.changed_at is None or self.controller is None:
            self.changed_at = None
            return
        # A page switch empties keys one by one before refilling them; planning on the partial set would raise the
        # level and drop it straight back. A costlier set is planned at once so it cannot overload the deck.
        cost = self.demand(slots)(self.level)
        if cost <= self.planned_cost * (1 + 1e-9) and now < self.changed_at + REPLAN_SETTLE_S:
            return
        self.changed_at = None
        self.replanned_at = now
        old = self.controller.level
        new = self.controller.replan(self.demand(slots), self.monitor.seconds_per_report)
        self.planned_cost = self.demand(slots)(new)
        self._changed(slots, (old, new), now, "animated keys changed")

    def tick(self, slots: dict[int, _Slot], now: float) -> None:
        """Feed the measured load to the controller, at most once per TICK_S while anything is animated."""
        if self.controller is None or not (slots or self.waiting):
            return
        if self.next_tick is None:
            self.next_tick = now + TICK_S
        if now < self.next_tick:
            return
        self.next_tick = now + TICK_S
        monitor = self.monitor
        lagging = monitor.lag_over(now, LAG_LIMIT_S, LAG_SUSTAIN_S)
        busy_20s = monitor.busy_fraction(now, LONG_WINDOW_S)
        if self.replanned_at is not None and now - self.replanned_at < LONG_WINDOW_S:
            # The long window still measures the previous key set, so its step-up projection would be wrong.
            busy_20s = 1.0
        sample = LoadSample(
            now,
            monitor.busy_fraction(now, SHORT_WINDOW_S),
            busy_20s,
            monitor.last_lag_s if lagging else 0.0,
        )
        old = self.controller.level
        new = self.controller.tick(sample, self.demand(slots), monitor.seconds_per_report)
        # Mirrors the controller's step-down rules; any other change is a step up.
        if sample.busy_5s > STEP_DOWN_BUSY:
            cause = "overloaded"
        elif sample.lag_s > LAG_LIMIT_S:
            cause = "frames lagging"
        else:
            cause = "load dropped"
        if new != old and self.changed_at is None:
            self.planned_cost = self.demand(slots)(new)
        self._changed(slots, (old, new), now, cause)

    def start_waiting(self, slots: dict[int, _Slot], now: float) -> None:
        """Start each waiting animation with any quality already built; otherwise ask for the level's quality."""
        if self.factory is None or self.fmt is None:
            return
        level_quality = self.level.quality
        for key_index, spec in list(self.waiting.items()):
            animation = self._any_cached(spec, level_quality) or self.factory.frames_for(spec, self.fmt, level_quality)
            if animation is not None:
                del self.waiting[key_index]
                slots[key_index] = _new_slot(animation, now, self.cap_for(animation, None), spec)
                self.changed(now)

    def switch_qualities(self, slots: dict[int, _Slot], now: float) -> None:
        """Move playing slots to the level's quality once the factory has it; until then they keep their frames."""
        if self.factory is None or self.fmt is None:
            return
        quality = self.level.quality
        for slot in slots.values():
            if slot.spec is not None and slot.animation.quality != quality:
                animation = self.factory.frames_for(slot.spec, self.fmt, quality)
                if animation is not None:
                    self._switch(slot, animation, now)

    def deadlines(self, slots: dict[int, _Slot]) -> list[float]:
        """Clock times at which tick, a pending re-plan or a poll has work to do."""
        wanted: list[float] = []
        if self.controller is not None and self.next_tick is not None and (slots or self.waiting):
            wanted.append(self.next_tick)
        if self.changed_at is not None:
            wanted.append(self.changed_at + REPLAN_SETTLE_S)
        if self.waiting or self._mismatched(slots):
            wanted.append(self.next_poll)
        return wanted

    def record(self, action: _Action, started: float, ended: float) -> None:
        """Record a write's busy time, its reports and, for a frame, how late it was."""
        reports = 0
        if isinstance(action, _FrameWrite):
            reports = action.slot.animation.frames[action.index].reports
            self.monitor.record_lag(ended, max(0.0, ended - action.deadline))
        elif action.data is not None and self.fmt is not None:
            reports = math.ceil(len(action.data) / self.fmt.report_payload)
        self.monitor.record_write(ended, max(0.0, ended - started), reports)

    def _any_cached(self, spec: AnimationSpec, preferred: int) -> Animation | None:
        if self.factory is None or self.fmt is None:
            return None
        for quality in sorted({level.quality for level in LADDER}, key=lambda q: (abs(q - preferred), -q)):
            animation = self.factory.cached_frames(spec, self.fmt, quality)
            if animation is not None:
                return animation
        return None

    def _mismatched(self, slots: dict[int, _Slot]) -> bool:
        quality = self.level.quality
        return any(slot.spec is not None and slot.animation.quality != quality for slot in slots.values())

    def _switch(self, slot: _Slot, animation: Animation, now: float) -> None:
        # Same start time: the new quality continues at the same elapsed time; its next frame boundary writes it.
        slot.animation = animation
        slot.ends_ms = _ends_ms(animation)
        slot.fps_cap = self.cap_for(animation, None)
        if slot.deadline is None:
            slot.deadline = now
            slot.shown_index = None

    def _changed(self, slots: dict[int, _Slot], levels: tuple[Level, Level], now: float, cause: str) -> None:
        old, new = levels
        if new == old:
            return
        logger.info(
            "Animation level %s -> %s: %s (busy %.0f%% over %.0f s)",
            old,
            new,
            cause,
            100 * self.monitor.busy_fraction(now, SHORT_WINDOW_S),
            SHORT_WINDOW_S,
        )
        for slot in slots.values():
            slot.fps_cap = self.cap_for(slot.animation, None)
        self.next_poll = -math.inf


class KeyWriter:  # pylint: disable=too-many-instance-attributes
    """Serialises all image writes of one device: queued static writes first, then animation frames by deadline."""

    def __init__(
        self, write: WriteFn, clock: Callable[[], float] = time.monotonic, *, adaptive: AdaptiveConfig | None = None
    ) -> None:
        self._write: WriteFn = write
        self._clock: Callable[[], float] = clock
        self._adapter: _Adapter = _Adapter(adaptive if adaptive is not None else AdaptiveConfig())
        self._condition: threading.Condition = threading.Condition()
        self._statics: deque[_StaticJob] = deque()
        self._slots: dict[int, _Slot] = {}
        self._in_flight: _StaticJob | None = None
        self._wake: bool = False
        self._closing: bool = False
        self._thread: threading.Thread | None = None
        # Key whose slot step is evaluating; the worker drops that slot if step raises.
        self._processing_key: int | None = None
        # True while an animation frame is being written (outside the lock); stop_all can wait for it.
        self._frame_in_flight: bool = False

    def submit_static(self, key_index: int, data: bytes | None, timeout: float = 5.0) -> bool:
        """Write data (None blanks) to the key ahead of animations; True once written, False on timeout or error.

        False means not confirmed in time; the image may still be written later.
        """
        with self._condition:
            if self._closing:
                return False
            job = _StaticJob(key_index, data)
            self._statics.append(job)
            # A timed-out job still runs: it is the newest image for a key whose animation is already cancelled.
            self._remove(key_index)
            self._notify()
        return job.done.wait(timeout) and job.ok

    def play(self, key_index: int, animation: Animation, fps_cap: int | None = None) -> None:
        """Start (or replace) the key's fixed animation from now, capped at fps_cap frames per second if given.

        With a level controller configured the level's cap applies instead of fps_cap.
        Raises ValueError if the animation has no frames or fps_cap is not None and not positive.
        """
        if not animation.frames:
            raise ValueError("animation has no frames")
        if fps_cap is not None and fps_cap <= 0:
            raise ValueError(f"fps_cap must be positive, got {fps_cap}")
        now = self._clock()
        with self._condition:
            self._adapter.waiting.pop(key_index, None)
            self._slots[key_index] = _new_slot(animation, now, self._adapter.cap_for(animation, fps_cap))
            self._adapter.changed(now)
            self._notify()

    def play_spec(self, key_index: int, spec: AnimationSpec, poster_written: bool = True) -> None:
        """Animate the key with spec at the current level's quality, starting once the factory has its frames.

        poster_written False keeps the key's current animation playing until then (no poster replaced it).
        Raises ValueError if the writer has no factory or key format.
        """
        adapter = self._adapter
        if adapter.factory is None or adapter.fmt is None:
            raise ValueError("play_spec needs an AdaptiveConfig with a factory and a key format")
        with self._condition:
            if poster_written:
                self._remove(key_index)
            adapter.waiting[key_index] = spec
            adapter.next_poll = -math.inf
            self._notify()

    @property
    def level(self) -> Level:
        """The current quality and frame-rate level (the top level when no controller is configured)."""
        with self._condition:
            return self._adapter.level

    def stop(self, key_index: int) -> None:
        """Stop the key's animation, leaving its last written frame on the key."""
        with self._condition:
            self._remove(key_index)
            self._notify()

    def stop_all(self, wait: float = 0.0) -> None:
        """Stop every animation; with wait > 0 also wait up to wait seconds for a frame write already under way."""
        with self._condition:
            had_slots = bool(self._slots)
            self._slots.clear()
            self._adapter.waiting.clear()
            if had_slots:
                self._adapter.changed(self._clock())
            self._notify()
            if wait > 0 and threading.current_thread() is not self._thread:
                self._condition.wait_for(lambda: not self._frame_in_flight or self._closing, wait)

    def step(self, now: float) -> float | None:
        """Perform at most one due write and return the clock time of the next deadline, or None when idle."""
        self._adapt(now)
        action = self._next_action(now)
        if action is not None:
            try:
                started = self._clock()
                ok = self._perform(action)
                self._complete(action, ok, now, (started, self._clock()))
            finally:
                with self._condition:
                    self._frame_in_flight = False
                    self._condition.notify_all()
        with self._condition:
            self._processing_key = None
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
            self._adapter.waiting.clear()
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

    def _remove(self, key_index: int) -> None:
        self._adapter.waiting.pop(key_index, None)
        self._drop_slot(key_index)

    def _drop_slot(self, key_index: int) -> None:
        if self._slots.pop(key_index, None) is not None:
            self._adapter.changed(self._clock())

    def _adapt(self, now: float) -> None:
        with self._condition:
            if self._closing:
                return
            adapter = self._adapter
            polling = adapter.poll_due(now)
            if polling and adapter.waiting:
                adapter.start_waiting(self._slots, now)
            # Re-plan before switching qualities, so a slot is never moved to a quality the new plan will not use.
            adapter.replan_if_due(self._slots, now)
            if polling:
                adapter.switch_qualities(self._slots, now)
            adapter.tick(self._slots, now)

    def _notify(self) -> None:
        self._wake = True
        self._condition.notify_all()

    def _run(self) -> None:
        while True:
            try:
                deadline = self.step(self._clock())
            except Exception:  # pylint: disable=broad-exception-caught
                # A scheduling bug or bad animation must not kill the worker: static writes and other keys depend on it.
                deadline = self._drop_failing_slot()
            with self._condition:
                if self._closing:
                    return
                if not self._wake:
                    self._condition.wait(None if deadline is None else max(0.0, deadline - self._clock()))
                self._wake = False

    def _drop_failing_slot(self) -> float | None:
        with self._condition:
            key_index, self._processing_key = self._processing_key, None
            if key_index is None:
                logger.exception("Key writer step failed; waiting for the next change")
                return None
            logger.exception("Key %d animation failed; dropping it", key_index)
            self._drop_slot(key_index)
            return self._clock()

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
                self._processing_key = key_index
                slot = self._slots[key_index]
                index = slot.animation.frame_index_at(self._elapsed_ms(slot, now)) if slot.ends_ms[-1] > 0 else 0
                if index != slot.shown_index and slot.animation.frames[index].data != slot.shown_data:
                    self._frame_in_flight = True
                    return _FrameWrite(key_index, slot, index, now if slot.deadline is None else slot.deadline)
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

    def _complete(self, action: _Action, ok: bool, now: float, span: tuple[float, float]) -> None:
        with self._condition:
            self._adapter.record(action, *span)
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
                self._drop_slot(action.key_index)
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
        deadlines.extend(self._adapter.deadlines(self._slots))
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
