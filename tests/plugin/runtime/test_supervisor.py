import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from assertpy import assert_that

from decker.plugin.protocol import Message
from decker.plugin.runtime.process import PluginProcess
from decker.plugin.runtime.supervisor import PluginSupervisor, SupervisorPolicy

FIXTURES = Path(__file__).parent / "fixtures"


class FakeProcess:
    def __init__(self, on_message: Callable[[Message], None], on_exit: Callable[[int], None]) -> None:
        self.on_message = on_message
        self.on_exit = on_exit
        self.running = False
        self.sent: list[Message] = []
        self.rss: int | None = 1024
        self.stops = 0

    @property
    def is_running(self) -> bool:
        return self.running

    def start(self) -> None:
        self.running = True

    def send(self, message: Message) -> None:
        self.sent.append(message)

    def stop(self, timeout: float = 3.0) -> None:  # pylint: disable=unused-argument
        self.stops += 1
        if self.running:
            self.running = False
            self.on_exit(0)

    def rss_bytes(self) -> int | None:
        return self.rss

    def emit(self, event: str) -> None:
        self.on_message(Message(event))

    def crash(self) -> None:
        self.running = False
        self.on_exit(1)

    def events(self) -> list[str]:
        return [m.event for m in self.sent]


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class Rig:
    def __init__(self, **policy: Any) -> None:
        self.clock = Clock()
        self.procs: list[FakeProcess] = []
        self.messages: list[tuple[str, str]] = []
        self.failures: list[tuple[str, str]] = []
        self.sup = PluginSupervisor(
            SupervisorPolicy(**policy),
            self._factory,
            lambda pid, msg: self.messages.append((pid, msg.event)),
            lambda pid, reason: self.failures.append((pid, reason)),
            self.clock,
        )
        self.sup.register("a.b", ["cmd"], Path("."), {}, {"protocol": 1})

    def _factory(self, _pid: str, _cmd: list[str], _cwd: Path, _env: dict[str, str], on_message: Any, on_exit: Any):
        proc = FakeProcess(on_message, on_exit)
        self.procs.append(proc)
        return proc

    @property
    def last(self) -> FakeProcess:
        return self.procs[-1]

    def advance(self, seconds: float) -> None:
        self.clock.now += seconds
        self.sup.tick(self.clock.now)


def test_first_acquire_starts_and_sends_hello() -> None:
    rig = Rig()
    rig.sup.acquire("a.b")
    assert_that(rig.procs).is_length(1)
    assert_that(rig.last.sent[0].event).is_equal_to("hello")
    assert_that(rig.last.sent[0].payload).is_equal_to({"protocol": 1})


def test_messages_queued_until_ready() -> None:
    rig = Rig()
    rig.sup.acquire("a.b")
    rig.sup.send("a.b", Message("will_appear", "c1"))
    assert_that(rig.last.events()).is_equal_to(["hello"])
    rig.last.emit("ready")
    assert_that(rig.last.events()).is_equal_to(["hello", "will_appear"])
    rig.sup.send("a.b", Message("key_down", "c1"))
    assert_that(rig.last.events()).is_equal_to(["hello", "will_appear", "key_down"])
    assert_that(rig.messages).is_equal_to([("a.b", "ready")])


def test_is_ready_tracks_ready_and_crash() -> None:
    rig = Rig()
    assert_that(rig.sup.is_ready("a.b")).is_false()
    rig.sup.acquire("a.b")
    assert_that(rig.sup.is_ready("a.b")).is_false()
    rig.last.emit("ready")
    assert_that(rig.sup.is_ready("a.b")).is_true()
    rig.last.crash()
    assert_that(rig.sup.is_ready("a.b")).is_false()
    assert_that(rig.sup.is_ready("unknown")).is_false()


def test_second_acquire_does_not_start_second_process() -> None:
    rig = Rig()
    rig.sup.acquire("a.b")
    rig.sup.acquire("a.b")
    assert_that(rig.procs).is_length(1)


def test_release_stops_after_idle_grace() -> None:
    rig = Rig(idle_grace_s=10.0)
    rig.sup.acquire("a.b")
    rig.sup.release("a.b")
    rig.advance(9.0)
    assert_that(rig.last.running).is_true()
    rig.advance(1.5)
    assert_that(rig.last.running).is_false()
    assert_that(rig.failures).is_empty()
    rig.advance(30.0)
    assert_that(rig.procs).is_length(1)


def test_reacquire_within_grace_keeps_process() -> None:
    rig = Rig(idle_grace_s=10.0)
    rig.sup.acquire("a.b")
    rig.last.emit("ready")
    rig.sup.release("a.b")
    rig.advance(5.0)
    rig.sup.acquire("a.b")
    rig.advance(20.0)
    assert_that(rig.procs).is_length(1)
    assert_that(rig.last.running).is_true()


