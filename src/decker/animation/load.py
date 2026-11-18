"""Measured write load of one device: busy time in 1 s buckets, frame lag and the cost of one HID report."""

import math
from collections import deque

SEED_SECONDS_PER_REPORT: float = 0.00025
# Weight of each new write in the seconds-per-report average; about the last 20 writes dominate.
EWMA_ALPHA: float = 0.05
# Busy buckets and lag samples older than this are dropped; windows and for_s must not exceed it.
HISTORY_S: float = 60.0


class LoadMonitor:
    """Sliding record of write busy time and frame lag; not thread-safe (the key writer calls it under its lock)."""

    def __init__(self, seed_seconds_per_report: float = SEED_SECONDS_PER_REPORT) -> None:
        self._seconds_per_report: float = seed_seconds_per_report
        self._buckets: dict[int, float] = {}
        self._lags: deque[tuple[float, float]] = deque()

    @property
    def seconds_per_report(self) -> float:
        """Moving average of measured seconds per HID report."""
        return self._seconds_per_report

    @property
    def last_lag_s(self) -> float:
        """The most recently recorded frame lag, or 0.0 if none was recorded."""
        return self._lags[-1][1] if self._lags else 0.0

    def record_write(self, now: float, busy_s: float, reports: int) -> None:
        """Record a write that ended at now after busy_s seconds; reports of 0 leaves the per-report cost alone."""
        start = now - busy_s
        for second in range(math.floor(start), math.floor(now) + 1):
            overlap = min(second + 1, now) - max(second, start)
            if overlap > 0:
                self._buckets[second] = self._buckets.get(second, 0.0) + overlap
        if reports > 0:
            self._seconds_per_report += EWMA_ALPHA * (busy_s / reports - self._seconds_per_report)
        oldest = math.floor(now - HISTORY_S)
        for second in [second for second in self._buckets if second < oldest]:
            del self._buckets[second]

    def record_lag(self, now: float, lag_s: float) -> None:
        """Record how far behind its scheduled deadline a frame was written at now; it holds until the next one."""
        self._lags.append((now, lag_s))
        while len(self._lags) > 1 and self._lags[1][0] <= now - HISTORY_S:
            self._lags.popleft()

    def busy_fraction(self, now: float, window_s: float) -> float:
        """Fraction of the window_s seconds before now spent writing (the oldest bucket counts pro rata)."""
        start = now - window_s
        busy = 0.0
        for second in range(math.floor(start), math.floor(now) + 1):
            covered = min(second + 1, now) - second
            overlap = min(second + 1, now) - max(second, start)
            if overlap > 0:
                busy += self._buckets.get(second, 0.0) * overlap / covered
        return min(1.0, busy / window_s)

    def lag_over(self, now: float, threshold_s: float, for_s: float) -> bool:
        """True when the recorded lag stayed above threshold_s for the whole for_s seconds before now."""
        start = now - for_s
        in_effect: float | None = None
        for when, lag in self._lags:
            if when <= start:
                in_effect = lag
            elif lag <= threshold_s:
                return False
        return in_effect is not None and in_effect > threshold_s
