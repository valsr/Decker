import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from assertpy import assert_that

from decker.plugin.manifest import VariableSpec
from decker.plugin.protocol import Message
from decker.plugin.runtime.supervisor import PluginSupervisor, SupervisorPolicy
from decker.server import variable_runner
from decker.server.variable_runner import VariableRunner
from decker.server.variables import VariableStore
from tests.plugin.runtime.test_supervisor import FakeProcess


def _wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class Rig:
    def __init__(self, timeout: float = 2.0) -> None:
        self.procs: dict[str, FakeProcess] = {}
        self.store = VariableStore()
        self.sup = PluginSupervisor(SupervisorPolicy(), self._factory, self._on_message, lambda _pid, _why: None)
        self.runner = VariableRunner(self.sup, self.store, timeout=timeout)

    def _factory(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, pid: str, _cmd: list[str], _cwd: Path, _env: dict[str, str], on_message: Any, on_exit: Any
    ) -> Any:  # a FakeProcess standing in for PluginProcess
        proc = FakeProcess(on_message, on_exit)
        self.procs[pid] = proc
        return proc

    def _on_message(self, plugin_id: str, message: Message) -> None:
        if message.event == "variable_value":
            self.runner.on_value(plugin_id, message.payload)

    def plugin(self, plugin_id: str, *names: str, ready: bool = True) -> FakeProcess:
        self.store.declare(plugin_id, [VariableSpec(name=n, pattern=None) for n in names])
        self.sup.register(plugin_id, ["cmd"], Path("."), {}, {"protocol": 2})
        self.sup.acquire(plugin_id)
        if ready:
            self.procs[plugin_id].emit("ready")
        return self.procs[plugin_id]

    def request(self, plugin_id: str, name: str, index: int = 0) -> str:
        proc = self.procs[plugin_id]

        def asks() -> list[Message]:
            return [m for m in list(proc.sent) if m.event == "get_variable" and m.payload.get("name") == name]

        assert_that(_wait_until(lambda: len(asks()) > index)).is_true()
        return str(asks()[index].payload["request"])

    def answer(self, plugin_id: str, payload: dict[str, Any]) -> None:
        self.procs[plugin_id].on_message(Message("variable_value", None, payload))

    def asks(self, plugin_id: str, name: str) -> int:
        return sum(
            1 for m in list(self.procs[plugin_id].sent) if m.event == "get_variable" and m.payload["name"] == name
        )

    def idle(self) -> bool:
        return not self.runner._pending and not self.runner._inflight


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno == logging.WARNING]


def _pushes(proc: FakeProcess) -> list[dict[str, Any]]:
    return [m.payload for m in list(proc.sent) if m.event == "variables_changed"]


def test_ask_sets_value_from_variable_value() -> None:
    rig = Rig()
    rig.plugin("p", "vol")

    rig.runner.ask("p", "vol")
    rig.answer("p", {"request": rig.request("p", "vol"), "ok": True, "value": 42})

    assert_that(_wait_until(lambda: rig.store.snapshot().get("vol") == "42")).is_true()
    assert_that(_wait_until(rig.idle)).is_true()


def test_ask_null_value_clears() -> None:
    rig = Rig()
    rig.plugin("p", "vol")
    rig.store.set_value("p", "vol", "7")

    rig.runner.ask("p", "vol")
    rig.answer("p", {"request": rig.request("p", "vol"), "ok": True, "value": None})

    assert_that(_wait_until(lambda: "vol" not in rig.store.snapshot())).is_true()


def test_ask_timeout_keeps_old_value(caplog: pytest.LogCaptureFixture) -> None:
    rig = Rig(timeout=0.1)
    rig.plugin("p", "vol")
    rig.store.set_value("p", "vol", "1")

    with caplog.at_level(logging.WARNING):
        rig.runner.ask("p", "vol")
        request = rig.request("p", "vol")
        assert_that(_wait_until(lambda: len(_warnings(caplog)) == 1)).is_true()
        assert_that(_wait_until(rig.idle)).is_true()
        rig.answer("p", {"request": request, "ok": True, "value": "late"})

    assert_that(rig.store.snapshot()).is_equal_to({"vol": "1"})
    assert_that(_warnings(caplog)).is_length(1)
    assert_that(_warnings(caplog)[0].exc_info).is_none()
    assert_that(_warnings(caplog)[0].getMessage()).contains("vol").contains("timed out")


