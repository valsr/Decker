import asyncio
import json
import os
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from assertpy import assert_that

import decker_plugin_sdk as sdk
from decker_plugin_sdk import _variables, run

WAIT = 5.0


class Rig:
    """Runs the SDK loop on os.pipe streams."""

    def __init__(self, actions: dict[str, Any] | None = None) -> None:
        in_r, in_w = os.pipe()
        out_r, out_w = os.pipe()
        self.to_plugin = os.fdopen(in_w, "wb")
        self._plugin_in = os.fdopen(in_r, "rb")
        self._plugin_out = os.fdopen(out_w, "wb")
        self.from_plugin = os.fdopen(out_r, "rb")
        self.code: list[int] = []
        self.thread = threading.Thread(
            target=lambda: self.code.append(run({}, self._plugin_in, self._plugin_out, actions or {}))
        )
        self.thread.start()

    def send(self, event: str, payload: dict | None = None) -> None:
        data: dict[str, Any] = {"event": event}
        if payload is not None:
            data["payload"] = payload
        self.to_plugin.write(json.dumps(data).encode() + b"\n")
        self.to_plugin.flush()

    def recv_until(self, event: str) -> dict:
        while True:
            line = self.from_plugin.readline()
            assert line, "plugin closed stdout"
            message = json.loads(line)
            if message["event"] == event:
                return message

    def hello(self) -> None:
        self.send("hello", {"protocol": 1, "decker_version": "x", "plugin_id": "t", "global_settings": {}})
        self.recv_until("ready")

    def stop(self) -> None:
        if self.thread.is_alive():
            self.send("shutdown")
        self.thread.join(WAIT)
        for stream in (self.to_plugin, self._plugin_in, self._plugin_out, self.from_plugin):
            stream.close()


@pytest.fixture(name="rigs")
def rigs_fixture() -> Iterator[list[Rig]]:
    _variables.reset()
    made: list[Rig] = []
    yield made
    for rig in made:
        rig.stop()
    _variables.reset()


def _start(rigs: list[Rig], actions: dict[str, Any] | None = None) -> Rig:
    rig = Rig(actions)
    rigs.append(rig)
    return rig


def _wait_for(predicate: Any) -> None:
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


def test_init_runs_after_ready_in_its_own_thread(rigs: list[Rig]) -> None:
    seen: dict[str, Any] = {}

    @sdk.init
    def setup(ctx: sdk.PluginContext) -> None:
        seen["thread"] = threading.current_thread()
        seen["ctx"] = ctx

    rig = _start(rigs)
    time.sleep(0.05)
    assert_that(seen).is_empty()
    rig.hello()
    _wait_for(lambda: "ctx" in seen)
    assert_that(seen["thread"]).is_not_equal_to(threading.main_thread())
    assert_that(seen["ctx"]).is_instance_of(sdk.PluginContext)


def test_init_exception_skips_main_but_actions_still_run(rigs: list[Rig]) -> None:
    calls: list[int] = []

    @sdk.init
    def setup(ctx: sdk.PluginContext) -> None:
        raise RuntimeError("boom")

    @sdk.main(0.01)
    def loop(ctx: sdk.PluginContext) -> None:
        calls.append(1)

    rig = _start(rigs, {"t.act": lambda settings: None})
    rig.hello()
    log = rig.recv_until("log")
    assert_that(log["payload"]["level"]).is_equal_to("error")
    assert_that(log["payload"]["message"]).contains("boom")
    rig.send("run_action", {"request": 7, "action": "t.act", "settings": {}})
    assert_that(rig.recv_until("action_result")["payload"]["ok"]).is_true()
    assert_that(calls).is_empty()


def test_main_called_at_interval(rigs: list[Rig]) -> None:
    calls: list[int] = []

    @sdk.main(0.05)
    def loop(ctx: sdk.PluginContext) -> None:
        calls.append(1)

    _start(rigs).hello()
    _wait_for(lambda: len(calls) >= 3)


def test_main_exception_is_logged_and_loop_continues(rigs: list[Rig]) -> None:
    calls: list[int] = []

    @sdk.main(interval=0.02)
    def loop(ctx: sdk.PluginContext) -> None:
        calls.append(1)
        raise ValueError("again")

    rig = _start(rigs)
    rig.hello()
    assert_that(rig.recv_until("log")["payload"]["message"]).contains("again")
    _wait_for(lambda: len(calls) >= 2)


def test_shutdown_stops_main_promptly(rigs: list[Rig]) -> None:
    calls: list[int] = []

    @sdk.main(5)
    def loop(ctx: sdk.PluginContext) -> None:
        calls.append(1)

    rig = _start(rigs)
    rig.hello()
    _wait_for(lambda: calls)
    started = time.monotonic()
    rig.send("shutdown")
    rig.thread.join(WAIT)
    assert_that(rig.thread.is_alive()).is_false()
    lifecycle = [t for t in threading.enumerate() if t.name == "decker-sdk-lifecycle"]
    for thread in lifecycle:
        thread.join(1)
    assert_that(time.monotonic() - started).is_less_than(1)
    assert_that([t for t in threading.enumerate() if t.name == "decker-sdk-lifecycle"]).is_empty()


def test_async_main_without_interval_runs_once_and_is_cancelled(rigs: list[Rig]) -> None:
    state: dict[str, Any] = {"starts": 0, "cancelled": False}

    @sdk.main(interval=None)
    async def loop(ctx: sdk.PluginContext) -> None:
        state["starts"] += 1
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    rig = _start(rigs)
    rig.hello()
    _wait_for(lambda: state["starts"] == 1)
    time.sleep(0.1)
    assert_that(state["starts"]).is_equal_to(1)
    rig.send("shutdown")
    _wait_for(lambda: state["cancelled"])


