import os
import shutil
import subprocess
import threading
from typing import Any, Mapping

import psutil
import pytest
from assertpy import assert_that

from decker.common.model import WindowInfo
from decker.server.windows.backend import BackendStatus
from decker.server.windows.x11 import X11Backend, X11Transport, window_from_x11

TERMINAL: dict[str, Any] = {
    "WM_CLASS": ("konsole", "konsole"),
    "_NET_WM_NAME": "Example - Konsole",
    "_NET_WM_PID": 4242,
    "_NET_WM_WINDOW_TYPE": ["_NET_WM_WINDOW_TYPE_NORMAL"],
}


class FakeX11:
    def __init__(self, bus: "FakeBus") -> None:
        self.bus = bus
        self.closed = False
        self.pending = 0

    def poll(self, timeout: float) -> bool:
        if self.bus.poll_error is not None:
            raise self.bus.poll_error
        if self.pending:
            self.pending -= 1
            return True
        threading.Event().wait(min(timeout, 0.01))
        return False

    def active_window(self) -> Mapping[str, Any] | None:
        self.bus.reads += 1
        if not self.bus.windows:
            return None
        return self.bus.windows.pop(0) if len(self.bus.windows) > 1 else self.bus.windows[0]

    def pick(self, timeout: float) -> Mapping[str, Any] | None:
        self.bus.pick_timeouts.append(timeout)
        self.bus.picking.append(self)
        try:
            return self.bus.pick_behaviour(self)
        finally:
            self.bus.picking.remove(self)

    def close(self) -> None:
        self.closed = True


class FakeBus:
    def __init__(self) -> None:
        self.windows: list[Mapping[str, Any] | None] = [TERMINAL]
        self.reads = 0
        self.transports: list[FakeX11] = []
        self.connect_error: Exception | None = None
        self.poll_error: Exception | None = None
        self.pick_timeouts: list[float] = []
        self.picking: list[FakeX11] = []
        self.pick_behaviour: Any = lambda transport: TERMINAL

    def factory(self) -> X11Transport:
        if self.connect_error:
            raise self.connect_error
        transport = FakeX11(self)
        self.transports.append(transport)
        return transport


@pytest.fixture(name="bus")
def bus_fixture() -> FakeBus:
    return FakeBus()


def test_window_from_x11_maps_properties() -> None:
    mine = psutil.Process(os.getpid())
    info = window_from_x11({**TERMINAL, "_NET_WM_PID": mine.pid})
    assert_that(info).is_equal_to(
        WindowInfo("konsole", "normal", "Example - Konsole", os.path.basename(mine.exe()), "", mine.pid)
    )


def test_wm_class_uses_class_part_not_instance() -> None:
    assert_that(window_from_x11({"WM_CLASS": ("navigator", "firefox")}).window_class).is_equal_to("firefox")
    assert_that(window_from_x11({"WM_CLASS": ("solo",)}).window_class).is_equal_to("solo")


@pytest.mark.parametrize(
    "atom, expected",
    [
        ("_NET_WM_WINDOW_TYPE_NORMAL", "normal"),
        ("_NET_WM_WINDOW_TYPE_DIALOG", "dialog"),
        ("_NET_WM_WINDOW_TYPE_UTILITY", "utility"),
        ("_NET_WM_WINDOW_TYPE_DOCK", "dock"),
        ("_NET_WM_WINDOW_TYPE_SPLASH", "splash"),
        ("_NET_WM_WINDOW_TYPE_MENU", "menu"),
        ("_NET_WM_WINDOW_TYPE_TOOLBAR", "toolbar"),
        ("_NET_WM_WINDOW_TYPE_NOTIFICATION", "normal"),
        ("something-else", "normal"),
    ],
)
def test_window_type_atoms_map_and_default_to_normal(atom: str, expected: str) -> None:
    assert_that(window_from_x11({"_NET_WM_WINDOW_TYPE": [atom]}).window_type).is_equal_to(expected)


def test_window_type_missing_or_empty_is_normal_and_first_known_wins() -> None:
    assert_that(window_from_x11({}).window_type).is_equal_to("normal")
    assert_that(window_from_x11({"_NET_WM_WINDOW_TYPE": []}).window_type).is_equal_to("normal")
    types = ["_NET_WM_WINDOW_TYPE_NOTIFICATION", "_NET_WM_WINDOW_TYPE_DIALOG"]
    assert_that(window_from_x11({"_NET_WM_WINDOW_TYPE": types}).window_type).is_equal_to("dialog")


def test_title_falls_back_to_wm_name() -> None:
    assert_that(window_from_x11({"WM_NAME": "legacy"}).title).is_equal_to("legacy")
    assert_that(window_from_x11({"WM_NAME": "legacy", "_NET_WM_NAME": "modern"}).title).is_equal_to("modern")
    assert_that(window_from_x11({"WM_NAME": "legacy", "_NET_WM_NAME": ""}).title).is_equal_to("legacy")


def test_missing_properties_give_empty_values() -> None:
    assert_that(window_from_x11({})).is_equal_to(WindowInfo("", "normal", "", "", "", 0))


