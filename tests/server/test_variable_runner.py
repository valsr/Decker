import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that

from decker.plugin.manifest import VariableSpec
from decker.plugin.protocol import Message
from decker.plugin.runtime.supervisor import PluginSupervisor, SupervisorPolicy
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

    def _factory(self, pid: str, _cmd: list[str], _cwd: Path, _env: dict[str, str], on_message: Any, on_exit: Any):
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
    assert_that(_wait_until(lambda: not rig.runner._pending)).is_true()


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
        assert_that(_wait_until(lambda: not rig.runner._pending)).is_true()
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
        assert_that(_wait_until(lambda: _warnings(caplog) != [] and _ask_threads() == 0)).is_true()

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
    assert_that(_wait_until(lambda: not rig.runner._pending)).is_true()

    assert_that(rig.store.snapshot()).is_empty()


def test_malformed_values_are_ignored() -> None:
    rig = Rig()
    rig.plugin("p", "vol")
    for payload in ({}, {"request": 5, "ok": True}, {"request": None}, {"request": [1], "ok": "yes"}):
        rig.runner.on_value("p", payload)

    assert_that(rig.runner._pending).is_empty()


def test_concurrent_asks_for_one_name_settle_on_the_last_answer() -> None:
    rig = Rig()
    rig.plugin("p", "vol")

    rig.runner.ask("p", "vol")
    rig.runner.ask("p", "vol")
    first, second = rig.request("p", "vol", 0), rig.request("p", "vol", 1)
    assert_that(first).is_not_equal_to(second)
    rig.answer("p", {"request": first, "ok": True, "value": "a"})
    assert_that(_wait_until(lambda: rig.store.snapshot().get("vol") == "a")).is_true()
    rig.answer("p", {"request": second, "ok": True, "value": "b"})

    assert_that(_wait_until(lambda: rig.store.snapshot().get("vol") == "b")).is_true()
    assert_that(_wait_until(lambda: not rig.runner._pending)).is_true()


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

        assert_that(_wait_until(lambda: len(rig.runner._pending) == 1, timeout=2.0)).is_true()
        assert_that(_wait_until(lambda: _ask_threads() == 1, timeout=2.0)).is_true()
    assert_that(rig.store.snapshot()).is_equal_to({"vol": "1"})
    assert_that(_warnings(caplog)).is_empty()
    rig.runner.plugin_stopped("q")
    assert_that(_wait_until(lambda: not rig.runner._pending and _ask_threads() == 0, timeout=2.0)).is_true()


def _ask_threads() -> int:
    return sum(1 for t in threading.enumerate() if t.name == "ask-variable" and t.is_alive())


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
