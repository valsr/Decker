import json
import os
import threading
from pathlib import Path
from typing import Any

import psutil
import pytest
from assertpy import assert_that

from decker.common.model import WindowInfo
from decker.server.window_watcher import WatcherTimings
from decker.server.windows.backend import BackendStatus
from decker.server.windows.kwin import (
    PICK_TIMEOUT,
    SCRIPT_NAME,
    DBusCall,
    DBusError,
    DBusTransport,
    KWinBackend,
    window_from_kwin,
)

FIXTURES = Path(__file__).parent / "fixtures"
FOCUS = json.loads((FIXTURES / "kwin_focus.json").read_text())["samples"]
PICK = json.loads((FIXTURES / "kwin_pick.json").read_text())


class FakeTransport:
    def __init__(self, log: list[tuple[str, Any]], bus: "FakeBus") -> None:
        self.log = log
        self.bus = bus
        self.incoming: list[str] = []
        self.closed = False

    def request_name(self, name: str) -> int:
        self.log.append(("request_name", name))
        return self.bus.request_reply

    def release_name(self, name: str) -> None:
        self.log.append(("release_name", name))

    def call(self, request: DBusCall, timeout: float) -> tuple[Any, ...]:
        self.log.append((request.member, request.args))
        if request.member == "queryWindowInfo":
            return self.bus.query(self)
        if request.member in self.bus.errors:
            raise self.bus.errors[request.member]
        return self.bus.results.get(request.member, (True,))

    def poll(self, timeout: float) -> str | None:
        if self.incoming:
            return self.incoming.pop(0)
        if self.bus.poll_error is not None:
            raise self.bus.poll_error
        threading.Event().wait(min(timeout, 0.01))
        return None

    def close(self) -> None:
        self.closed = True


class FakeBus:
    def __init__(self) -> None:
        self.log: list[tuple[str, Any]] = []
        self.request_reply = 1
        self.results: dict[str, tuple[Any, ...]] = {"loadScript": (7,)}
        self.errors: dict[str, Exception] = {}
        self.connect_error: Exception | None = None
        self.poll_error: Exception | None = None
        self.transports: list[FakeTransport] = []
        self.query: Any = lambda transport: (_variants(PICK),)

    def factory(self) -> DBusTransport:
        if self.connect_error:
            raise self.connect_error
        transport = FakeTransport(self.log, self)
        self.transports.append(transport)
        return transport


def _variants(pick: dict[str, Any]) -> dict[str, tuple[str, Any]]:
    return {key: (pick["signatures"][key], value) for key, value in pick["info"].items()}


@pytest.fixture(name="bus")
def bus_fixture() -> FakeBus:
    return FakeBus()


def test_window_from_kwin_maps_fixture_payloads() -> None:
    mine = psutil.Process(os.getpid())
    native = window_from_kwin(FOCUS["native_wayland"])
    assert_that(native).is_equal_to(
        WindowInfo("org.kde.dolphin", "normal", "Example folder — Dolphin", "", "org.kde.dolphin", 11111)
    )
    dialog = window_from_kwin(FOCUS["dialog_xwayland"])
    assert_that(dialog.window_type).is_equal_to("dialog")
    assert_that(dialog.window_class).is_equal_to("qtdlg.py")
    assert_that(window_from_kwin(FOCUS["xwayland"]).desktop_file).is_equal_to("")
    own = window_from_kwin({"resourceClass": "x", "pid": mine.pid})
    assert_that(own.executable).is_equal_to(os.path.basename(mine.exe()))


def test_window_from_kwin_gone_process_has_empty_executable() -> None:
    assert_that(window_from_kwin({"pid": 2**22 + 12345}).executable).is_equal_to("")
    assert_that(window_from_kwin({}).pid).is_equal_to(0)


def test_query_window_info_result_maps_to_window_info() -> None:
    info = window_from_kwin(PICK["info"])
    assert_that(info.window_class).is_equal_to("org.kde.konsole")
    assert_that(info.title).is_equal_to("Example window - Konsole")
    assert_that(info.desktop_file).is_equal_to("org.kde.konsole")
    assert_that(info.window_type).is_equal_to("normal")
    assert_that(info.pid).is_equal_to(44444)


@pytest.mark.parametrize(
    "net_type,name",
    [(0, "normal"), (1, "desktop"), (2, "dock"), (3, "toolbar"), (4, "menu"), (5, "dialog"), (8, "utility"),
     (9, "splash"), (13, "notification"), (16, "onscreendisplay"), (17, "criticalnotification")],
)  # fmt: skip
def test_pick_type_maps_to_the_names_the_focus_script_emits(net_type: int, name: str) -> None:
    assert_that(window_from_kwin({**PICK["info"], "type": net_type}).window_type).is_equal_to(name)


def test_kwin_picker_does_not_outlive_the_watcher_token() -> None:
    assert_that(PICK_TIMEOUT).is_less_than_or_equal_to(WatcherTimings().pick_timeout)


