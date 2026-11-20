import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that

from decker.plugin.loader import InstalledPlugin
from decker.plugin.manifest import PluginManifest
from decker.plugin.protocol import Message
from decker.plugin.settings_store import PluginSettingsStore
from decker.server.plugins import PluginManager
from tests.plugin.runtime.test_supervisor import FakeProcess


def _plugin(tmp_path: Path, plugin_id: str, variables: list[dict[str, Any]]) -> InstalledPlugin:
    data = {
        "format": 2,
        "id": plugin_id,
        "name": "V",
        "version": "1.0.0",
        "author": "a",
        "decker": ">=0.6",
        "runtime": {"type": "python", "entry": "plugin.py"},
        "contributes": {"variables": variables},
    }
    return InstalledPlugin(PluginManifest.from_dict(data), tmp_path)


def _manager(tmp_path: Path) -> PluginManager:
    manager = PluginManager(tmp_path / "plugins", settings_store=PluginSettingsStore(tmp_path / "plugins.db"))
    manager._sdk_path = tmp_path  # pylint: disable=protected-access  # the process is never started here
    return manager


def test_adding_plugin_declares_variables(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    try:
        manager.add_plugin(_plugin(tmp_path, "com.t.one", [{"name": "media_volume"}, {"pattern": "m_{x}_v"}]))

        assert_that(manager.variables.owner_of("media_volume")).is_equal_to("com.t.one")
        assert_that(manager.variables.owner_of("m_a_v")).is_equal_to("com.t.one")
        assert_that(manager.load_failures()).is_empty()
    finally:
        manager.destroy()


def test_second_plugin_with_same_name_fails_to_load_and_first_keeps_working(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    try:
        manager.add_plugin(_plugin(tmp_path, "com.t.one", [{"name": "media_volume"}]))
        manager.add_plugin(_plugin(tmp_path, "com.t.two", [{"name": "other_one"}, {"name": "media_volume"}]))

        assert_that(manager.variables.owner_of("media_volume")).is_equal_to("com.t.one")
        assert_that(manager.variables.owner_of("other_one")).is_none()
        failures = manager.load_failures()
        assert_that([f.plugin_uuid for f in failures]).is_equal_to(["com.t.two"])
        assert_that(failures[0].error).contains("media_volume")
        assert_that(manager._supervisor._entries).contains_key("com.t.one").does_not_contain_key("com.t.two")
    finally:
        manager.destroy()


def test_removing_plugin_frees_its_names(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    try:
        manager.add_plugin(_plugin(tmp_path, "com.t.one", [{"name": "media_volume"}]))
        manager.remove_plugin("com.t.one")

        assert_that(manager.variables.owner_of("media_volume")).is_none()
        manager.add_plugin(_plugin(tmp_path, "com.t.two", [{"name": "media_volume"}]))
        assert_that(manager.variables.owner_of("media_volume")).is_equal_to("com.t.two")
    finally:
        manager.destroy()


def _fake_processes(manager: PluginManager) -> dict[str, FakeProcess]:
    procs: dict[str, FakeProcess] = {}

    def factory(pid: str, _cmd: list[str], _cwd: Path, _env: dict[str, str], on_message: Any, on_exit: Any) -> Any:
        procs[pid] = FakeProcess(on_message, on_exit)
        return procs[pid]

    manager._supervisor._factory = factory  # pylint: disable=protected-access
    return procs


def _started(manager: PluginManager, procs: dict[str, FakeProcess], plugin: InstalledPlugin) -> FakeProcess:
    manager.add_plugin(plugin)
    manager._supervisor.acquire(plugin.manifest.id)  # pylint: disable=protected-access
    proc = procs[plugin.manifest.id]
    proc.emit("ready")
    return proc


def _wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def _asks(proc: FakeProcess, name: str) -> list[Message]:
    return [m for m in list(proc.sent) if m.event == "get_variable" and m.payload.get("name") == name]


def _pushes(proc: FakeProcess) -> list[dict[str, Any]]:
    return [m.payload for m in list(proc.sent) if m.event == "variables_changed"]


def _send(proc: FakeProcess, event: str, payload: dict[str, Any]) -> None:
    proc.on_message(Message(event, None, payload))


def _answer(proc: FakeProcess, name: str, value: Any, index: int = 0) -> None:
    assert_that(_wait_until(lambda: len(_asks(proc, name)) > index)).is_true()
    request = _asks(proc, name)[index].payload["request"]
    _send(proc, "variable_value", {"request": request, "ok": True, "value": value})


def test_hello_protocol_is_2(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    procs = _fake_processes(manager)
    try:
        proc = _started(manager, procs, _plugin(tmp_path, "com.t.one", [{"name": "media_volume"}]))

        assert_that(proc.sent[0].event).is_equal_to("hello")
        assert_that(proc.sent[0].payload["protocol"]).is_equal_to(2)
    finally:
        manager.destroy()


def test_ready_sends_snapshot_then_asks_registered_names(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    procs = _fake_processes(manager)
    try:
        one = _started(manager, procs, _plugin(tmp_path, "com.t.one", [{"name": "a_vol"}]))
        _answer(one, "a_vol", 5)
        assert_that(_wait_until(lambda: manager.variables.snapshot() == {"a_vol": "5"})).is_true()

        two = _started(manager, procs, _plugin(tmp_path, "com.t.two", [{"name": "b_x"}, {"name": "b_y"}]))

        assert_that(_wait_until(lambda: len(_asks(two, "b_x")) == 1 and len(_asks(two, "b_y")) == 1)).is_true()
        events = [m.event for m in two.sent]
        assert_that(events.index("variables_changed")).is_less_than(events.index("get_variable"))
        assert_that(_pushes(two)[0]).is_equal_to({"set": {"a_vol": "5"}, "removed": []})
    finally:
        manager.destroy()


def test_register_concrete_name_triggers_ask(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    procs = _fake_processes(manager)
    try:
        proc = _started(manager, procs, _plugin(tmp_path, "com.t.one", [{"pattern": "m_{x}_v"}]))

        _send(proc, "register_variable", {"name": "m_a_v"})
        _answer(proc, "m_a_v", "loud")

        assert_that(_wait_until(lambda: manager.variables.snapshot() == {"m_a_v": "loud"})).is_true()
        assert_that(manager.variables.registered_names("com.t.one")).is_equal_to(["m_a_v"])
    finally:
        manager.destroy()


def test_rejected_register_is_ignored(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    procs = _fake_processes(manager)
    try:
        proc = _started(manager, procs, _plugin(tmp_path, "com.t.one", [{"pattern": "m_{x}_v"}]))

        _send(proc, "register_variable", {"name": "other_name"})
        time.sleep(0.1)

        assert_that(_asks(proc, "other_name")).is_empty()
        assert_that(manager.variables.registered_names("com.t.one")).is_empty()
    finally:
        manager.destroy()


def test_variable_updated_triggers_ask(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    procs = _fake_processes(manager)
    try:
        proc = _started(manager, procs, _plugin(tmp_path, "com.t.one", [{"name": "a_vol"}]))
        _answer(proc, "a_vol", 1)

        _send(proc, "variable_updated", {"name": "a_vol"})
        _answer(proc, "a_vol", 2, index=1)

        assert_that(_wait_until(lambda: manager.variables.snapshot() == {"a_vol": "2"})).is_true()
    finally:
        manager.destroy()


def test_update_from_non_owner_is_ignored(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    procs = _fake_processes(manager)
    try:
        one = _started(manager, procs, _plugin(tmp_path, "com.t.one", [{"name": "a_vol"}, {"pattern": "m_{x}_v"}]))
        two = _started(manager, procs, _plugin(tmp_path, "com.t.two", [{"name": "b_x"}]))
        assert_that(_wait_until(lambda: len(_asks(one, "a_vol")) == 1)).is_true()

        _send(two, "variable_updated", {"name": "a_vol"})
        _send(one, "variable_updated", {"name": "m_q_v"})  # its own pattern, but never registered
        time.sleep(0.1)

        assert_that(_asks(one, "a_vol")).is_length(1)
        assert_that(_asks(two, "a_vol")).is_empty()
        assert_that(_asks(one, "m_q_v")).is_empty()
    finally:
        manager.destroy()


def test_change_pushes_variables_changed_to_ready_plugins(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    procs = _fake_processes(manager)
    try:
        one = _started(manager, procs, _plugin(tmp_path, "com.t.one", [{"name": "a_vol"}]))
        two = _started(manager, procs, _plugin(tmp_path, "com.t.two", [{"name": "b_x"}]))
        manager.add_plugin(_plugin(tmp_path, "com.t.idle", [{"name": "c_x"}]))

        _answer(one, "a_vol", 42)

        expected = {"set": {"a_vol": "42"}, "removed": []}
        assert_that(_wait_until(lambda: expected in _pushes(one) and expected in _pushes(two))).is_true()
        assert_that(procs).does_not_contain_key("com.t.idle")
    finally:
        manager.destroy()


def test_unregister_variable_pushes_removal(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    procs = _fake_processes(manager)
    try:
        proc = _started(manager, procs, _plugin(tmp_path, "com.t.one", [{"pattern": "m_{x}_v"}]))
        _send(proc, "register_variable", {"name": "m_a_v"})
        _answer(proc, "m_a_v", "loud")
        assert_that(_wait_until(lambda: manager.variables.snapshot() == {"m_a_v": "loud"})).is_true()

        _send(proc, "unregister_variable", {"name": "m_a_v"})

        assert_that(manager.variables.snapshot()).is_empty()
        assert_that(_pushes(proc)[-1]).is_equal_to({"set": {}, "removed": ["m_a_v"]})
    finally:
        manager.destroy()


def test_malformed_variable_payloads_are_ignored(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    manager = _manager(tmp_path)
    procs = _fake_processes(manager)
    try:
        proc = _started(manager, procs, _plugin(tmp_path, "com.t.one", [{"name": "a_vol"}]))
        with caplog.at_level(logging.ERROR):
            for event in ("register_variable", "unregister_variable", "variable_updated"):
                for payload in ({}, {"name": 5}, {"name": None}, {"name": ["a_vol"]}):
                    _send(proc, event, payload)
            values: list[dict[str, Any]] = [{}, {"request": 3, "ok": True, "value": "x"}, {"request": "r", "ok": "yes"}]
            for value in values:
                _send(proc, "variable_value", value)

        assert_that([r for r in caplog.records if r.levelno >= logging.ERROR]).is_empty()
        assert_that(_asks(proc, "a_vol")).is_length(1)
    finally:
        manager.destroy()


def test_removing_plugin_releases_its_pending_asks(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    procs = _fake_processes(manager)
    try:
        proc = _started(manager, procs, _plugin(tmp_path, "com.t.one", [{"name": "a_vol"}]))
        assert_that(_wait_until(lambda: len(_asks(proc, "a_vol")) == 1)).is_true()

        manager.remove_plugin("com.t.one")

        runner = manager._variable_runner  # pylint: disable=protected-access
        assert_that(_wait_until(lambda: not runner._pending and not runner._inflight, timeout=2.0)).is_true()
    finally:
        manager.destroy()


def test_destroy_releases_pending_asks(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    procs = _fake_processes(manager)
    proc = _started(manager, procs, _plugin(tmp_path, "com.t.one", [{"name": "a_vol"}]))
    assert_that(_wait_until(lambda: len(_asks(proc, "a_vol")) == 1)).is_true()
    runner = manager._variable_runner  # pylint: disable=protected-access

    manager.destroy()

    assert_that(_wait_until(lambda: not runner._pending and not runner._inflight, timeout=1.0)).is_true()
