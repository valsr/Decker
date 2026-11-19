import os
import sys
import threading
from typing import Any, Callable, Mapping

import psutil
import pytest
from assertpy import assert_that

from decker.common.model import WindowInfo
from decker.server.windows.backend import BackendStatus
from decker.server.windows.windows import (
    WindowsBackend,
    WindowsTransport,
    is_pick_message,
    window_from_win32,
)

EDITOR: dict[str, Any] = {"hwnd": 10, "class_name": "Notepad", "title": "a.txt", "pid": 4242}
BROWSER: dict[str, Any] = {"hwnd": 11, "class_name": "Chrome_WidgetWin_1", "title": "Tab", "pid": 4343}


class FakeTransport:
    def __init__(self) -> None:
        self.windows: list[Mapping[str, Any] | None] = [EDITOR]
        self.error: Exception | None = None
        self.closed = 0
        self.pick_timeouts: list[float] = []
        self.picking = 0
        self.max_picking = 0
        self.pick_behaviour: Callable[[], Mapping[str, Any] | None] = lambda: EDITOR
        self.unhooked = 0

    def foreground(self) -> Mapping[str, Any] | None:
        if self.error is not None:
            raise self.error
        return self.windows.pop(0) if len(self.windows) > 1 else self.windows[0]

    def pick(self, timeout: float) -> Mapping[str, Any] | None:
        self.pick_timeouts.append(timeout)
        self.picking += 1
        self.max_picking = max(self.max_picking, self.picking)
        try:
            return self.pick_behaviour()
        finally:
            self.picking -= 1
            self.unhooked += 1

    def close(self) -> None:
        self.closed += 1


def make(transport: FakeTransport, **kwargs: Any) -> WindowsBackend:
    return WindowsBackend(transport=transport, poll_interval=0.01, **kwargs)


def test_window_from_win32_maps_info_and_empty_type() -> None:
    me = psutil.Process(os.getpid())
    info = window_from_win32({**EDITOR, "pid": me.pid})
    assert_that(info).is_equal_to(
        WindowInfo(
            window_class="Notepad",
            window_type="",
            title="a.txt",
            executable=os.path.basename(me.exe()),
            desktop_file="",
            pid=me.pid,
        )
    )


@pytest.mark.parametrize("pid", [0, -1, 2**22 + 12345])
def test_window_from_win32_executable_empty_when_unknown(pid: int) -> None:
    assert_that(window_from_win32({**EDITOR, "pid": pid}).executable).is_equal_to("")


def test_window_from_win32_access_denied_gives_empty_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(pid: int) -> Any:
        raise psutil.AccessDenied(pid)

    monkeypatch.setattr(psutil, "Process", deny)
    assert_that(window_from_win32(EDITOR).executable).is_equal_to("")


def test_is_pick_message_buttons_only() -> None:
    assert_that([is_pick_message(m) for m in (0x201, 0x204, 0x207)]).is_equal_to([True, True, True])
    assert_that([is_pick_message(m) for m in (0x200, 0x202, 0x20A, 0x20E)]).is_equal_to([False] * 4)


@pytest.mark.skipif(sys.platform == "win32", reason="reports off Windows only")
def test_backend_reports_unsupported_off_windows() -> None:
    assert_that(WindowsBackend().available()).is_equal_to(BackendStatus("unsupported", "Windows only"))


def test_backend_available_active_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    assert_that(WindowsBackend().available()).is_equal_to(BackendStatus("active"))


def test_backend_attributes() -> None:
    backend = WindowsBackend(transport=FakeTransport())
    assert_that(backend.name).is_equal_to("windows")
    assert_that(backend.supports_pick).is_true()


def collect(count: int) -> tuple[list[WindowInfo], threading.Event, Callable[[WindowInfo], None]]:
    seen: list[WindowInfo] = []
    done = threading.Event()

    def on_change(info: WindowInfo) -> None:
        seen.append(info)
        if len(seen) >= count:
            done.set()

    return seen, done, on_change


def test_start_reports_initial_and_changes_only() -> None:
    transport = FakeTransport()
    transport.windows = [EDITOR, EDITOR, EDITOR, BROWSER, BROWSER]
    backend = make(transport)
    seen, done, on_change = collect(2)
    backend.start(on_change)
    assert_that(done.wait(2)).is_true()
    backend.stop()
    assert_that([w.window_class for w in seen]).is_equal_to(["Notepad", "Chrome_WidgetWin_1"])


def test_null_and_vanished_foreground_keeps_last_window() -> None:
    transport = FakeTransport()
    transport.windows = [EDITOR, None, None, EDITOR, BROWSER]
    backend = make(transport)
    seen, done, on_change = collect(2)
    backend.start(on_change)
    assert_that(done.wait(2)).is_true()
    backend.stop()
    assert_that([w.window_class for w in seen]).is_equal_to(["Notepad", "Chrome_WidgetWin_1"])


def test_title_change_is_a_change() -> None:
    transport = FakeTransport()
    transport.windows = [EDITOR, {**EDITOR, "title": "b.txt"}]
    backend = make(transport)
    seen, done, on_change = collect(2)
    backend.start(on_change)
    assert_that(done.wait(2)).is_true()
    backend.stop()
    assert_that(seen[1].title).is_equal_to("b.txt")


