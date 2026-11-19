"""Cross-platform process groups, process-tree termination and memory reading."""

import os
import signal
import subprocess
import sys
from typing import Any

import psutil


def group_popen_kwargs() -> dict[str, Any]:
    """Popen keyword arguments that put the child in its own process group."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def terminate_tree(proc: subprocess.Popen[Any]) -> None:
    """Ask the process and its descendants to stop; never raises."""
    if sys.platform == "win32":
        _walk_tree(proc.pid, terminate=True)
    else:
        _signal_group(proc.pid, signal.SIGTERM)


def kill_tree(proc: subprocess.Popen[Any]) -> None:
    """Forcefully stop the process and its descendants; never raises."""
    if sys.platform == "win32":
        _walk_tree(proc.pid, terminate=False)
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


def _walk_tree(pid: int, terminate: bool) -> None:
    try:
        root = psutil.Process(pid)
        victims = [*root.children(recursive=True), root]
    except psutil.Error:
        return
    for victim in victims:
        try:
            victim.terminate() if terminate else victim.kill()
        except psutil.Error:
            pass