def test_start_unloads_stale_script_first(bus: FakeBus) -> None:
    backend = KWinBackend(bus.factory)
    backend.start(lambda info: None)
    backend.stop()
    members = [entry[0] for entry in bus.log]
    assert_that(members.index("unloadScript")).is_less_than(members.index("loadScript"))
    assert_that(members.index("loadScript")).is_less_than(members.index("start"))
    assert_that(members.index("request_name")).is_less_than(members.index("unloadScript"))
    assert_that(bus.log).contains(("loadScript", (str(Path(KWinBackend.script_path())), SCRIPT_NAME)))


def test_start_delivers_focus_events(bus: FakeBus) -> None:
    got: list[WindowInfo] = []
    seen = threading.Event()

    def on_change(info: WindowInfo) -> None:
        got.append(info)
        seen.set()

    backend = KWinBackend(bus.factory)
    backend.start(on_change)
    receiver = bus.transports[0]
    receiver.incoming.extend(["not json", json.dumps(FOCUS["native_wayland"])])
    assert_that(seen.wait(2)).is_true()
    backend.stop()
    assert_that(got).is_length(1)
    assert_that(got[0].window_class).is_equal_to("org.kde.dolphin")


def test_listener_failure_calls_on_failure_once(bus: FakeBus) -> None:
    failures: list[Exception] = []
    called = threading.Event()

    def on_failure(exc: Exception) -> None:
        failures.append(exc)
        called.set()

    bus.poll_error = OSError("socket gone")
    backend = KWinBackend(bus.factory)
    backend.start(lambda info: None, on_failure)
    assert_that(called.wait(2)).is_true()
    backend.stop()
    assert_that(failures).is_length(1)
    assert_that(failures[0]).is_same_as(bus.poll_error)


def test_restart_after_listener_failure_succeeds(bus: FakeBus) -> None:
    called = threading.Event()
    bus.poll_error = OSError("socket gone")
    backend = KWinBackend(bus.factory)
    backend.start(lambda info: None, lambda exc: called.set())
    assert_that(called.wait(2)).is_true()
    bus.poll_error = None
    backend.stop()
    backend.start(lambda info: None)
    backend.stop()
    assert_that([e[0] for e in bus.log].count("loadScript")).is_equal_to(2)


def test_normal_stop_does_not_call_on_failure(bus: FakeBus) -> None:
    failures: list[Exception] = []
    backend = KWinBackend(bus.factory)
    backend.start(lambda info: None, failures.append)
    backend.stop()
    threading.Event().wait(0.1)
    assert_that(failures).is_empty()


def test_stop_from_listener_thread_does_not_raise(bus: FakeBus) -> None:
    backend = KWinBackend(bus.factory)
    errors: list[BaseException] = []
    done = threading.Event()

    def on_change(info: WindowInfo) -> None:
        try:
            backend.stop()
        except BaseException as exc:  # pylint: disable=broad-exception-caught
            errors.append(exc)
        done.set()

    backend.start(on_change)
    bus.transports[0].incoming.append(json.dumps(FOCUS["native_wayland"]))
    assert_that(done.wait(2)).is_true()
    assert_that(errors).is_empty()


def test_absurd_pid_does_not_kill_listener(bus: FakeBus) -> None:
    got: list[WindowInfo] = []
    seen = threading.Event()

    def on_change(info: WindowInfo) -> None:
        got.append(info)
        seen.set()

    backend = KWinBackend(bus.factory)
    backend.start(on_change)
    bus.transports[0].incoming.extend(['{"pid": 1e999}', json.dumps(FOCUS["native_wayland"])])
    assert_that(seen.wait(2)).is_true()
    backend.stop()
    assert_that(got).is_length(1)


def test_stop_unloads_script_releases_name_and_never_raises(bus: FakeBus) -> None:
    backend = KWinBackend(bus.factory)
    backend.start(lambda info: None)
    bus.errors["unloadScript"] = DBusError("org.freedesktop.DBus.Error.Failed")
    backend.stop()
    backend.stop()
    assert_that(bus.log).contains(("release_name", "org.decker.WindowWatcher"))
    assert_that([t.closed for t in bus.transports]).contains_only(True)


def test_start_raises_when_bus_name_taken(bus: FakeBus) -> None:
    bus.request_reply = 2
    backend = KWinBackend(bus.factory)
    with pytest.raises(RuntimeError, match="org.decker.WindowWatcher"):
        backend.start(lambda info: None)
    assert_that([entry[0] for entry in bus.log]).does_not_contain("loadScript")
    assert_that([t.closed for t in bus.transports]).contains_only(True)


def test_start_raises_when_script_fails_to_load(bus: FakeBus) -> None:
    bus.results["loadScript"] = (-1,)
    with pytest.raises(RuntimeError, match="load"):
        KWinBackend(bus.factory).start(lambda info: None)
    assert_that([t.closed for t in bus.transports]).contains_only(True)


