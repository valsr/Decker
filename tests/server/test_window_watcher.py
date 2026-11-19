import threading
import time
from typing import Callable

from assertpy import assert_that

from decker.common.model import WindowInfo
from decker.server.window_watcher import WatcherTimings, WindowWatcher
from decker.server.windows.backend import BackendStatus

WAIT = 3.0


class FakeBackend:
    name = "fake"

    def __init__(self, supports_pick: bool = True, fail_starts: int = 0) -> None:
        self.supports_pick = supports_pick
        self.fail_starts = fail_starts
        self.starts = 0
        self.stops = 0
        self.on_change: Callable[[WindowInfo], None] | None = None
        self.pick_cb: Callable[[WindowInfo | None], None] | None = None
        self.started = threading.Event()
        self.in_start = threading.Event()
        self.release_start: threading.Event | None = None
        self.stop_threads: list[int] = []
        self.running = False

    def available(self) -> BackendStatus:
        return BackendStatus("active")

    def start(self, on_change: Callable[[WindowInfo], None]) -> None:
        self.starts += 1
        if self.starts <= self.fail_starts:
            raise RuntimeError("boom")
        self.on_change = on_change
        self.in_start.set()
        if self.release_start is not None:
            self.release_start.wait(WAIT)
        self.running = True
        self.started.set()

    def stop(self) -> None:
        self.stops += 1
        self.running = False
        self.stop_threads.append(threading.get_ident())

    def pick(self, on_result: Callable[[WindowInfo | None], None]) -> None:
        self.pick_cb = on_result


class Recorder:
    def __init__(self) -> None:
        self.windows: list[WindowInfo] = []
        self.pushed: list[tuple[str, WindowInfo]] = []
        self.statuses = 0
        self.got = threading.Event()

    def on_window(self, window: WindowInfo) -> None:
        self.windows.append(window)
        self.got.set()

    def push(self, event: str, window: WindowInfo) -> None:
        self.pushed.append((event, window))

    def on_status(self) -> None:
        self.statuses += 1


def make(backend: FakeBackend, timings: WatcherTimings | None = None) -> tuple[WindowWatcher, Recorder]:
    rec = Recorder()
    watcher = WindowWatcher(backend, rec.on_window, rec.push, rec.on_status, timings or WatcherTimings(debounce=0.05))
    return watcher, rec


def wait_for(condition: Callable[[], bool]) -> None:
    deadline = time.time() + WAIT
    while not condition() and time.time() < deadline:
        time.sleep(0.005)
    assert_that(condition()).is_true()


def win(title: str) -> WindowInfo:
    return WindowInfo(window_class="app", title=title)


def test_rapid_changes_evaluate_once_for_last_window() -> None:
    backend = FakeBackend()
    watcher, rec = make(backend)
    watcher.start()
    assert backend.on_change is not None
    for title in ("a", "b", "c"):
        backend.on_change(win(title))
    assert_that(rec.got.wait(WAIT)).is_true()
    time.sleep(0.15)
    watcher.stop()
    assert_that(rec.windows).is_equal_to([win("c")])


def test_identical_consecutive_windows_dropped() -> None:
    backend = FakeBackend()
    watcher, rec = make(backend)
    watcher.start()
    assert backend.on_change is not None
    backend.on_change(win("a"))
    assert_that(rec.got.wait(WAIT)).is_true()
    backend.on_change(win("a"))
    time.sleep(0.2)
    watcher.stop()
    assert_that(rec.windows).is_length(1)
    assert_that(rec.pushed).is_length(1)


def test_push_called_for_every_distinct_change() -> None:
    backend = FakeBackend()
    watcher, rec = make(backend, WatcherTimings(debounce=5.0))
    watcher.start()
    assert backend.on_change is not None
    backend.on_change(win("a"))
    backend.on_change(win("b"))
    watcher.stop()
    assert_that([w for _, w in rec.pushed]).is_equal_to([win("a"), win("b")])
    assert_that(rec.windows).is_empty()


def test_backend_exception_marks_unavailable_and_retries() -> None:
    backend = FakeBackend(fail_starts=1)
    watcher, rec = make(backend, WatcherTimings(debounce=0.05, retry_base=0.05, retry_cap=0.2))
    watcher.start()
    assert_that(watcher.status()["state"]).is_equal_to("unavailable")
    assert_that(watcher.status()["reason"]).contains("boom")
    wait_for(lambda: watcher.status()["state"] == "active")
    assert_that(rec.statuses).is_greater_than_or_equal_to(2)
    watcher.stop()
    assert_that(backend.stops).is_greater_than_or_equal_to(1)