def test_gone_process_has_empty_executable() -> None:
    assert_that(window_from_x11({"_NET_WM_PID": 2**22 + 12345}).executable).is_equal_to("")
    assert_that(window_from_x11({"_NET_WM_PID": -3}).executable).is_equal_to("")


def test_unavailable_without_display(monkeypatch: pytest.MonkeyPatch, bus: FakeBus) -> None:
    monkeypatch.delenv("DISPLAY", raising=False)
    status = X11Backend(bus.factory).available()
    assert_that(status.state).is_equal_to("unavailable")
    assert_that(status.reason).contains("DISPLAY")
    assert_that(bus.transports).is_empty()


def test_unavailable_when_display_cannot_be_opened(monkeypatch: pytest.MonkeyPatch, bus: FakeBus) -> None:
    monkeypatch.setenv("DISPLAY", ":99")
    bus.connect_error = OSError("refused")
    status = X11Backend(bus.factory).available()
    assert_that(status.state).is_equal_to("unavailable")
    assert_that(status.reason).contains("refused")


def test_available_when_display_opens(monkeypatch: pytest.MonkeyPatch, bus: FakeBus) -> None:
    monkeypatch.setenv("DISPLAY", ":99")
    assert_that(X11Backend(bus.factory).available()).is_equal_to(BackendStatus("active"))
    assert_that(bus.transports[0].closed).is_true()


def test_backend_identity() -> None:
    assert_that(X11Backend.name).is_equal_to("x11")
    assert_that(X11Backend.supports_pick).is_true()


def _collect(backend: X11Backend, bus: FakeBus, count: int) -> list[WindowInfo]:
    got: list[WindowInfo] = []
    enough = threading.Event()

    def on_change(info: WindowInfo) -> None:
        got.append(info)
        if len(got) >= count:
            enough.set()

    backend.start(on_change)
    assert_that(enough.wait(5)).is_true()
    return got


def test_start_reports_initial_window_then_changes(bus: FakeBus) -> None:
    other = {"WM_CLASS": ("a", "Other"), "_NET_WM_NAME": "x"}
    bus.windows = [TERMINAL, other]
    backend = X11Backend(bus.factory)
    got: list[WindowInfo] = []
    initial = threading.Event()
    changed = threading.Event()

    def on_change(info: WindowInfo) -> None:
        got.append(info)
        (changed if len(got) > 1 else initial).set()

    backend.start(on_change)
    assert_that(initial.wait(5)).is_true()
    bus.transports[0].pending = 1
    assert_that(changed.wait(5)).is_true()
    backend.stop()
    assert_that([info.window_class for info in got]).is_equal_to(["konsole", "Other"])
    assert_that(bus.transports[0].closed).is_true()


def test_start_raises_when_display_cannot_be_opened(bus: FakeBus) -> None:
    bus.connect_error = OSError("no display")
    with pytest.raises(OSError):
        X11Backend(bus.factory).start(lambda info: None)


def test_vanished_window_is_ignored_and_listener_survives(bus: FakeBus) -> None:
    survivor = {"WM_CLASS": ("a", "Survivor")}
    bus.windows = [None, survivor]
    backend = X11Backend(bus.factory)
    got: list[WindowInfo] = []
    seen = threading.Event()

    def on_change(info: WindowInfo) -> None:
        got.append(info)
        seen.set()

    backend.start(on_change)
    while bus.reads < 1:
        threading.Event().wait(0.01)
    assert_that(got).is_empty()
    bus.transports[0].pending = 1
    assert_that(seen.wait(5)).is_true()
    backend.stop()
    assert_that(got[0].window_class).is_equal_to("Survivor")


def test_callback_exception_does_not_kill_listener(bus: FakeBus) -> None:
    calls: list[int] = []
    second = threading.Event()

    def on_change(info: WindowInfo) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        second.set()

    backend = X11Backend(bus.factory)
    backend.start(on_change)
    while not calls:
        threading.Event().wait(0.01)
    bus.transports[0].pending = 1
    assert_that(second.wait(5)).is_true()
    backend.stop()


def test_listener_failure_calls_on_failure_once(bus: FakeBus) -> None:
    failures: list[Exception] = []
    failed = threading.Event()

    def on_failure(exc: Exception) -> None:
        failures.append(exc)
        failed.set()

    backend = X11Backend(bus.factory)
    backend.start(lambda info: None, on_failure)
    bus.poll_error = ConnectionError("x server gone")
    assert_that(failed.wait(5)).is_true()
    backend.stop()
    assert_that(failures).is_length(1)
    assert_that(str(failures[0])).is_equal_to("x server gone")


def test_normal_stop_does_not_call_on_failure(bus: FakeBus) -> None:
    failures: list[Exception] = []
    backend = X11Backend(bus.factory)
    _collect_started = threading.Event()
    backend.start(lambda info: _collect_started.set(), failures.append)
    assert_that(_collect_started.wait(5)).is_true()
    bus.poll_error = ConnectionError("closing")
    backend.stop()
    threading.Event().wait(0.1)
    assert_that(failures).is_empty()


