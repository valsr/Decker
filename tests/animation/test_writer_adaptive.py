import io
import logging
from collections.abc import Callable, Iterator

import pytest
from assertpy import assert_that
from PIL import Image

from decker.animation.controller import LADDER, Level, LevelController
from decker.animation.encode import KeyFormat
from decker.animation.factory import AnimationFactory
from decker.animation.load import LoadMonitor
from decker.animation.model import Animation, AnimationSpec, Frame
from decker.animation.writer import POLL_S, REPLAN_SETTLE_S, AdaptiveConfig, KeyWriter
from decker.server.appearance import resolve_appearance

SECONDS_PER_REPORT = 0.00025
FMT = KeyFormat((96, 96), "JPEG", 0, (False, False))
L0, L1 = LADDER[0], LADDER[1]
START = 1000.0
# Reports per frame by quality for the default test GIF (10 frames).
REPORTS = {100: 7, 90: 3, 75: 2}


class _Clock:
    def __init__(self) -> None:
        self.now: float = START

    def __call__(self) -> float:
        return self.now


class _Deck:
    """Fake deck whose writes take reports * SECONDS_PER_REPORT of clock time; data is b"<reports>|<label>"."""

    def __init__(self, clock: _Clock) -> None:
        self._clock: _Clock = clock
        self.writes: list[tuple[float, int, bytes | None]] = []

    def __call__(self, key_index: int, data: bytes | None) -> None:
        self.writes.append((self._clock.now, key_index, data))
        if data is not None:
            self._clock.now += int(data.split(b"|")[0]) * SECONDS_PER_REPORT

    def frames_of(self, key_index: int, since: float = 0.0) -> list[bytes]:
        return [data for when, key, data in self.writes if key == key_index and when >= since and data is not None]


def _animation(quality: int, reports: dict[int, int], delay_ms: int = 100, count: int = 10) -> Animation:
    frames = tuple(
        Frame(f"{reports[quality]}|q{quality}f{index}".encode(), reports[quality], delay_ms) for index in range(count)
    )
    return Animation("anim", quality, frames, b"poster", {q: float(r) for q, r in reports.items()})


def _static(reports: int, label: str) -> bytes:
    """Static image data as long as `reports` full reports, so the writer's size-based report count matches."""
    return f"{reports}|{label}|".encode().ljust(reports * FMT.report_payload, b".")


POSTER = _static(16, "poster")


class _Factory:
    """Fake frame source: an animation per quality, returned only once that quality is marked ready."""

    def __init__(self, reports: dict[int, int], delay_ms: int = 100, ready: tuple[int, ...] = (100, 90, 75)) -> None:
        self.animations: dict[int, Animation] = {q: _animation(q, reports, delay_ms) for q in reports}
        self.ready: set[int] = set(ready)
        self.calls: list[int] = []

    def frames_for(self, spec: AnimationSpec, fmt: KeyFormat, quality: int) -> Animation | None:
        assert_that(fmt).is_equal_to(FMT)
        self.calls.append(quality)
        return self.animations[quality] if quality in self.ready else None

    def cached_frames(self, spec: AnimationSpec, fmt: KeyFormat, quality: int) -> Animation | None:
        assert_that(fmt).is_equal_to(FMT)
        return self.animations[quality] if quality in self.ready else None


SPEC = AnimationSpec(b"gif", {}, "", 1.0)