def test_callback_exception_marks_unavailable() -> None:
    backend = FakeBackend()
    rec = Recorder()

    def bad(_window: WindowInfo) -> None:
        raise ValueError("bad callback")

    watcher = WindowWatcher(
        backend, bad, rec.push, rec.on_status, WatcherTimings(debounce=0.02, retry_base=5.0, retry_cap=5.0)
    )
    watcher.start()
    assert backend.on_change is not None
    backend.on_change(win("a"))
    deadline = time.time() + WAIT
    while watcher.status()["state"] != "unavailable" and time.time() < deadline:
        time.sleep(0.01)
    assert_that(watcher.status()["state"]).is_equal_to("unavailable")
    watcher.stop()


def test_pick_refused_while_pick_open_and_when_unsupported() -> None:
    backend = FakeBackend()
    watcher, _ = make(backend)
    watcher.start()
    results: list[WindowInfo | None] = []
    assert_that(watcher.pick(results.append)).is_true()
    assert_that(watcher.pick(results.append)).is_false()
    assert backend.pick_cb is not None
    backend.pick_cb(win("x"))
    assert_that(results).is_equal_to([win("x")])
    assert_that(watcher.pick(results.append)).is_true()
    watcher.stop()

    unsupported = FakeBackend(supports_pick=False)
    other, _ = make(unsupported)
    other.start()
    assert_that(other.pick(results.append)).is_false()
    other.stop()

    idle, _ = make(FakeBackend())
    assert_that(idle.pick(results.append)).is_false()


def test_pick_times_out_with_none() -> None:
    backend = FakeBackend()
    watcher, _ = make(backend, WatcherTimings(debounce=0.05, pick_timeout=0.05))
    watcher.start()
    done = threading.Event()
    results: list[WindowInfo | None] = []

    def on_result(window: WindowInfo | None) -> None:
        results.append(window)
        done.set()

    assert_that(watcher.pick(on_result)).is_true()
    assert_that(done.wait(WAIT)).is_true()
    assert_that(results).is_equal_to([None])
    assert backend.pick_cb is not None
    backend.pick_cb(win("late"))
    assert_that(results).is_equal_to([None])
    watcher.stop()


def test_status_reports_last_window_and_support() -> None:
    backend = FakeBackend(supports_pick=False)
    watcher, rec = make(backend)
    assert_that(watcher.status()["window"]).is_none()
    watcher.start()
    assert backend.on_change is not None
    backend.on_change(win("t"))
    assert_that(rec.got.wait(WAIT)).is_true()
    status = watcher.status()
    assert_that(status).contains_key("state", "reason", "backend", "supports_pick", "window")
    assert_that(status["state"]).is_equal_to("active")
    assert_that(status["backend"]).is_equal_to("fake")
    assert_that(status["supports_pick"]).is_false()
    assert_that(status["window"]["title"]).is_equal_to("t")
    assert_that(watcher.last_window()).is_equal_to(win("t"))
    watcher.stop()


def test_stop_during_start_leaves_backend_stopped_and_not_active() -> None:
    backend = FakeBackend()
    backend.release_start = threading.Event()
    watcher, _ = make(backend, WatcherTimings(debounce=0.05, retry_base=0.02, retry_cap=0.02))
    launcher = threading.Thread(target=watcher.start)
    launcher.start()
    assert_that(backend.in_start.wait(WAIT)).is_true()
    watcher.stop()
    backend.release_start.set()
    launcher.join(WAIT)
    assert_that(backend.running).is_false()
    assert_that(watcher.status()["state"]).is_not_equal_to("active")


def test_second_start_does_not_double_launch() -> None:
    backend = FakeBackend()
    watcher, _ = make(backend)
    watcher.start()
    watcher.start()
    watcher.stop()
    assert_that(backend.starts).is_equal_to(1)