def test_ask_not_ok_keeps_old_value_and_logs_once(caplog: pytest.LogCaptureFixture) -> None:
    rig = Rig()
    rig.plugin("p", "vol")
    rig.store.set_value("p", "vol", "1")

    with caplog.at_level(logging.WARNING):
        rig.runner.ask("p", "vol")
        rig.answer("p", {"request": rig.request("p", "vol"), "ok": False, "error": "ValueError: boom"})
        assert_that(_wait_until(rig.idle)).is_true()

    assert_that(rig.store.snapshot()).is_equal_to({"vol": "1"})
    assert_that(_warnings(caplog)).is_length(1)
    assert_that(_warnings(caplog)[0].exc_info).is_none()
    assert_that(_warnings(caplog)[0].getMessage()).contains("boom")


def test_ask_invalid_value_keeps_old_value(caplog: pytest.LogCaptureFixture) -> None:
    rig = Rig()
    rig.plugin("p", "vol")
    rig.store.set_value("p", "vol", "1")

    with caplog.at_level(logging.WARNING):
        rig.runner.ask("p", "vol")
        rig.answer("p", {"request": rig.request("p", "vol"), "ok": True, "value": {"no": "dicts"}})
        assert_that(_wait_until(lambda: len(_warnings(caplog)) == 1)).is_true()

    assert_that(rig.store.snapshot()).is_equal_to({"vol": "1"})


def test_value_from_another_plugin_or_unknown_request_is_dropped() -> None:
    rig = Rig(timeout=0.2)
    rig.plugin("p", "vol")
    rig.plugin("q", "other")

    rig.runner.ask("p", "vol")
    request = rig.request("p", "vol")
    rig.answer("q", {"request": request, "ok": True, "value": "stolen"})
    rig.answer("p", {"request": "nope", "ok": True, "value": "unknown"})
    assert_that(_wait_until(rig.idle)).is_true()

    assert_that(rig.store.snapshot()).is_empty()


def test_malformed_values_are_ignored() -> None:
    rig = Rig()
    rig.plugin("p", "vol")
    for payload in ({}, {"request": 5, "ok": True}, {"request": None}, {"request": [1], "ok": "yes"}):
        rig.runner.on_value("p", payload)

    assert_that(rig.runner._pending).is_empty()


def test_signal_during_an_ask_asks_once_more_and_keeps_the_newest_value() -> None:
    rig = Rig()
    rig.plugin("p", "vol")

    rig.runner.ask("p", "vol")
    first = rig.request("p", "vol", 0)
    for _ in range(20):
        rig.runner.ask("p", "vol")
    assert_that(rig.asks("p", "vol")).is_equal_to(1)
    rig.answer("p", {"request": first, "ok": True, "value": "a"})
    rig.answer("p", {"request": rig.request("p", "vol", 1), "ok": True, "value": "b"})

    assert_that(_wait_until(rig.idle)).is_true()
    assert_that(rig.store.snapshot()).is_equal_to({"vol": "b"})
    assert_that(rig.asks("p", "vol")).is_equal_to(2)


def test_flood_of_asks_while_failing_sends_two_asks_and_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    rig = Rig()
    rig.plugin("p", "vol")

    with caplog.at_level(logging.WARNING):
        rig.runner.ask("p", "vol")
        first = rig.request("p", "vol", 0)
        for _ in range(200):
            rig.runner.ask("p", "vol")
        rig.answer("p", {"request": first, "ok": False, "error": "boom"})
        rig.answer("p", {"request": rig.request("p", "vol", 1), "ok": False, "error": "boom"})
        assert_that(_wait_until(rig.idle)).is_true()

    assert_that(rig.asks("p", "vol")).is_equal_to(2)
    assert_that(_warnings(caplog)).is_length(1)


def test_failure_warns_again_only_after_a_success(caplog: pytest.LogCaptureFixture) -> None:
    rig = Rig()
    rig.plugin("p", "vol")

    def run(index: int, payload: dict[str, Any]) -> None:
        rig.runner.ask("p", "vol")
        rig.answer("p", {"request": rig.request("p", "vol", index), **payload})
        assert_that(_wait_until(rig.idle)).is_true()

    with caplog.at_level(logging.WARNING):
        run(0, {"ok": False, "error": "one"})
        run(1, {"ok": False, "error": "two"})
        run(2, {"ok": True, "value": 1})
        run(3, {"ok": False, "error": "three"})

    assert_that([r.getMessage() for r in _warnings(caplog)]).is_length(2)
    assert_that(_warnings(caplog)[1].getMessage()).contains("three")
    assert_that(rig.runner._failing).contains(("p", "vol"))
    rig.runner.plugin_stopped("p")
    assert_that(rig.runner._failing).is_empty()