class _Sim:
    def __init__(self, factory: _Factory) -> None:
        self.clock: _Clock = _Clock()
        self.deck: _Deck = _Deck(self.clock)
        self.monitor: LoadMonitor = LoadMonitor()
        config = AdaptiveConfig(LevelController(LADDER), self.monitor, factory, FMT)
        self.writer: KeyWriter = KeyWriter(self.deck, self.clock, adaptive=config)
        self.levels: list[tuple[float, Level]] = [(START, self.writer.level)]
        # Optional background load: a static write every period seconds while active.
        self.static_period: float | None = None
        self._next_static: float = START

    def run_until(self, end: float) -> None:
        while self.clock.now < end:
            if self.static_period is not None and self.clock.now >= self._next_static:
                self.writer.submit_static(99, _static(8, "plugin"), timeout=0.0)
                self._next_static = self.clock.now + self.static_period
            deadline = self.writer.step(self.clock.now)
            target = end if deadline is None else min(deadline, end)
            if self.static_period is not None:
                target = min(target, self._next_static)
            self.clock.now = max(self.clock.now, target)
            if self.writer.level != self.levels[-1][1]:
                self.levels.append((self.clock.now, self.writer.level))

    def level_at(self, when: float) -> Level:
        return [level for changed, level in self.levels if changed <= when][-1]


def _play(sim: _Sim, keys: range) -> None:
    for key in keys:
        sim.writer.play_spec(key, SPEC)


def test_32_keys_at_10fps_settle_at_L0_and_stay() -> None:
    sim = _Sim(_Factory(REPORTS))
    _play(sim, range(32))

    sim.run_until(START + 60)

    assert_that(sim.levels).is_equal_to([(START, L0)])
    assert_that(sim.monitor.busy_fraction(sim.clock.now, 20.0)).is_close_to(32 * 10 * 7 * SECONDS_PER_REPORT, 0.02)
    assert_that(sim.monitor.seconds_per_report).is_close_to(SECONDS_PER_REPORT, 1e-9)
    assert_that(len(sim.deck.frames_of(0, since=START + 50))).is_between(99, 101)
    assert_that(sim.deck.frames_of(31)[-1].decode()).starts_with("7|q100")


def test_overload_steps_down_within_6s_and_recovers_after_load_drops(caplog: pytest.LogCaptureFixture) -> None:
    sim = _Sim(_Factory(REPORTS))
    _play(sim, range(32))
    sim.run_until(START + 30)
    assert_that(sim.writer.level).is_equal_to(L0)

    caplog.set_level(logging.INFO, logger="decker.animation.writer")
    overload = START + 30
    sim.static_period = 0.005  # 200 static writes/s of 8 reports: 40% busy on top of 56% for the animations
    sim.run_until(overload + 6)
    assert_that(sim.writer.level).is_not_equal_to(L0)
    assert_that(sim.levels[1][0]).is_less_than_or_equal_to(overload + 6)
    sim.run_until(overload + 10)
    assert_that(sim.writer.level.quality).is_equal_to(90)
    assert_that(sim.deck.frames_of(5, since=overload + 9)[-1].decode()).starts_with("3|q90")

    sim.static_period = None
    sim.run_until(overload + 45)
    assert_that(sim.writer.level).is_equal_to(L0)
    sim.run_until(overload + 60)
    assert_that(sim.level_at(overload + 60)).is_equal_to(L0)
    assert_that(sim.levels[-1][0]).is_less_than(overload + 45)
    assert_that(sim.deck.frames_of(5, since=overload + 55)[-1].decode()).starts_with("7|q100")
    messages = [record.getMessage() for record in caplog.records if record.levelno == logging.INFO]
    assert_that(messages).is_not_empty()
    assert_that(messages[0]).contains("busy", "overloaded")
    assert_that(messages[-1]).contains("load dropped")


def test_page_switch_burst_of_32_static_writes_does_not_change_the_level(caplog: pytest.LogCaptureFixture) -> None:
    # 72% busy at q100. The posters (32 x 16 reports, 128 ms, less the frames they displace) add about 6% to a 1 s
    # window, which would step down, but only about 1% to the 5 s window.
    sim = _Sim(_Factory({100: 9, 90: 4, 75: 3}))
    _play(sim, range(32))
    sim.run_until(START + 20)
    caplog.set_level(logging.INFO, logger="decker.animation.writer")

    for key in range(32):
        assert_that(sim.writer.submit_static(key, POSTER, timeout=0.0)).is_false()
    _play(sim, range(32))
    sim.run_until(START + 40)

    assert_that(sim.levels).is_equal_to([(START, L0)])
    assert_that(sim.deck.frames_of(0, since=START + 20)[0]).is_equal_to(POSTER)
    assert_that(caplog.records).is_empty()