def test_crash_restarts_with_backoff() -> None:
    rig = Rig(backoff_s=(0.5, 2.0))
    rig.sup.acquire("a.b")
    rig.last.crash()
    assert_that(rig.procs).is_length(1)
    rig.advance(0.4)
    assert_that(rig.procs).is_length(1)
    rig.advance(0.2)
    assert_that(rig.procs).is_length(2)
    assert_that(rig.last.events()).is_equal_to(["hello"])


def test_repeated_crashes_mark_failed_and_notify() -> None:
    rig = Rig(max_crashes=3)
    rig.sup.acquire("a.b")
    rig.sup.send("a.b", Message("key_down", "c1"))
    for _ in range(2):
        rig.last.crash()
        rig.advance(6.0)
    rig.last.crash()
    assert_that(rig.sup.is_failed("a.b")).is_true()
    assert_that(rig.failures).is_length(1)
    assert_that(rig.failures[0][0]).is_equal_to("a.b")
    rig.advance(60.0)
    assert_that(rig.procs).is_length(3)
    rig.sup.send("a.b", Message("key_down", "c1"))
    rig.sup.acquire("a.b")
    assert_that(rig.procs).is_length(3)


def test_crashes_outside_window_do_not_fail() -> None:
    rig = Rig(max_crashes=2, crash_window_s=60.0)
    rig.sup.acquire("a.b")
    rig.last.crash()
    rig.advance(100.0)
    rig.last.crash()
    assert_that(rig.sup.is_failed("a.b")).is_false()


def test_reset_failure_allows_restart() -> None:
    rig = Rig(max_crashes=1)
    rig.sup.acquire("a.b")
    rig.last.crash()
    assert_that(rig.sup.is_failed("a.b")).is_true()
    rig.sup.reset_failure("a.b")
    assert_that(rig.sup.is_failed("a.b")).is_false()
    assert_that(rig.procs).is_length(2)
    assert_that(rig.last.running).is_true()


def test_memory_limit_kills() -> None:
    rig = Rig(memory_limit=1000)
    rig.sup.acquire("a.b")
    rig.last.emit("ready")
    rig.last.rss = 5000
    rig.advance(1.0)
    assert_that(rig.procs[0].stops).is_equal_to(1)
    assert_that(rig.procs[0].running).is_false()
    rig.advance(1.0)
    assert_that(rig.procs).is_length(2)


def test_unanswered_ping_kills() -> None:
    rig = Rig(ping_interval_s=5.0, ping_timeout_s=10.0)
    rig.sup.acquire("a.b")
    rig.last.emit("ready")
    rig.advance(5.0)
    assert_that(rig.last.events()).contains("ping")
    rig.advance(9.0)
    assert_that(rig.last.stops).is_equal_to(0)
    rig.advance(2.0)
    assert_that(rig.procs[0].stops).is_equal_to(1)
    rig.advance(1.0)
    assert_that(rig.procs).is_length(2)


def test_answered_ping_keeps_process_and_pong_not_forwarded() -> None:
    rig = Rig(ping_interval_s=5.0, ping_timeout_s=10.0)
    rig.sup.acquire("a.b")
    rig.last.emit("ready")
    for _ in range(4):
        rig.advance(5.0)
        rig.last.emit("pong")
    assert_that(rig.last.stops).is_equal_to(0)
    assert_that(rig.messages).is_equal_to([("a.b", "ready")])


def test_stop_all_stops_every_process() -> None:
    rig = Rig()
    rig.sup.register("c.d", ["cmd"], Path("."), {}, {})
    rig.sup.acquire("a.b")
    rig.sup.acquire("c.d")
    rig.sup.start()
    rig.sup.stop_all()
    assert_that([p.stops for p in rig.procs]).is_equal_to([1, 1])
    assert_that(rig.failures).is_empty()
    rig.advance(60.0)
    assert_that(rig.procs).is_length(2)
    rig.sup.acquire("a.b")
    assert_that(rig.procs).is_length(2)


def test_unregister_stops_process() -> None:
    rig = Rig()
    rig.sup.acquire("a.b")
    rig.sup.unregister("a.b")
    assert_that(rig.last.stops).is_equal_to(1)
    assert_that(rig.failures).is_empty()
    rig.advance(30.0)
    assert_that(rig.procs).is_length(1)


def _real_factory(plugin_id: str, command: list[str], cwd: Path, env: dict[str, str], on_message: Any, on_exit: Any):
    return PluginProcess(plugin_id, command, cwd, env, on_message, on_exit)


def _pid_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_server_stop_leaves_no_orphans() -> None:
    ready: list[str] = []
    sup = PluginSupervisor(
        SupervisorPolicy(),
        _real_factory,
        lambda pid, msg: ready.append(pid) if msg.event == "ready" else None,
        lambda _pid, _reason: None,
    )
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    for plugin_id in ("x.one", "x.two"):
        sup.register(plugin_id, [sys.executable, str(FIXTURES / "ping_pong.py")], FIXTURES, env, {})
        sup.acquire(plugin_id)
    sup.start()
    deadline = time.monotonic() + 5.0
    while len(ready) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert_that(ready).is_length(2)
    pids = [
        p.pid for e in sup._entries.values() if (p := e.process) is not None and p.pid
    ]  # pylint: disable=protected-access
    assert_that(pids).is_length(2)
    sup.stop_all()
    for pid in pids:
        assert_that(_pid_gone(pid)).is_true()


