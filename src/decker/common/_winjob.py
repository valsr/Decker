"""Windows Job Object helpers (ctypes); every function swallows OSError and reports failure instead."""

# pylint: disable=too-few-public-methods

import ctypes
import sys
from ctypes import wintypes
from typing import Any

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in ("Read", "Write", "Other", "ReadBytes", "WriteBytes", "OtherBytes")]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _kernel32() -> Any:
    kernel32 = ctypes.WinDLL("kernel32")  # type: ignore[attr-defined,unused-ignore]
    handle = ctypes.c_void_p
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = handle
    kernel32.SetInformationJobObject.argtypes = [handle, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = handle
    kernel32.AssignProcessToJobObject.argtypes = [handle, handle]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = [handle, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [handle]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def create_job() -> int | None:
    """Create a job object that kills its processes when the last handle closes; None on failure."""
    if sys.platform != "win32":
        return None
    try:
        kernel32 = _kernel32()
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS, ctypes.byref(info), ctypes.sizeof(info)
        ):
            kernel32.CloseHandle(job)
            return None
        return int(job)
    except OSError:
        return None


def assign(handle: int, pid: int) -> bool:
    """Put the process into the job; False if it could not be assigned."""
    if sys.platform != "win32":
        return False
    try:
        kernel32 = _kernel32()
        process = kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
        if not process:
            return False
        try:
            return bool(kernel32.AssignProcessToJobObject(handle, process))
        finally:
            kernel32.CloseHandle(process)
    except OSError:
        return False


def terminate(handle: int) -> None:
    """Kill every process in the job."""
    if sys.platform != "win32":
        return
    try:
        _kernel32().TerminateJobObject(handle, 1)
    except OSError:
        pass


def close(handle: int) -> None:
    """Close the job handle (which kills whatever is still in the job)."""
    if sys.platform != "win32":
        return
    try:
        _kernel32().CloseHandle(handle)
    except OSError:
        pass