def test_restart_after_failure(bus: FakeBus) -> None:
    failed = threading.Event()
    backend = X11Backend(bus.factory)
    backend.start(lambda info: None, lambda exc: failed.set())
    bus.poll_error = ConnectionError("gone")
    assert_that(failed.wait(5)).is_true()
    bus.poll_error = None
    got = _collect(backend, bus, 1)
    backend.stop()
    assert_that(got).is_length(1)
    assert_that(bus.transports).is_length(2)
    assert_that(bus.transports[0].closed).is_true()


def test_stop_never_raises_and_is_idempotent(bus: FakeBus) -> None:
    backend = X11Backend(bus.factory)
    backend.stop()
    backend.start(lambda info: None)
    backend.stop()
    backend.stop()


def test_stop_from_listener_thread_does_not_raise(bus: FakeBus) -> None:
    backend = X11Backend(bus.factory)
    errors: list[BaseException] = []
    done = threading.Event()

    def on_change(info: WindowInfo) -> None:
        try:
            backend.stop()
        except BaseException as exc:  # pylint: disable=broad-exception-caught
            errors.append(exc)
        done.set()

    backend.start(on_change)
    assert_that(done.wait(5)).is_true()
    assert_that(errors).is_empty()


def _pick(backend: X11Backend) -> list[WindowInfo | None]:
    results: list[WindowInfo | None] = []
    done = threading.Event()

    def on_result(info: WindowInfo | None) -> None:
        results.append(info)
        done.set()

    backend.pick(on_result)
    assert_that(done.wait(5)).is_true()
    threading.Event().wait(0.05)
    return results


def test_pick_returns_clicked_window_with_configured_timeout(bus: FakeBus) -> None:
    results = _pick(X11Backend(bus.factory, pick_timeout=7.5))
    assert_that(results).is_length(1)
    assert_that(results[0]).is_not_none()
    assert results[0] is not None
    assert_that(results[0].window_class).is_equal_to("konsole")
    assert_that(bus.pick_timeouts).is_equal_to([7.5])
    assert_that(bus.transports[0].closed).is_true()


def test_pick_escape_or_timeout_gives_none(bus: FakeBus) -> None:
    bus.pick_behaviour = lambda transport: None
    assert_that(_pick(X11Backend(bus.factory))).is_equal_to([None])


def test_pick_error_gives_none_once(bus: FakeBus) -> None:
    def fail(transport: FakeX11) -> Mapping[str, Any]:
        raise RuntimeError("grab failed")

    bus.pick_behaviour = fail
    assert_that(_pick(X11Backend(bus.factory))).is_equal_to([None])
    assert_that(bus.transports[0].closed).is_true()


def test_pick_connect_error_gives_none(bus: FakeBus) -> None:
    bus.connect_error = OSError("no display")
    assert_that(_pick(X11Backend(bus.factory))).is_equal_to([None])


def test_concurrent_pick_is_refused_with_none(bus: FakeBus) -> None:
    release = threading.Event()
    entered = threading.Event()

    def slow(transport: FakeX11) -> Mapping[str, Any]:
        entered.set()
        release.wait(5)
        return TERMINAL

    bus.pick_behaviour = slow
    backend = X11Backend(bus.factory)
    first: list[WindowInfo | None] = []
    first_done = threading.Event()

    def on_first(info: WindowInfo | None) -> None:
        first.append(info)
        first_done.set()

    backend.pick(on_first)
    assert_that(entered.wait(5)).is_true()
    second: list[WindowInfo | None] = []
    backend.pick(second.append)
    assert_that(second).is_equal_to([None])
    assert_that(bus.pick_timeouts).is_length(1)
    release.set()
    assert_that(first_done.wait(5)).is_true()
    assert_that(first).is_length(1)
    assert_that(_pick(backend)).is_length(1)


def test_pick_callback_exception_is_contained(bus: FakeBus) -> None:
    done = threading.Event()

    def on_result(info: WindowInfo | None) -> None:
        done.set()
        raise RuntimeError("boom")

    backend = X11Backend(bus.factory)
    backend.pick(on_result)
    assert_that(done.wait(5)).is_true()
    bus.pick_behaviour = lambda transport: None
    assert_that(_pick(backend)).is_equal_to([None])


@pytest.mark.skipif(shutil.which("Xvfb") is None, reason="Xvfb is not installed")
def test_xvfb_private_display_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    number = ":87"
    server = subprocess.Popen(
        ["Xvfb", number, "-nolisten", "tcp"], stderr=subprocess.DEVNULL
    )  # pylint: disable=consider-using-with
    try:
        threading.Event().wait(1.0)
        monkeypatch.setenv("DISPLAY", number)
        assert_that(X11Backend().available().state).is_equal_to("active")
    finally:
        server.terminate()
        server.wait(5)


def test_pick_thread_start_failure_releases_lock_and_reports_none(
    bus: FakeBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = X11Backend(bus.factory)
    results: list[WindowInfo | None] = []

    def refuse(self: threading.Thread) -> None:
        raise RuntimeError("can't start new thread")

    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, "start", refuse)
        backend.pick(results.append)
    assert_that(results).is_equal_to([None])
    assert_that(_pick(backend)).is_length(1)