def test_failure_reported_once_and_not_on_stop() -> None:
    transport = FakeTransport()
    backend = make(transport)
    failures: list[Exception] = []
    failed = threading.Event()

    def on_failure(exc: Exception) -> None:
        failures.append(exc)
        failed.set()

    backend.start(lambda info: None, on_failure)
    transport.error = RuntimeError("boom")
    assert_that(failed.wait(2)).is_true()
    backend.stop()
    threading.Event().wait(0.05)
    assert_that(failures).is_length(1)

    quiet = FakeTransport()
    backend2 = make(quiet)
    other: list[Exception] = []
    backend2.start(lambda info: None, other.append)
    backend2.stop()
    quiet.error = RuntimeError("late")
    threading.Event().wait(0.05)
    assert_that(other).is_empty()
    assert_that(quiet.closed).is_greater_than_or_equal_to(1)


def test_restart_after_failure() -> None:
    transport = FakeTransport()
    backend = make(transport)
    failed = threading.Event()
    backend.start(lambda info: None, lambda exc: failed.set())
    transport.error = RuntimeError("boom")
    assert_that(failed.wait(2)).is_true()
    transport.error = None
    seen, done, on_change = collect(1)
    backend.start(on_change)
    assert_that(done.wait(2)).is_true()
    backend.stop()


def test_stop_from_listener_thread_does_not_raise() -> None:
    backend = make(FakeTransport())
    outcome: list[str] = []
    done = threading.Event()

    def on_change(info: WindowInfo) -> None:
        try:
            backend.stop()
            outcome.append("ok")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            outcome.append(repr(exc))
        done.set()

    backend.start(on_change)
    assert_that(done.wait(2)).is_true()
    assert_that(outcome).is_equal_to(["ok"])


def test_stop_without_start_is_safe() -> None:
    make(FakeTransport()).stop()


def run_pick(backend: WindowsBackend) -> list[WindowInfo | None]:
    results: list[WindowInfo | None] = []
    done = threading.Event()

    def on_result(info: WindowInfo | None) -> None:
        results.append(info)
        done.set()

    backend.pick(on_result)
    assert_that(done.wait(2)).is_true()
    threading.Event().wait(0.02)
    return results


def test_pick_returns_clicked_window_once_and_unhooks() -> None:
    transport = FakeTransport()
    results = run_pick(make(transport, pick_timeout=3.5))
    assert_that(results).is_length(1)
    assert_that(results[0]).is_not_none()
    assert results[0] is not None
    assert_that(results[0].window_class).is_equal_to("Notepad")
    assert_that(transport.pick_timeouts).is_equal_to([3.5])
    assert_that(transport.unhooked).is_equal_to(1)


def test_pick_escape_or_timeout_gives_none() -> None:
    transport = FakeTransport()
    transport.pick_behaviour = lambda: None
    assert_that(run_pick(make(transport))).is_equal_to([None])


def test_pick_error_gives_none_and_unhooks() -> None:
    transport = FakeTransport()

    def boom() -> Mapping[str, Any] | None:
        raise OSError("hook failed")

    transport.pick_behaviour = boom
    assert_that(run_pick(make(transport))).is_equal_to([None])
    assert_that(transport.unhooked).is_equal_to(1)


def test_concurrent_pick_is_rejected_with_none() -> None:
    transport = FakeTransport()
    release = threading.Event()
    entered = threading.Event()

    def slow() -> Mapping[str, Any] | None:
        entered.set()
        release.wait(2)
        return EDITOR

    transport.pick_behaviour = slow
    backend = make(transport)
    first: list[WindowInfo | None] = []
    first_done = threading.Event()

    def on_first(info: WindowInfo | None) -> None:
        first.append(info)
        first_done.set()

    backend.pick(on_first)
    assert_that(entered.wait(2)).is_true()
    second: list[WindowInfo | None] = []
    backend.pick(second.append)
    assert_that(second).is_equal_to([None])
    release.set()
    assert_that(first_done.wait(2)).is_true()
    assert_that(transport.max_picking).is_equal_to(1)
    assert_that(run_pick(backend)).is_length(1)


def test_pick_callback_error_does_not_leak_lock() -> None:
    backend = make(FakeTransport())
    done = threading.Event()

    def bad(info: WindowInfo | None) -> None:
        done.set()
        raise RuntimeError("cb")

    backend.pick(bad)
    assert_that(done.wait(2)).is_true()
    threading.Event().wait(0.05)
    assert_that(run_pick(backend)).is_length(1)


def test_protocol_is_satisfied_by_fake() -> None:
    transport: WindowsTransport = FakeTransport()
    assert_that(transport.foreground()).is_equal_to(EDITOR)


@pytest.mark.skipif(sys.platform != "win32", reason="needs real Windows")
def test_foreground_window_poll_reports_change() -> None:
    backend = WindowsBackend(poll_interval=0.05)
    seen, done, on_change = collect(1)
    backend.start(on_change)
    try:
        assert_that(done.wait(5)).is_true()
    finally:
        backend.stop()


@pytest.mark.skipif(sys.platform != "win32", reason="needs real Windows")
def test_pick_returns_none_on_timeout() -> None:
    results = run_pick_real(WindowsBackend(pick_timeout=0.3))
    assert_that(results).is_equal_to([None])


def run_pick_real(backend: WindowsBackend) -> list[WindowInfo | None]:
    results: list[WindowInfo | None] = []
    done = threading.Event()

    def on_result(info: WindowInfo | None) -> None:
        results.append(info)
        done.set()

    backend.pick(on_result)
    assert_that(done.wait(5)).is_true()
    return results
