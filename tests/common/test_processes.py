import os
import subprocess
import sys
import time
from collections.abc import Iterator

import psutil
import pytest
from assertpy import assert_that

from decker.common.processes import (
    group_popen_kwargs,
    kill_tree,
    rss_bytes,
    terminate_tree,
)

_SLEEP = "import time; time.sleep(60)"
_PARENT = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "print(child.pid, flush=True)\n"
    "time.sleep(60)\n"
)


def _spawn(code: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # pylint: disable=consider-using-with
        [sys.executable, "-c", code], stdout=subprocess.PIPE, **group_popen_kwargs()
    )


def _wait_gone(pid: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not psutil.pid_exists(pid):
            return True
        time.sleep(0.05)
    return not psutil.pid_exists(pid)


@pytest.fixture(name="procs")
def _procs() -> Iterator[list[subprocess.Popen[bytes]]]:
    started: list[subprocess.Popen[bytes]] = []
    yield started
    for proc in started:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        if proc.stdout is not None:
            proc.stdout.close()


def test_kill_tree_stops_the_process_and_its_grandchild(procs: list[subprocess.Popen[bytes]]) -> None:
    parent = _spawn(_PARENT)
    procs.append(parent)
    assert parent.stdout is not None
    grandchild = int(parent.stdout.readline())
    kill_tree(parent)
    parent.wait(timeout=5)
    assert_that(_wait_gone(parent.pid)).is_true()
    assert_that(_wait_gone(grandchild)).is_true()


def test_terminate_tree_stops_a_sleeping_process(procs: list[subprocess.Popen[bytes]]) -> None:
    proc = _spawn(_SLEEP)
    procs.append(proc)
    terminate_tree(proc)
    assert_that(proc.wait(timeout=5)).is_not_equal_to(0)


def test_terminate_and_kill_on_an_exited_process_do_not_raise(procs: list[subprocess.Popen[bytes]]) -> None:
    proc = _spawn("pass")
    procs.append(proc)
    proc.wait(timeout=5)
    terminate_tree(proc)
    kill_tree(proc)


def test_rss_bytes_of_the_current_process_is_positive() -> None:
    assert_that(rss_bytes(os.getpid())).is_greater_than(0)


def test_rss_bytes_of_a_missing_pid_is_none(procs: list[subprocess.Popen[bytes]]) -> None:
    proc = _spawn("pass")
    procs.append(proc)
    proc.wait(timeout=5)
    assert_that(rss_bytes(proc.pid)).is_none()


@pytest.mark.posix_only
def test_group_popen_kwargs_starts_a_new_session_on_posix() -> None:
    assert_that(group_popen_kwargs()).is_equal_to({"start_new_session": True})


@pytest.mark.windows_only
def test_group_popen_kwargs_creates_a_process_group_on_windows() -> None:
    flags = group_popen_kwargs()["creationflags"]
    assert_that(flags & subprocess.CREATE_NEW_PROCESS_GROUP).is_true()  # type: ignore[attr-defined,unused-ignore]