def test_unavailable_when_no_session_bus(bus: FakeBus) -> None:
    bus.connect_error = OSError("no bus")
    status = KWinBackend(bus.factory).available()
    assert_that(status.state).is_equal_to("unavailable")
    assert_that(status.reason).contains("session bus")


def test_unavailable_when_kwin_missing(bus: FakeBus) -> None:
    bus.results["NameHasOwner"] = (False,)
    status = KWinBackend(bus.factory).available()
    assert_that(status.state).is_equal_to("unavailable")
    assert_that(status.reason).contains("org.kde.KWin")


def test_unavailable_when_kwin_older_than_6(bus: FakeBus) -> None:
    bus.results["NameHasOwner"] = (True,)
    bus.results["supportInformation"] = ("KWin version: 5.27.11\n",)
    status = KWinBackend(bus.factory).available()
    assert_that(status.state).is_equal_to("unavailable")
    assert_that(status.reason).contains("6")


def test_available_with_kwin_6(bus: FakeBus) -> None:
    bus.results["NameHasOwner"] = (True,)
    bus.results["supportInformation"] = ("KWin version: 6.7.5\n",)
    assert_that(KWinBackend(bus.factory).available()).is_equal_to(BackendStatus("active"))
    assert_that([t.closed for t in bus.transports]).contains_only(True)


def _pick(backend: KWinBackend) -> list[WindowInfo | None]:
    results: list[WindowInfo | None] = []
    done = threading.Event()

    def on_result(info: WindowInfo | None) -> None:
        results.append(info)
        done.set()

    backend.pick(on_result)
    assert_that(done.wait(2)).is_true()
    return results


def test_pick_returns_window_info(bus: FakeBus) -> None:
    results = _pick(KWinBackend(bus.factory))
    assert_that(results).is_length(1)
    assert results[0] is not None
    assert_that(results[0].window_class).is_equal_to("org.kde.konsole")


def test_pick_cancel_returns_none(bus: FakeBus) -> None:
    def cancel(transport: FakeTransport) -> tuple[Any, ...]:
        raise DBusError("org.kde.KWin.Error.UserCancel")

    bus.query = cancel
    assert_that(_pick(KWinBackend(bus.factory))).is_equal_to([None])


def test_pick_error_returns_none_exactly_once(bus: FakeBus) -> None:
    def fail(transport: FakeTransport) -> tuple[Any, ...]:
        raise TimeoutError("timed out")

    bus.query = fail
    assert_that(_pick(KWinBackend(bus.factory))).is_equal_to([None])


def test_pick_connection_failure_returns_none(bus: FakeBus) -> None:
    bus.connect_error = OSError("no bus")
    assert_that(_pick(KWinBackend(bus.factory))).is_equal_to([None])


def test_concurrent_pick_is_refused_without_a_second_query(bus: FakeBus) -> None:
    release = threading.Event()
    entered = threading.Event()
    queries: list[int] = []

    def slow(transport: FakeTransport) -> tuple[Any, ...]:
        queries.append(1)
        entered.set()
        release.wait(2)
        return (_variants(PICK),)

    bus.query = slow
    backend = KWinBackend(bus.factory)
    first: list[WindowInfo | None] = []
    first_done = threading.Event()

    def record(info: WindowInfo | None) -> None:
        first.append(info)
        first_done.set()

    backend.pick(record)
    assert_that(entered.wait(2)).is_true()
    assert_that(_pick(backend)).is_equal_to([None])
    assert_that(queries).is_length(1)
    release.set()
    assert_that(first_done.wait(2)).is_true()
    assert_that(first).is_length(1)
    assert first[0] is not None
    assert_that(_pick(backend)).is_length(1)


def test_supports_pick_and_name() -> None:
    assert_that(KWinBackend.name).is_equal_to("kwin")
    assert_that(KWinBackend.supports_pick).is_true()
    assert_that(KWinBackend.script_path().is_file()).is_true()


@pytest.mark.skipif(
    os.environ.get("DECKER_LIVE_DESKTOP_TESTS") != "1" or not os.environ.get("DBUS_SESSION_BUS_ADDRESS"),
    reason="set DECKER_LIVE_DESKTOP_TESTS=1 on a live Plasma session to run",
)
def test_live_kwin_loads_script_and_reports_initial_focus() -> None:
    backend = KWinBackend()
    if backend.available().state != "active":
        pytest.skip("org.kde.KWin 6 not present on the session bus")
    seen = threading.Event()
    got: list[WindowInfo] = []

    def on_change(info: WindowInfo) -> None:
        got.append(info)
        seen.set()

    backend.start(on_change)
    try:
        assert_that(seen.wait(5)).is_true()
    finally:
        backend.stop()
    assert_that(got[0].window_class or got[0].title).is_not_empty()
