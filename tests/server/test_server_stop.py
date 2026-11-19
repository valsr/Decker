"""Tests for the graceful stop pieces of the server process: ShutdownGate and stop_process."""

import multiprocessing
import multiprocessing.synchronize
import pickle
import signal
import sys
import time
from collections.abc import Callable

import pytest
from assertpy import assert_that

from decker.common import config
from decker.common.context import ServerAppContext
from decker.server.server import ServerProcess, ShutdownGate, stop_process


class FakeServer:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


def _exit_on_event(stop_event: multiprocessing.synchronize.Event) -> None:
    stop_event.wait()
    sys.exit(0)


def _ignore_event(stop_event: multiprocessing.synchronize.Event) -> None:  # pylint: disable=unused-argument
    time.sleep(60)


def _ignore_terminate(
    stop_event: multiprocessing.synchronize.Event, ready: multiprocessing.synchronize.Event
) -> None:  # pylint: disable=unused-argument
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    ready.set()
    time.sleep(60)


def _exit_now(stop_event: multiprocessing.synchronize.Event) -> None:  # pylint: disable=unused-argument
    sys.exit(0)


def _spawn(target: Callable[..., object]) -> tuple[multiprocessing.Process, multiprocessing.synchronize.Event]:
    stop_event = multiprocessing.Event()
    process = multiprocessing.Process(target=target, args=(stop_event,))
    process.start()
    return process, stop_event


class TestShutdownGate:
    def test_gate_closes_the_server_when_a_request_arrives_after_attach(self) -> None:
        gate = ShutdownGate()
        server = FakeServer()
        assert_that(gate.attach(server)).is_false()
        gate.request()
        assert_that(server.closed).is_equal_to(1)

    def test_gate_closes_at_attach_when_the_request_came_first(self) -> None:
        gate = ShutdownGate()
        server = FakeServer()
        gate.request()
        assert_that(gate.attach(server)).is_true()
        assert_that(server.closed).is_equal_to(1)

    def test_gate_attach_without_a_request_returns_false(self) -> None:
        server = FakeServer()
        assert_that(ShutdownGate().attach(server)).is_false()
        assert_that(server.closed).is_equal_to(0)

    def test_gate_request_after_a_false_attach_closes_the_server(self) -> None:
        gate = ShutdownGate()
        server = FakeServer()
        assert_that(gate.attach(server)).is_false()
        assert_that(gate.requested).is_false()
        gate.request()
        assert_that(gate.requested).is_true()
        assert_that(server.closed).is_equal_to(1)

    def test_gate_request_from_inside_close_does_not_deadlock(self) -> None:
        gate = ShutdownGate()

        class Reentrant:
            closed = 0

            def close(self) -> None:
                Reentrant.closed += 1
                gate.request()

        gate.attach(Reentrant())
        gate.request()
        assert_that(Reentrant.closed).is_equal_to(1)

    def test_gate_request_is_idempotent(self) -> None:
        gate = ShutdownGate()
        server = FakeServer()
        gate.attach(server)
        gate.request()
        gate.request()
        assert_that(server.closed).is_equal_to(1)


class TestStopProcess:
    def test_stop_process_returns_graceful_when_the_child_exits_on_the_event(self) -> None:
        process, stop_event = _spawn(_exit_on_event)
        assert_that(stop_process(process, stop_event, grace=10.0)).is_equal_to("graceful")
        assert_that(process.exitcode).is_equal_to(0)

    def test_stop_process_terminates_a_child_that_ignores_the_event(self) -> None:
        process, stop_event = _spawn(_ignore_event)
        assert_that(stop_process(process, stop_event, grace=0.3, terminate_wait=10.0)).is_equal_to("terminated")
        assert_that(process.is_alive()).is_false()

    @pytest.mark.posix_only(
        reason="server stop (docs/platform-support.md row 'Server and monitor'): "
        "a child that ignores SIGTERM can only be built on POSIX"
    )
    def test_stop_process_kills_a_child_that_ignores_terminate(self) -> None:
        stop_event = multiprocessing.Event()
        ready = multiprocessing.Event()
        process = multiprocessing.Process(target=_ignore_terminate, args=(stop_event, ready))
        process.start()
        assert_that(ready.wait(timeout=30)).is_true()
        assert_that(stop_process(process, stop_event, grace=0.3, terminate_wait=0.5)).is_equal_to("killed")
        assert_that(process.is_alive()).is_false()

    def test_stop_process_on_an_exited_child_does_not_raise(self) -> None:
        process, stop_event = _spawn(_exit_now)
        process.join()
        assert_that(stop_process(process, stop_event, grace=1.0)).is_equal_to("graceful")


def test_default_stop_timeout_is_ten_seconds() -> None:
    assert_that(config.get_as("server.stop_timeout", float)).is_equal_to(10.0)


def test_server_process_pickles_for_spawn() -> None:
    server_process = ServerProcess(port=0, startup_wait=0.0, app_context=ServerAppContext())
    # the stop event only pickles while a child is being spawned, so leave it out
    server_process._stop_event = None  # type: ignore[assignment]  # pylint: disable=protected-access
    assert_that(pickle.dumps(server_process)).is_not_empty()