@pytest.mark.parametrize("worker_runs_between_calls", [False, True])
def test_page_switch_on_an_overloaded_key_set_keeps_the_level_and_builds_nothing_unused(
    worker_runs_between_calls: bool, caplog: pytest.LogCaptureFixture
) -> None:
    # 32 keys at 20 fps only fit at q90 (L1). Re-attaching the same animations must not swing L1 -> L0 -> L1.
    factory = _Factory(REPORTS, delay_ms=50)
    sim = _Sim(factory)
    _play(sim, range(32))
    sim.run_until(START + 25)
    assert_that([level for _, level in sim.levels]).is_equal_to([L0, L1])
    factory.calls.clear()
    caplog.set_level(logging.INFO, logger="decker.animation.writer")

    switch = sim.clock.now
    for key in range(32):
        sim.writer.submit_static(key, POSTER, timeout=0.0)
        if worker_runs_between_calls:  # a real submit_static waits for its write
            sim.run_until(sim.clock.now + 0.005)
    for key in range(32):
        sim.writer.play_spec(key, SPEC)
        if worker_runs_between_calls:
            sim.run_until(sim.clock.now + 0.001)
    sim.run_until(switch + 5)

    assert_that([level for _, level in sim.levels]).is_equal_to([L0, L1])
    assert_that(caplog.records).is_empty()
    assert_that(factory.calls).does_not_contain(100)
    assert_that(sim.deck.frames_of(7, since=switch + 4)[-1].decode()).starts_with("3|q90")


def test_waiting_spec_starts_with_a_cached_quality_when_the_levels_quality_is_not_built() -> None:
    # q90 is cached, q100 never builds: the keys start at once and the plan settles on q90 without asking for q100.
    factory = _Factory(REPORTS, delay_ms=50, ready=(90,))
    sim = _Sim(factory)
    _play(sim, range(32))
    sim.run_until(START + 1)

    assert_that(sim.writer.level).is_equal_to(L1)
    assert_that(sim.deck.frames_of(0)[0]).is_equal_to(b"3|q90f0")
    assert_that(sim.deck.frames_of(31)).is_not_empty()
    assert_that(factory.calls).does_not_contain(100)


def test_waiting_spec_started_at_another_quality_moves_to_the_levels_quality_once_built() -> None:
    factory = _Factory(REPORTS, ready=(90,))
    sim = _Sim(factory)
    sim.writer.play_spec(0, SPEC)
    sim.run_until(START + 0.5)
    assert_that(sim.writer.level).is_equal_to(L0)
    assert_that(sim.deck.frames_of(0)[0]).is_equal_to(b"3|q90f0")
    assert_that(factory.calls).contains(100)

    factory.ready.add(100)
    sim.run_until(START + 1.0)
    assert_that(sim.deck.frames_of(0)[-1].decode()).starts_with("7|q100")


def test_adding_keys_replans_immediately() -> None:
    # 20 fps: 16 keys at q100 are 56% busy, 32 keys would be 112%; at q90 32 keys are 48%.
    sim = _Sim(_Factory(REPORTS, delay_ms=50))
    _play(sim, range(16))
    sim.run_until(START + 5)
    assert_that(sim.writer.level).is_equal_to(L0)

    _play(sim, range(16, 32))
    assert_that(sim.writer.level).is_equal_to(L0)  # new keys count only once their frames are ready
    sim.writer.step(sim.clock.now)
    assert_that(sim.writer.level).is_equal_to(L1)

    # A cheaper key set is planned once it has been stable for REPLAN_SETTLE_S.
    for key in range(16, 32):
        sim.writer.stop(key)
    stopped = sim.clock.now
    sim.run_until(stopped + REPLAN_SETTLE_S / 2)
    assert_that(sim.writer.level).is_equal_to(L1)
    sim.run_until(stopped + REPLAN_SETTLE_S + 0.01)
    assert_that(sim.writer.level).is_equal_to(L0)