def test_never_ready_is_killed_and_restarted() -> None:
    rig = Rig(ping_timeout_s=10.0)
    rig.sup.acquire("a.b")
    rig.advance(9.0)
    assert_that(rig.last.stops).is_equal_to(0)
    rig.advance(2.0)
    assert_that(rig.procs[0].stops).is_equal_to(1)
    rig.advance(1.0)
    assert_that(rig.procs).is_length(2)


def test_repeated_never_ready_marks_failed() -> None:
    rig = Rig(ping_timeout_s=10.0, max_crashes=3)
    rig.sup.acquire("a.b")
    for _ in range(3):
        rig.advance(11.0)
        rig.advance(6.0)
    assert_that(rig.sup.is_failed("a.b")).is_true()
    assert_that(rig.failures).is_length(1)


class BrokenStart(FakeProcess):
    error: Exception = OSError("no such interpreter")

    def start(self) -> None:
        raise self.error


def _broken_rig(error: Exception, **policy: Any) -> Rig:
    rig = Rig(**policy)

    def factory(_pid: str, _cmd: list[str], _cwd: Path, _env: dict[str, str], on_message: Any, on_exit: Any):
        proc = BrokenStart(on_message, on_exit)
        proc.error = error
        rig.procs.append(proc)
        return proc

    rig.sup._factory = factory  # pylint: disable=protected-access
    return rig


def test_start_failures_count_as_crashes_and_mark_failed() -> None:
    rig = _broken_rig(OSError("no such interpreter"), max_crashes=3)
    rig.sup.acquire("a.b")
    assert_that(rig.procs).is_length(1)
    rig.advance(0.6)
    assert_that(rig.procs).is_length(2)
    rig.advance(2.1)
    assert_that(rig.procs).is_length(3)
    assert_that(rig.sup.is_failed("a.b")).is_true()
    assert_that(rig.failures).is_length(1)
    assert_that(rig.failures[0][1]).contains("failed to start")
    rig.advance(60.0)
    assert_that(rig.procs).is_length(3)


def test_non_oserror_start_failure_does_not_raise() -> None:
    rig = _broken_rig(ValueError("embedded null byte"), max_crashes=2)
    rig.sup.acquire("a.b")
    rig.advance(0.6)
    assert_that(rig.sup.is_failed("a.b")).is_true()
    assert_that(rig.failures).is_length(1)


def test_stale_queue_not_delivered_after_crash() -> None:
    rig = Rig()
    rig.sup.acquire("a.b")
    rig.sup.send("a.b", Message("key_down", "c1"))
    rig.last.crash()
    rig.advance(1.0)
    assert_that(rig.procs).is_length(2)
    rig.last.emit("ready")
    assert_that(rig.last.events()).is_equal_to(["hello"])


def test_queued_messages_follow_what_the_ready_handler_sends() -> None:
    rig = Rig()
    rig.sup.acquire("a.b")
    rig.sup.send("a.b", Message("key_down", "c1"))
    rig.messages.clear()
    original = rig.sup._on_message  # pylint: disable=protected-access
    rig.sup._on_message = lambda pid, msg: (  # pylint: disable=protected-access
        rig.sup.send(pid, Message("will_appear", "c1")) if msg.event == "ready" else original(pid, msg)
    )
    rig.last.emit("ready")
    assert_that(rig.last.events()).is_equal_to(["hello", "will_appear", "key_down"])


def test_burst_within_budget_is_delivered_and_excess_is_dropped() -> None:
    rig = Rig()
    rig.sup.acquire("a.b")
    for _ in range(250):
        rig.last.emit("log")
    assert_that(rig.messages).is_length(200)
    rig.clock.now += 1.0
    for _ in range(50):
        rig.last.emit("log")
    assert_that(rig.messages).is_length(250)


def test_sustained_flood_kills_plugin_and_counts_a_crash() -> None:
    rig = Rig(flood_kill_s=5.0, backoff_s=(0.5,))
    rig.sup.acquire("a.b")
    first = rig.last
    for _ in range(300):
        first.emit("log")
    for _ in range(8):
        rig.clock.now += 0.7
        for _ in range(200):
            first.emit("log")
        if not first.running:
            break
    deadline = time.monotonic() + 3
    while rig.sup._entries["a.b"].restart_at is None and time.monotonic() < deadline:  # pylint: disable=protected-access
        time.sleep(0.01)
    assert_that(first.stops).is_greater_than(0)
    rig.advance(1.0)
    assert_that(rig.procs).is_length(2)


def test_steady_rate_under_budget_never_kills() -> None:
    rig = Rig(flood_kill_s=1.0)
    rig.sup.acquire("a.b")
    for _ in range(20):
        rig.clock.now += 1.0
        for _ in range(90):
            rig.last.emit("log")
    assert_that(rig.last.stops).is_equal_to(0)
    assert_that(rig.messages).is_length(1800)
