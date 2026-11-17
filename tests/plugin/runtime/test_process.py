import logging
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from assertpy import assert_that

from decker.plugin.protocol import Message
from decker.plugin.runtime.process import PluginProcess

FIXTURES = Path(__file__).parent / "fixtures"


class Harness:
    def __init__(self, script: str) -> None:
        self.messages: list[Message] = []
        self.exits: list[int] = []
        self.proc = PluginProcess(
            "test.plugin",
            [sys.executable, str(FIXTURES / script)],
            FIXTURES,
            {"PATH": "/usr/bin:/bin"},
            self.messages.append,
            self.exits.append,
        )


def wait_for(cond: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


@pytest.fixture
def make() -> Iterator[Callable[[str], Harness]]:
    created: list[Harness] = []

    def _make(script: str) -> Harness:
        h = Harness(script)
        created.append(h)
        return h

    yield _make
    for h in created:
        h.proc.stop(timeout=0.3)


def test_message_round_trip(make: Callable[[str], Harness]) -> None:
    h = make("echo_ready.py")
    h.proc.start()
    h.proc.send(Message("hello"))
    assert_that(wait_for(lambda: len(h.messages) == 1)).is_true()
    assert_that(h.messages[0].event).is_equal_to("ready")
    assert_that(h.messages[0].payload).is_equal_to({"echo": True})


def test_non_protocol_stdout_is_ignored_and_process_keeps_running(
    make: Callable[[str], Harness], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    h = make("noisy.py")
    h.proc.start()
    assert_that(wait_for(lambda: len(h.messages) == 1)).is_true()
    assert_that([m.event for m in h.messages]).is_equal_to(["ready"])
    assert_that(h.proc.is_running).is_true()
    assert_that(caplog.text).contains("[test.plugin] non-protocol output: hello world")


def test_oversized_line_is_discarded_and_reading_continues(make: Callable[[str], Harness]) -> None:
    h = make("oversized.py")
    h.proc.start()
    assert_that(wait_for(lambda: len(h.messages) == 1, timeout=15)).is_true()
    assert_that(h.messages[0].event).is_equal_to("ready")
    assert_that(h.proc.is_running).is_true()


def test_stderr_is_logged_with_plugin_prefix(make: Callable[[str], Harness], caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    h = make("stderr_writer.py")
    h.proc.start()
    assert_that(wait_for(lambda: "[test.plugin] boom detail" in caplog.text)).is_true()


def test_stop_sends_shutdown_then_kills_unresponsive(make: Callable[[str], Harness]) -> None:
    h = make("ignore_shutdown.py")
    h.proc.start()
    h.proc.stop(timeout=0.5)
    assert_that(h.proc.is_running).is_false()
    assert_that(wait_for(lambda: len(h.exits) == 1)).is_true()


def test_stop_is_graceful_for_cooperative_plugin(make: Callable[[str], Harness]) -> None:
    h = make("echo_ready.py")
    h.proc.start()
    h.proc.stop(timeout=3.0)
    assert_that(wait_for(lambda: len(h.exits) == 1)).is_true()
    assert_that(h.exits).is_equal_to([0])


def test_on_exit_called_once_on_crash(make: Callable[[str], Harness]) -> None:
    h = make("crash.py")
    h.proc.start()
    assert_that(wait_for(lambda: len(h.exits) == 1)).is_true()
    time.sleep(0.2)
    assert_that(h.exits).is_equal_to([3])
    assert_that([m.event for m in h.messages]).is_equal_to(["ready"])
    assert_that(h.proc.is_running).is_false()
    h.proc.send(Message("ping"))


def test_rss_bytes_positive_while_running(make: Callable[[str], Harness]) -> None:
    h = make("ignore_shutdown.py")
    assert_that(h.proc.rss_bytes()).is_none()
    h.proc.start()
    assert_that(h.proc.pid).is_not_none()
    rss = h.proc.rss_bytes()
    assert_that(rss).is_not_none()
    assert_that(rss).is_greater_than(0)


def test_concurrent_send_does_not_interleave(make: Callable[[str], Harness]) -> None:
    h = make("echo_ready.py")
    h.proc.start()

    def spam() -> None:
        for _ in range(20):
            h.proc.send(Message("ping", payload={"n": "x" * 5000}))

    threads = [threading.Thread(target=spam) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert_that(h.proc.is_running).is_true()


def test_stop_returns_when_plugin_never_reads_stdin(make: Callable[[str], Harness]) -> None:
    h = make("never_reads.py")
    h.proc.start()
    big = {"blob": "x" * 200_000}
    for _ in range(100):
        began = time.monotonic()
        h.proc.send(Message("ping", payload=big))
        assert_that(time.monotonic() - began).is_less_than(0.5)
    began = time.monotonic()
    h.proc.stop(timeout=0.5)
    assert_that(time.monotonic() - began).is_less_than(5.0)
    assert_that(h.proc.is_running).is_false()
    assert_that(wait_for(lambda: len(h.exits) == 1)).is_true()


def test_stderr_without_newline_is_read_in_bounded_chunks(
    make: Callable[[str], Harness], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    h = make("stderr_flood.py")
    h.proc.start()
    assert_that(wait_for(lambda: len(h.messages) == 1)).is_true()
    assert_that(wait_for(lambda: sum(len(r.getMessage()) for r in caplog.records) > 2 * 1024 * 1024)).is_true()
    assert_that(max(len(r.getMessage()) for r in caplog.records)).is_less_than(16 * 1024)