def test_plugin_stopped_before_the_ask_thread_runs_is_not_missed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    deferred: list[tuple[Callable[..., None], tuple[Any, ...]]] = []

    class DeferredThread:
        def __init__(self, target: Callable[..., None], args: tuple[Any, ...] = (), **_kwargs: Any) -> None:
            self._call = (target, args)

        def start(self) -> None:
            deferred.append(self._call)

    fake = SimpleNamespace(Thread=DeferredThread, Lock=threading.Lock, Event=threading.Event)
    monkeypatch.setattr(variable_runner, "threading", fake)
    rig = Rig(timeout=30.0)
    rig.plugin("p", "vol")

    with caplog.at_level(logging.WARNING):
        rig.runner.ask("p", "vol")
        rig.runner.plugin_stopped("p")
        for target, args in deferred:
            threading.Thread(target=target, args=args, daemon=True).start()
        assert_that(_wait_until(rig.idle, timeout=2.0)).is_true()

    assert_that(deferred).is_length(1)
    assert_that(rig.asks("p", "vol")).is_equal_to(0)
    assert_that(_warnings(caplog)).is_empty()


def test_stop_all_releases_every_pending_ask() -> None:
    rig = Rig(timeout=30.0)
    rig.plugin("p", "vol")
    rig.plugin("q", "other")
    rig.runner.ask("p", "vol")
    rig.runner.ask("q", "other")
    rig.request("p", "vol")
    rig.request("q", "other")

    rig.runner.stop_all()

    assert_that(_wait_until(rig.idle, timeout=2.0)).is_true()
    rig.runner.ask("p", "vol")
    assert_that(rig.idle()).is_true()


def test_plugin_stopped_releases_pending_ask(caplog: pytest.LogCaptureFixture) -> None:
    rig = Rig(timeout=30.0)
    rig.plugin("p", "vol")
    rig.plugin("q", "other")
    rig.store.set_value("p", "vol", "1")

    with caplog.at_level(logging.WARNING):
        rig.runner.ask("p", "vol")
        rig.runner.ask("q", "other")
        rig.request("p", "vol")
        rig.request("q", "other")
        rig.runner.plugin_stopped("p")

        assert_that(_wait_until(lambda: list(rig.runner._inflight) == [("q", "other")], timeout=2.0)).is_true()
        assert_that([p.plugin_id for p in rig.runner._pending.values()]).is_equal_to(["q"])
    assert_that(rig.store.snapshot()).is_equal_to({"vol": "1"})
    assert_that(_warnings(caplog)).is_empty()
    rig.runner.plugin_stopped("q")
    assert_that(_wait_until(rig.idle, timeout=2.0)).is_true()


def test_push_reaches_one_ready_plugin() -> None:
    rig = Rig()
    p = rig.plugin("p", "vol")
    q = rig.plugin("q", "other")

    rig.runner.push("p", {"vol": "1"}, ["gone"])

    assert_that(_pushes(p)).is_equal_to([{"set": {"vol": "1"}, "removed": ["gone"]}])
    assert_that(_pushes(q)).is_empty()


def test_push_to_all_skips_plugins_that_are_not_ready() -> None:
    rig = Rig()
    p = rig.plugin("p", "vol")
    q = rig.plugin("q", "other")
    r = rig.plugin("r", "third", ready=False)

    rig.runner.push(None, {"vol": "1"}, [])
    r.emit("ready")

    assert_that(_pushes(p)).is_equal_to([{"set": {"vol": "1"}, "removed": []}])
    assert_that(_pushes(q)).is_equal_to([{"set": {"vol": "1"}, "removed": []}])
    assert_that(_pushes(r)).is_empty()


def test_changed_pushes_current_values_and_removals() -> None:
    rig = Rig()
    p = rig.plugin("p", "vol", "mute")
    rig.store.set_value("p", "vol", "3")

    rig.runner.changed(frozenset({"vol", "mute"}))

    assert_that(_pushes(p)).is_equal_to([{"set": {"vol": "3"}, "removed": ["mute"]}])


def test_send_snapshot_sends_every_value() -> None:
    rig = Rig()
    p = rig.plugin("p", "vol", "mute")
    rig.store.set_value("p", "vol", "3")
    rig.store.set_value("p", "mute", "true")

    rig.runner.send_snapshot("p")

    assert_that(_pushes(p)).is_equal_to([{"set": {"mute": "true", "vol": "3"}, "removed": []}])


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_raising_send_does_not_block_the_variable_forever() -> None:
    rig = Rig()
    rig.plugin("p", "vol")
    real_send = rig.sup.send
    calls: list[int] = []

    def flaky(plugin_id: str, message: Message) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        real_send(plugin_id, message)

    rig.sup.send = flaky  # type: ignore[method-assign]
    rig.runner.ask("p", "vol")
    assert_that(_wait_until(rig.idle)).is_true()

    rig.runner.ask("p", "vol")

    assert_that(rig.request("p", "vol", 0)).is_not_empty()
