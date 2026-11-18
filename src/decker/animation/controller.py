"""Feedback controller choosing the animation quality and frame-rate level for one device."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

BUDGET: float = 0.75
STEP_DOWN_BUSY: float = 0.75
LAG_LIMIT_S: float = 0.250
STEP_UP_BUSY: float = 0.50
STEP_UP_HOLD_S: float = 30.0
STEP_UP_PROJECTED: float = 0.65


@dataclass(frozen=True)
class Level:
    """One rung of the ladder: JPEG quality and an optional frame-rate cap (None means native)."""

    quality: int
    fps_cap: int | None


@dataclass(frozen=True)
class LoadSample:
    """Measured load at time `now`: mean busy fractions over 5 s and 20 s, and sustained frame lag in seconds."""

    now: float
    busy_5s: float
    busy_20s: float
    lag_s: float


Demand = Callable[[Level], float]

LADDER: tuple[Level, ...] = (
    Level(100, None),
    Level(90, None),
    Level(90, 30),
    Level(90, 20),
    Level(90, 15),
    Level(90, 10),
    Level(75, 10),
    Level(75, 5),
)


def ladder_for(bmp: bool) -> tuple[Level, ...]:
    """Return the ladder for a deck type; BMP decks use only the distinct frame-rate rungs at quality 100."""
    if not bmp:
        return LADDER
    caps: list[int | None] = []
    for level in LADDER:
        if level.fps_cap not in caps:
            caps.append(level.fps_cap)
    return tuple(Level(100, cap) for cap in caps)


class LevelController:
    """Pure decision logic stepping a device along a cost-ordered ladder of levels."""

    def __init__(self, ladder: Sequence[Level], budget: float = BUDGET) -> None:
        self._ladder: tuple[Level, ...] = tuple(ladder)
        self._budget: float = budget
        self._index: int = 0
        self._last_step_down: float | None = None

    @property
    def level(self) -> Level:
        """The current level."""
        return self._ladder[self._index]

    def replan(self, demand: Demand, seconds_per_report: float) -> Level:
        """Pick the first (highest quality) level whose projected busy fraction fits the budget, else the last."""
        self._index = len(self._ladder) - 1
        for index, level in enumerate(self._ladder):
            if demand(level) * seconds_per_report <= self._budget:
                self._index = index
                break
        return self.level

    def tick(self, sample: LoadSample, demand: Demand, seconds_per_report: float) -> Level:
        """Apply the step rules to a load sample; moves at most one rung."""
        last = len(self._ladder) - 1
        if sample.busy_5s > STEP_DOWN_BUSY or sample.lag_s > LAG_LIMIT_S:
            if self._index < last:
                self._index += 1
                self._last_step_down = sample.now
        elif self._index > 0 and self._may_step_up(sample, demand):
            self._index -= 1
        return self.level

    def _may_step_up(self, sample: LoadSample, demand: Demand) -> bool:
        if sample.busy_20s >= STEP_UP_BUSY:
            return False
        if self._last_step_down is not None and sample.now - self._last_step_down < STEP_UP_HOLD_S:
            return False
        current = demand(self.level)
        if current <= 0:
            return False
        projected = sample.busy_20s * demand(self._ladder[self._index - 1]) / current
        return projected <= STEP_UP_PROJECTED
