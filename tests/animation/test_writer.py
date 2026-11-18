import threading
import time

from assertpy import assert_that

from decker.animation.model import Animation, Frame
from decker.animation.writer import KeyWriter

WRITER_THREAD = "decker-key-writer"


def _animation(datas: list[bytes], delay_ms: int = 100) -> Animation:
    frames = tuple(Frame(data, 1, delay_ms) for data in datas)
    return Animation("anim", 90, frames, b"poster", {90: 1.0})


def _frames(count: int, prefix: str = "f") -> list[bytes]:
    return [f"{prefix}{index}".encode() for index in range(count)]


class _Recorder:
    def __init__(self) -> None:
        self.writes: list[tuple[int, bytes | None]] = []

    def __call__(self, key_index: int, data: bytes | None) -> None:
        self.writes.append((key_index, data))


def _run(writer: KeyWriter, start: float, end: float) -> None:
    """Drive step over [start, end); a deadline within float noise of end counts as end."""
    now: float | None = start
    while now is not None and now < end - 1e-9:
        now = writer.step(now)


def _writer_threads() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate() if thread.name == WRITER_THREAD and thread.is_alive()]


def test_static_write_is_served_before_a_due_animation_frame() -> None:
    recorder = _Recorder()
    writer = KeyWriter(recorder, clock=lambda: 0.0)
    writer.play(0, _animation(_frames(3)))

    assert_that(writer.submit_static(1, b"static", timeout=0.0)).is_false()
    writer.step(0.0)
    writer.step(0.0)

    assert_that(recorder.writes).is_equal_to([(1, b"static"), (0, b"f0")])


def test_earliest_deadline_key_is_written_first() -> None:
    recorder = _Recorder()
    writer = KeyWriter(recorder, clock=lambda: 0.0)
    writer.play(0, _animation(_frames(3), delay_ms=100))
    writer.play(1, _animation(_frames(3, "g"), delay_ms=30))
    writer.step(0.0)
    writer.step(0.0)
    recorder.writes.clear()

    next_deadline = writer.step(0.15)
    writer.step(0.15)

    assert_that(next_deadline).is_greater_than(0.15)
    # Key 1's frame went stale at 0.03, key 0's only at 0.1: key 1 is the earlier deadline despite its higher index.
    assert_that(recorder.writes).is_equal_to([(1, b"g2"), (0, b"f1")])


def test_late_writer_skips_frames_instead_of_replaying_them() -> None:
    recorder = _Recorder()
    writer = KeyWriter(recorder, clock=lambda: 0.0)
    writer.play(0, _animation(_frames(10)))
    assert_that(writer.step(0.0)).is_close_to(0.1, 1e-9)
    recorder.writes.clear()

    first = writer.step(0.5)
    second = writer.step(0.5)

    assert_that(recorder.writes).is_equal_to([(0, b"f5")])
    assert_that(first).is_close_to(0.6, 1e-9)
    assert_that(second).is_close_to(0.6, 1e-9)


def test_fps_cap_limits_writes_per_second() -> None:
    recorder = _Recorder()
    writer = KeyWriter(recorder, clock=lambda: 0.0)
    writer.play(0, _animation(_frames(100), delay_ms=10), fps_cap=30)

    _run(writer, 0.0, 1.0)

    assert_that(recorder.writes).is_length(30)


def test_identical_consecutive_frames_cost_no_write() -> None:
    recorder = _Recorder()
    writer = KeyWriter(recorder, clock=lambda: 0.0)
    writer.play(0, _animation([b"a", b"a", b"b"]))

    _run(writer, 0.0, 0.3)

    assert_that(recorder.writes).is_equal_to([(0, b"a"), (0, b"b")])


def test_static_write_cancels_the_keys_animation_and_wins_a_race() -> None:
    writes: list[tuple[int, bytes | None]] = []
    results: list[bool] = []

    def write(key_index: int, data: bytes | None) -> None:
        writes.append((key_index, data))
        if data == b"f0":
            # A static write submitted while the animation frame is on the wire.
            results.append(writer.submit_static(0, b"static", timeout=0.0))

    writer = KeyWriter(write, clock=lambda: 0.0)
    writer.play(0, _animation(_frames(10)))

    _run(writer, 0.0, 1.0)

    assert_that(results).is_equal_to([False])
    assert_that(writes).is_equal_to([(0, b"f0"), (0, b"static")])