def test_no_hooks_starts_no_lifecycle_thread(rigs: list[Rig]) -> None:
    _start(rigs).hello()
    time.sleep(0.05)
    assert_that([t for t in threading.enumerate() if t.name == "decker-sdk-lifecycle"]).is_empty()


def test_get_variable_request_answered_exact(rigs: list[Rig]) -> None:
    @sdk.variable("volume")
    def volume() -> int:
        return 42

    rig = _start(rigs)
    rig.hello()
    rig.send("get_variable", {"request": 1, "name": "volume"})
    assert_that(rig.recv_until("variable_value")["payload"]).is_equal_to({"request": 1, "ok": True, "value": "42"})


def test_get_variable_request_pattern_passes_placeholders(rigs: list[Rig]) -> None:
    @sdk.variable("mute_{device}")
    async def mute(device: str) -> bool:
        return device == "speakers"

    rig = _start(rigs)
    rig.hello()
    rig.send("get_variable", {"request": 2, "name": "mute_speakers"})
    assert_that(rig.recv_until("variable_value")["payload"]["value"]).is_equal_to("true")
    rig.send("get_variable", {"request": 3, "name": "mute_mic"})
    assert_that(rig.recv_until("variable_value")["payload"]["value"]).is_equal_to("false")


def test_get_variable_none_unknown_and_bad_values(rigs: list[Rig]) -> None:
    @sdk.variable("nothing")
    def nothing() -> None:
        return None

    @sdk.variable("bad")
    def bad() -> Any:
        return [1]

    @sdk.variable("long")
    def long() -> str:
        return "x" * 1025

    rig = _start(rigs)
    rig.hello()
    rig.send("get_variable", {"request": 1, "name": "nothing"})
    assert_that(rig.recv_until("variable_value")["payload"]).is_equal_to({"request": 1, "ok": True, "value": None})
    for request, name in ((2, "bad"), (3, "long"), (4, "unknown")):
        rig.send("get_variable", {"request": request, "name": name})
        payload = rig.recv_until("variable_value")["payload"]
        assert_that(payload["ok"]).is_false()
        assert_that(payload["error"]).is_not_empty()


def test_getter_raising_answers_not_ok(rigs: list[Rig]) -> None:
    @sdk.variable("broken")
    def broken() -> str:
        raise RuntimeError("nope")

    rig = _start(rigs)
    rig.hello()
    rig.send("get_variable", {"request": 9, "name": "broken"})
    payload = rig.recv_until("variable_value")["payload"]
    assert_that(payload["ok"]).is_false()
    assert_that(payload["error"]).contains("nope")


def test_variables_changed_feeds_get_and_has_variable(rigs: list[Rig]) -> None:
    @sdk.init
    def setup(ctx: sdk.PluginContext) -> None:
        pass

    rig = _start(rigs)
    rig.hello()
    rig.send("variables_changed", {"set": {"a": "1", "b": "2"}, "removed": []})
    _wait_for(lambda: sdk.has_variable("a"))
    assert_that(sdk.get_variable("b")).is_equal_to("2")
    assert_that(sdk.has_variable("zzz")).is_false()
    assert_that(sdk.get_variable("zzz")).is_none()
    rig.send("variables_changed", {"set": {"b": "3"}, "removed": ["a"]})
    _wait_for(lambda: not sdk.has_variable("a"))
    assert_that(sdk.get_variable("b")).is_equal_to("3")


def test_signal_sends_variable_updated_and_updates_local_copy(rigs: list[Rig]) -> None:
    level = {"value": 1}
    ctxs: list[sdk.PluginContext] = []

    @sdk.variable("level")
    def read_level() -> int:
        return level["value"]

    @sdk.init
    def setup(ctx: sdk.PluginContext) -> None:
        ctxs.append(ctx)

    rig = _start(rigs)
    rig.hello()
    _wait_for(lambda: ctxs)
    level["value"] = 5
    ctxs[0].signal_variable_updated("level")
    assert_that(rig.recv_until("variable_updated")["payload"]).is_equal_to({"name": "level"})
    assert_that(ctxs[0].get_variable("level")).is_equal_to("5")
    sdk.signal_variable_updated("level")
    rig.recv_until("variable_updated")


def test_register_and_unregister_send_events(rigs: list[Rig]) -> None:
    @sdk.variable("vol_{device}")
    def vol(device: str) -> int:
        return 1

    ctxs: list[sdk.PluginContext] = []

    @sdk.init
    def setup(ctx: sdk.PluginContext) -> None:
        ctxs.append(ctx)
        ctx.register_variable("vol_speakers")
        ctx.unregister_variable("vol_speakers")

    rig = _start(rigs)
    rig.hello()
    assert_that(rig.recv_until("register_variable")["payload"]).is_equal_to({"name": "vol_speakers"})
    assert_that(rig.recv_until("unregister_variable")["payload"]).is_equal_to({"name": "vol_speakers"})


def test_register_without_matching_getter_sends_nothing(rigs: list[Rig]) -> None:
    done = threading.Event()

    @sdk.init
    def setup(ctx: sdk.PluginContext) -> None:
        ctx.register_variable("ghost")
        ctx.log("marker")
        done.set()

    rig = _start(rigs)
    rig.hello()
    seen: list[str] = []
    while True:
        message = rig.recv_until("log")
        seen.append(message["payload"]["message"])
        if message["payload"]["message"] == "marker":
            break
    assert_that(seen[0]).contains("ghost")
    assert_that(seen[0]).is_not_equal_to("marker")


def test_helpers_without_runtime_raise() -> None:
    _variables.reset()
    with pytest.raises(RuntimeError):
        sdk.get_variable("x")