def test_quality_change_keeps_playing_old_frames_until_new_quality_is_ready() -> None:
    # 20 fps, 0.5 s loop: 32 keys at q100 overload, so the plan drops to q90 once the second half is ready.
    factory = _Factory(REPORTS, delay_ms=50, ready=(100,))
    sim = _Sim(factory)
    _play(sim, range(16))
    sim.run_until(START + 1.02)
    _play(sim, range(16, 32))
    sim.writer.step(sim.clock.now)
    assert_that(sim.writer.level).is_equal_to(L1)

    sim.run_until(START + 3.02)
    old_frames = sim.deck.frames_of(0, since=START + 1.02)
    assert_that(len(old_frames)).is_between(39, 41)
    assert_that([data[:6] for data in old_frames + sim.deck.frames_of(20)]).contains_only(b"7|q100")
    assert_that(factory.calls).contains(90)

    factory.ready.add(90)
    sim.run_until(START + 3.5)
    switched = [(when, data) for when, key, data in sim.deck.writes if key == 0 and when >= START + 3.02]
    labels = [data[:5] for _, data in switched if data is not None]
    first_new = labels.index(b"3|q90")
    assert_that(labels[:first_new]).contains_only(b"7|q10")
    assert_that(labels[first_new:]).contains_only(b"3|q90")
    when, data = switched[first_new]
    # The new frames continue at the same elapsed time: the written frame is the one due at that moment.
    expected_index = int(((when - START) % 0.5 + 1e-6) // 0.05)
    assert_that(data).is_equal_to(f"3|q90f{expected_index}".encode())
    assert_that(sim.deck.frames_of(20, since=START + 3.4)[-1].decode()).starts_with("3|q90")


def test_level_fps_cap_applies_to_every_key_but_never_above_its_native_rate() -> None:
    clock = _Clock()
    deck = _Deck(clock)
    slow, fast = _Factory(REPORTS, delay_ms=100), _Factory(REPORTS, delay_ms=20)
    writer = KeyWriter(deck, clock, adaptive=AdaptiveConfig(LevelController([Level(100, 15)]), None, slow, FMT))
    writer.play_spec(0, SPEC)
    writer.play(1, fast.animations[100], fps_cap=50)
    sim_end = START + 10

    while clock.now < sim_end:
        deadline = writer.step(clock.now)
        clock.now = max(clock.now, sim_end if deadline is None else min(deadline, sim_end))

    assert_that(len(deck.frames_of(0, since=START + 1))).is_between(89, 91)
    assert_that(len(deck.frames_of(1, since=START + 1))).is_between(9 * 15 - 2, 9 * 15 + 1)


def test_demand_uses_measured_reports_without_an_estimate_and_ignores_still_images() -> None:
    sim = _Sim(_Factory(REPORTS))
    # No estimate for any ladder quality: 400 measured reports x 10 fps is 100% busy until the 5 fps cap.
    heavy = Animation("heavy", 50, tuple(Frame(f"400|f{i}".encode(), 400, 100) for i in range(10)), b"", {})
    still = Animation("still", 90, (Frame(b"900|still", 900, 100),), b"", {90: 900.0})

    sim.writer.play(1, still)
    sim.writer.step(sim.clock.now)
    assert_that(sim.writer.level).is_equal_to(L0)
    sim.writer.play(0, heavy)
    sim.writer.step(sim.clock.now)
    assert_that(sim.writer.level).is_equal_to(LADDER[-1])
    sim.writer.stop_all()
    sim.run_until(sim.clock.now + REPLAN_SETTLE_S + 0.01)
    assert_that(sim.writer.level).is_equal_to(L0)


def test_play_spec_polls_a_pending_build_without_spinning() -> None:
    factory = _Factory(REPORTS, ready=())
    sim = _Sim(factory)
    sim.writer.play_spec(0, SPEC)

    deadline = sim.writer.step(sim.clock.now)
    assert_that(deadline).is_close_to(START + POLL_S, 1e-9)
    sim.run_until(START + 1)
    assert_that(len(factory.calls)).is_between(int(1 / POLL_S) - 1, int(1 / POLL_S) + 2)
    assert_that(sim.deck.writes).is_empty()

    factory.ready.add(100)
    sim.run_until(START + 1.2)
    assert_that(sim.deck.frames_of(0)[0]).is_equal_to(b"7|q100f0")


def test_animation_id_names_the_waiting_then_playing_spec_until_the_key_is_stopped() -> None:
    factory = _Factory(REPORTS, ready=())
    sim = _Sim(factory)
    assert_that(sim.writer.animation_id(0)).is_none()

    sim.writer.play_spec(0, SPEC)
    assert_that(sim.writer.animation_id(0)).is_equal_to(SPEC.animation_id)  # waiting for its frames
    factory.ready.add(100)
    sim.run_until(START + 0.5)
    assert_that(sim.deck.frames_of(0)).is_not_empty()
    assert_that(sim.writer.animation_id(0)).is_equal_to(SPEC.animation_id)  # playing

    sim.writer.stop(0)
    assert_that(sim.writer.animation_id(0)).is_none()
    sim.writer.play(1, factory.animations[100])
    assert_that(sim.writer.animation_id(1)).is_equal_to("anim")  # a fixed animation without a spec
    sim.writer.submit_static(1, _static(1, "still"), timeout=0.0)
    assert_that(sim.writer.animation_id(1)).is_none()


def test_play_spec_without_poster_keeps_the_old_animation_until_the_new_one_is_ready() -> None:
    old = _Factory(REPORTS)
    sim = _Sim(_Factory(REPORTS, ready=()))
    sim.writer.play(0, old.animations[90])
    sim.writer.play_spec(0, SPEC, poster_written=False)
    sim.run_until(START + 0.5)
    assert_that(sim.deck.frames_of(0)[-1].decode()).starts_with("3|q90")

    sim.writer.play_spec(0, SPEC)
    sim.run_until(START + 1.0)
    assert_that(len(sim.deck.frames_of(0))).is_equal_to(5)


def test_play_spec_needs_a_factory_and_key_format() -> None:
    writer = KeyWriter(_Deck(_Clock()), _Clock(), adaptive=AdaptiveConfig(LevelController(LADDER)))

    assert_that(writer.play_spec).raises(ValueError).when_called_with(0, SPEC)
    assert_that(KeyWriter(_Deck(_Clock())).level).is_equal_to(L0)


def _gif(count: int = 3) -> bytes:
    images = [Image.new("RGB", (16, 16), (index * 60, 0, 0)) for index in range(count)]
    buffer = io.BytesIO()
    images[0].save(buffer, format="GIF", save_all=True, append_images=images[1:], duration=100, loop=0)
    return buffer.getvalue()


@pytest.fixture(name="factory")
def _real_factory() -> Iterator[AnimationFactory]:
    factory = AnimationFactory(8 * 1024 * 1024)
    yield factory
    factory.close()


def test_play_spec_plays_frames_built_by_the_real_factory(factory: AnimationFactory) -> None:
    clock = _Clock()
    writes: list[tuple[int, bytes | None]] = []
    record: Callable[[int, bytes | None], None] = lambda key, data: writes.append((key, data))
    writer = KeyWriter(record, clock, adaptive=AdaptiveConfig(LevelController(LADDER), None, factory, FMT))
    spec = AnimationSpec(_gif(), resolve_appearance({}, {"background": "#202020"}), "", 1.0)

    writer.play_spec(3, spec)
    writer.step(clock.now)
    assert_that(factory.wait_idle(10.0)).is_true()
    clock.now += POLL_S
    writer.step(clock.now)

    assert_that(writes).is_length(1)
    assert_that(writes[0][0]).is_equal_to(3)
    assert_that(writes[0][1]).is_equal_to(factory.frames_for(spec, FMT, 100).frames[0].data)  # type: ignore[union-attr]