def test_failing_write_for_one_key_does_not_stop_other_keys() -> None:
    attempts: list[tuple[int, bytes | None]] = []

    def write(key_index: int, data: bytes | None) -> None:
        attempts.append((key_index, data))
        if key_index == 1:
            raise OSError("device gone")

    writer = KeyWriter(write, clock=lambda: 0.0)
    writer.play(0, _animation(_frames(10)))
    writer.play(1, _animation(_frames(10, "g")))

    _run(writer, 0.0, 1.0)

    assert_that([data for key, data in attempts if key == 1]).is_equal_to([b"g0"])
    assert_that([data for key, data in attempts if key == 0]).is_equal_to(_frames(10))


def test_failed_write_of_a_replaced_animation_keeps_the_new_one() -> None:
    attempts: list[bytes | None] = []

    def write(key_index: int, data: bytes | None) -> None:
        attempts.append(data)
        if data == b"f0":
            writer.play(0, _animation(_frames(2, "g")))
            raise OSError("device gone")

    writer = KeyWriter(write, clock=lambda: 0.0)
    writer.play(0, _animation(_frames(2)))

    _run(writer, 0.0, 0.2)

    assert_that(attempts).is_equal_to([b"f0", b"g0", b"g1"])


def test_zero_delay_gif_does_not_make_step_return_a_zero_wait() -> None:
    recorder = _Recorder()
    writer = KeyWriter(recorder, clock=lambda: 0.0)
    writer.play(0, _animation(_frames(3), delay_ms=0))
    writer.play(1, Animation("mixed", 90, (Frame(b"z", 1, 0), Frame(b"p", 1, 50)), b"poster", {90: 1.0}))

    deadlines = [writer.step(0.0) for _ in range(4)]

    assert_that(recorder.writes).is_equal_to([(0, b"f0"), (1, b"p")])
    for deadline in deadlines:
        assert_that(deadline).is_not_none().is_greater_than(0.0)
    assert_that(deadlines[-1]).is_close_to(0.05, 1e-9)


def test_stop_and_stop_all_end_animations() -> None:
    recorder = _Recorder()
    writer = KeyWriter(recorder, clock=lambda: 0.0)
    for key_index in range(3):
        writer.play(key_index, _animation(_frames(10)))

    writer.stop(0)
    _run(writer, 0.0, 0.1)
    writer.stop_all()

    assert_that(writer.step(0.5)).is_none()
    assert_that(recorder.writes).is_equal_to([(1, b"f0"), (2, b"f0")])


def test_submit_static_reports_write_success_and_write_errors() -> None:
    def write(key_index: int, data: bytes | None) -> None:
        if data is None:
            raise OSError("device gone")

    writer = KeyWriter(write)
    writer.start()
    try:
        assert_that(writer.submit_static(0, b"image")).is_true()
        assert_that(writer.submit_static(0, None)).is_false()
    finally:
        writer.close()

    assert_that(writer.submit_static(0, b"image")).is_false()
    assert_that(_writer_threads()).is_empty()


def test_submit_static_returns_false_on_timeout() -> None:
    entered = threading.Event()
    release = threading.Event()

    def write(key_index: int, data: bytes | None) -> None:
        entered.set()
        release.wait(5.0)

    writer = KeyWriter(write)
    writer.start()
    try:
        assert_that(writer.submit_static(0, b"image", timeout=0.05)).is_false()
        assert_that(entered.wait(5.0)).is_true()
    finally:
        release.set()
        writer.close()

    assert_that(_writer_threads()).is_empty()


def test_close_returns_promptly_while_a_write_is_pending() -> None:
    entered = threading.Event()
    release = threading.Event()
    results: list[bool] = []

    def write(key_index: int, data: bytes | None) -> None:
        entered.set()
        release.wait(5.0)

    writer = KeyWriter(write)
    writer.start()
    waiter = threading.Thread(target=lambda: results.append(writer.submit_static(0, b"image", timeout=5.0)))
    waiter.start()
    try:
        assert_that(entered.wait(5.0)).is_true()
        began = time.monotonic()
        writer.close(timeout=0.2)
        elapsed = time.monotonic() - began
        waiter.join(5.0)

        assert_that(elapsed).is_less_than(1.0)
        assert_that(waiter.is_alive()).is_false()
        assert_that(results).is_equal_to([False])
    finally:
        release.set()
        writer.close()

    assert_that(_writer_threads()).is_empty()