def test_backend_stop_not_called_on_callback_thread() -> None:
    backend = FakeBackend()
    rec = Recorder()

    def bad_push(_event: str, _window: WindowInfo) -> None:
        raise ValueError("push failed")

    watcher = WindowWatcher(
        backend, rec.on_window, bad_push, rec.on_status, WatcherTimings(retry_base=5.0, retry_cap=5.0)
    )
    watcher.start()
    assert backend.on_change is not None
    idents: list[int] = []

    def emit() -> None:
        idents.append(threading.get_ident())
        assert backend.on_change is not None
        backend.on_change(win("a"))

    worker = threading.Thread(target=emit)
    worker.start()
    worker.join(WAIT)
    wait_for(lambda: bool(backend.stop_threads))
    assert_that(backend.stop_threads[0]).is_not_equal_to(idents[0])
    watcher.stop()


def test_backoff_keeps_growing_when_callback_always_fails() -> None:
    backend = FakeBackend()

    def bad(_window: WindowInfo) -> None:
        raise ValueError("always")

    rec = Recorder()
    watcher = WindowWatcher(
        backend, bad, rec.push, rec.on_status, WatcherTimings(debounce=0.01, retry_base=0.05, retry_cap=0.2)
    )
    watcher.start()
    gaps: list[float] = []
    for cycle in range(1, 5):  # pylint: disable=cell-var-from-loop
        wait_for(lambda: backend.starts == cycle and watcher.status()["state"] == "active")
        assert backend.on_change is not None
        backend.on_change(win(str(cycle)))
        wait_for(lambda: watcher.status()["state"] == "unavailable")
        failed_at = time.time()
        wait_for(lambda: backend.starts == cycle + 1)
        gaps.append(time.time() - failed_at)
    watcher.stop()
    assert_that(gaps[2]).is_greater_than(0.12)
    assert_that(gaps[3]).is_greater_than(0.12)


def test_backoff_delay_doubles_to_cap() -> None:
    from decker.server.window_watcher import backoff_delay

    delays = [backoff_delay(1.0, 30.0, n) for n in range(8)]
    assert_that(delays).is_equal_to([1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0])


def test_stop_with_open_pick_reports_none_once() -> None:
    backend = FakeBackend()
    watcher, _ = make(backend)
    watcher.start()
    results: list[WindowInfo | None] = []
    assert_that(watcher.pick(results.append)).is_true()
    watcher.stop()
    assert backend.pick_cb is not None
    backend.pick_cb(win("late"))
    assert_that(results).is_equal_to([None])


def test_late_callback_after_stop_is_ignored() -> None:
    backend = FakeBackend()
    watcher, rec = make(backend)
    watcher.start()
    watcher.stop()
    assert backend.on_change is not None
    backend.on_change(win("late"))
    time.sleep(0.15)
    assert_that(rec.windows).is_empty()
    assert_that(rec.pushed).is_empty()
    assert_that(watcher.last_window()).is_none()


def test_failure_after_stop_does_not_flip_state() -> None:
    backend = FakeBackend()
    watcher, _ = make(backend)
    watcher.start()
    watcher.stop()
    state = watcher.status()["state"]
    watcher._fail(RuntimeError("late"))  # pylint: disable=protected-access
    assert_that(watcher.status()["state"]).is_equal_to(state)


def test_no_timer_fires_after_stop() -> None:
    backend = FakeBackend()
    watcher, rec = make(backend, WatcherTimings(debounce=0.05))
    watcher.start()
    assert backend.on_change is not None
    backend.on_change(win("a"))
    watcher.stop()
    time.sleep(0.15)
    assert_that(rec.windows).is_empty()


def test_pick_failure_returns_false_and_allows_new_pick() -> None:
    backend = FakeBackend()
    watcher, _ = make(backend)
    watcher.start()
    results: list[WindowInfo | None] = []
    original = backend.pick

    def failing(on_result: Callable[[WindowInfo | None], None]) -> None:
        raise RuntimeError("no pick")

    backend.pick = failing  # type: ignore[method-assign]
    assert_that(watcher.pick(results.append)).is_false()
    assert_that(results).is_empty()
    backend.pick = original  # type: ignore[method-assign]
    assert_that(watcher.pick(results.append)).is_true()
    watcher.stop()


def test_pick_result_and_timeout_race_fires_once() -> None:
    backend = FakeBackend()
    watcher, _ = make(backend, WatcherTimings(debounce=0.05, pick_timeout=0.05))
    watcher.start()
    results: list[WindowInfo | None] = []
    assert_that(watcher.pick(results.append)).is_true()
    assert backend.pick_cb is not None
    backend.pick_cb(win("x"))
    backend.pick_cb(win("y"))
    time.sleep(0.15)
    assert_that(results).is_equal_to([win("x")])
    watcher.stop()
