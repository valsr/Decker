import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterator

import psutil
import pytest
from assertpy import assert_that

from decker.common import _winjob, processes
from decker.common.processes import (
    adopt,
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


def _is_gone(pid: int) -> bool:
    if not psutil.pid_exists(pid):
        return True
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


def _wait_gone(pid: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _is_gone(pid):
            return True
        time.sleep(0.05)
    return _is_gone(pid)


def _read_pid(proc: subprocess.Popen[bytes], timeout: float = 10.0) -> int:
    assert proc.stdout is not None
    result: list[bytes] = []
    stdout = proc.stdout
    reader = threading.Thread(target=lambda: result.append(stdout.readline()), daemon=True)
    reader.start()
    reader.join(timeout)
    assert result, "child did not report a pid in time"
    return int(result[0])


@pytest.fixture(name="procs")
def _procs() -> Iterator[list[subprocess.Popen[bytes]]]:
    started: list[subprocess.Popen[bytes]] = []
    yield started
    for proc in started:
        kill_tree(proc)
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        if proc.stdout is not None:
            proc.stdout.close()


@pytest.fixture(name="strays")
def _strays() -> Iterator[list[int]]:
    pids: list[int] = []
    yield pids
    for pid in pids:
        try:
            psutil.Process(pid).kill()
        except psutil.Error:
            pass


def test_kill_tree_stops_the_process_and_its_grandchild(
    procs: list[subprocess.Popen[bytes]], strays: list[int]
) -> None:
    parent = _spawn(_PARENT)
    procs.append(parent)
    grandchild = _read_pid(parent)
    strays.append(grandchild)
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


@pytest.mark.posix_only("plugin runtime and server monitor (docs/platform-support.md): start_new_session is POSIX-only")
def test_group_popen_kwargs_starts_a_new_session_on_posix() -> None:
    assert_that(group_popen_kwargs()).is_equal_to({"start_new_session": True})


@pytest.mark.windows_only(
    "plugin runtime and server monitor (docs/platform-support.md): CREATE_NEW_PROCESS_GROUP is Windows-only"
)
def test_group_popen_kwargs_creates_a_process_group_on_windows() -> None:
    flags = group_popen_kwargs()["creationflags"]
    assert_that(flags & subprocess.CREATE_NEW_PROCESS_GROUP).is_true()  # type: ignore[attr-defined,unused-ignore]


@pytest.mark.parametrize("terminate", [True, False])
def test_walk_tree_never_looks_up_a_pid_after_the_leader_exited(
    procs: list[subprocess.Popen[bytes]], monkeypatch: pytest.MonkeyPatch, terminate: bool
) -> None:
    proc = _spawn("pass")
    procs.append(proc)
    proc.wait(timeout=5)
    lookups: list[int] = []
    monkeypatch.setattr(processes, "_lookup", lambda pid: lookups.append(pid))
    processes._walk_tree(proc, terminate)  # pylint: disable=protected-access
    assert_that(lookups).is_empty()


def test_walk_tree_kills_a_live_leader_and_its_grandchild(
    procs: list[subprocess.Popen[bytes]], strays: list[int]
) -> None:
    parent = _spawn(_PARENT)
    procs.append(parent)
    grandchild = _read_pid(parent)
    strays.append(grandchild)
    processes._walk_tree(parent, False)  # pylint: disable=protected-access
    parent.wait(timeout=5)
    assert_that(_wait_gone(grandchild)).is_true()


def test_adopt_is_harmless_for_any_process(procs: list[subprocess.Popen[bytes]]) -> None:
    proc = _spawn(_SLEEP)
    procs.append(proc)
    adopt(proc)
    assert_that(proc.poll()).is_none()


def test_kill_tree_after_adopt_on_an_exited_process_does_not_raise(procs: list[subprocess.Popen[bytes]]) -> None:
    proc = _spawn("pass")
    procs.append(proc)
    adopt(proc)
    proc.wait(timeout=5)
    kill_tree(proc)
    kill_tree(proc)


def test_adopt_failure_falls_back_to_the_psutil_walk(
    procs: list[subprocess.Popen[bytes]], strays: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_winjob, "create_job", lambda: None, raising=False)
    parent = _spawn(_PARENT)
    procs.append(parent)
    adopt(parent)
    grandchild = _read_pid(parent)
    strays.append(grandchild)
    kill_tree(parent)
    parent.wait(timeout=5)
    assert_that(_wait_gone(grandchild)).is_true()


@pytest.mark.windows_only("plugin runtime (docs/platform-support.md): Job Objects reach helpers of an exited leader")
def test_kill_tree_reaches_a_helper_after_the_leader_exited(
    procs: list[subprocess.Popen[bytes]], strays: list[int]
) -> None:
    parent = _spawn(_PARENT)
    procs.append(parent)
    adopt(parent)
    helper = _read_pid(parent)
    strays.append(helper)
    parent.kill()
    parent.wait(timeout=5)
    assert_that(_is_gone(helper)).is_false()
    kill_tree(parent)
    assert_that(_wait_gone(helper)).is_true()


@pytest.mark.windows_only("plugin runtime (docs/platform-support.md): Job Objects only touch adopted processes")
def test_process_outside_the_job_survives_kill_tree(procs: list[subprocess.Popen[bytes]]) -> None:
    adopted = _spawn(_SLEEP)
    outsider = _spawn(_SLEEP)
    procs.extend([adopted, outsider])
    adopt(adopted)
    kill_tree(adopted)
    adopted.wait(timeout=5)
    assert_that(outsider.poll()).is_none()
    assert_that(_is_gone(outsider.pid)).is_false()
