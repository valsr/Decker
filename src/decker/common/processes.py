"""Cross-platform process groups, process-tree termination and memory reading."""

import logging
import os
import signal
import subprocess
import sys
import weakref
from dataclasses import dataclass
from typing import Any

import psutil

from decker.common import _winjob

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Job:
    handle: int
    close: weakref.finalize  # type: ignore[type-arg,unused-ignore]


_JOBS: "weakref.WeakKeyDictionary[subprocess.Popen[Any], _Job]" = weakref.WeakKeyDictionary()


def group_popen_kwargs() -> dict[str, Any]:
    """Popen keyword arguments that put the child in its own process group."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def terminate_tree(proc: subprocess.Popen[Any]) -> None:
    """Ask the process and its descendants to stop; never raises."""
    if sys.platform == "win32":
        _walk_tree(proc, terminate=True)
    else:
        _signal_group(proc.pid, signal.SIGTERM)


def adopt(proc: subprocess.Popen[Any]) -> None:
    """On Windows put a just-spawned process in a kill-on-close job object; never raises, no-op elsewhere."""
    if sys.platform != "win32":
        return
    handle = _winjob.create_job()
    if handle is None:
        _LOGGER.debug("job object unavailable; falling back to the process walk")
        return
    if not _winjob.assign(handle, proc.pid):
        _LOGGER.debug("could not assign pid %s to a job object; falling back to the process walk", proc.pid)
        _winjob.close(handle)
        return
    _JOBS[proc] = _Job(handle, weakref.finalize(proc, _winjob.close, handle))


def kill_tree(proc: subprocess.Popen[Any]) -> None:
    """Forcefully stop the process and its descendants; never raises."""
    if sys.platform == "win32":
        job = _JOBS.pop(proc, None)
        if job is None:
            _walk_tree(proc, terminate=False)
        else:
            _winjob.terminate(job.handle)
            job.close()
    else:
        _signal_group(proc.pid, signal.SIGKILL)


def rss_bytes(pid: int) -> int | None:
    """Resident set size of a process, or None if it is gone or unreadable."""
    try:
        return int(psutil.Process(pid).memory_info().rss)
    except (psutil.Error, OSError):
        return None


def _signal_group(pgid: int, sig: int) -> None:
    if sys.platform == "win32":
        return
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _lookup(pid: int) -> psutil.Process:
    return psutil.Process(pid)


def _walk_tree(proc: subprocess.Popen[Any], terminate: bool) -> None:
    # Windows has no process group to signal once the leader is gone, and its pid may already be recycled by an
    # unrelated process, so orphans of an exited leader are deliberately left alone.
    if proc.poll() is not None:
        return
    try:
        root = _lookup(proc.pid)
        victims = [*root.children(recursive=True), root]
    except psutil.Error:
        return
    if proc.poll() is not None:
        return
    for victim in victims:
        try:
            if terminate:
                victim.terminate()
            else:
                victim.kill()
        except psutil.Error:
            pass
