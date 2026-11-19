"""Windows window backend: polls GetForegroundWindow; a low-level mouse hook picks a window."""

import ctypes
import ctypes.wintypes as wt
import logging
import os
import sys
import threading
import time
from typing import Any, Callable, Mapping, Protocol

import psutil

from decker.common.model import WindowInfo
from decker.server.windows.backend import BackendStatus

PICK_TIMEOUT = 60.0
POLL_INTERVAL = 0.3

_WH_KEYBOARD_LL = 13
_WH_MOUSE_LL = 14
_WM_KEYDOWN = 0x0100
_WM_SYSKEYDOWN = 0x0104
_PICK_MESSAGES = frozenset({0x0201, 0x0204, 0x0207})  # left, right and middle button down; never the wheel
_VK_ESCAPE = 0x1B
_GA_ROOT = 2
_PM_REMOVE = 1
_QS_ALLINPUT = 0x04FF

_log = logging.getLogger(__name__)


def is_pick_message(message: int) -> bool:
    """True for a left, middle or right button-down mouse message."""
    return message in _PICK_MESSAGES


class WindowsTransport(Protocol):
    """The Win32 operations the backend needs; the only part faked in tests."""

    def foreground(self) -> Mapping[str, Any] | None:
        """Describe the foreground window (hwnd, class_name, title, pid); None when none or it vanished."""
        ...

    def pick(self, timeout: float) -> Mapping[str, Any] | None:
        """Hook the mouse in the calling thread and describe the clicked top-level window; None on Escape or timeout."""
        ...

    def close(self) -> None:
        """Release resources."""
        ...


def _executable(pid: int) -> str:
    if pid <= 0:
        return ""
    try:
        return os.path.basename(psutil.Process(pid).exe())
    except (psutil.Error, OSError):
        return ""


def window_from_win32(hwnd_info: Mapping[str, Any]) -> WindowInfo:
    """Map a described Win32 window to a WindowInfo; window_type stays empty, Windows has no equivalent."""
    pid = int(hwnd_info.get("pid") or 0)
    return WindowInfo(
        window_class=str(hwnd_info.get("class_name") or ""),
        window_type="",
        title=str(hwnd_info.get("title") or ""),
        executable=_executable(pid),
        desktop_file="",
        pid=pid,
    )


class _PickState:
    def __init__(self) -> None:
        self.point: wt.POINT | None = None
        self.cancelled = False


class _Win32Transport:  # pylint: disable=missing-function-docstring
    def __init__(self) -> None:
        win_dll = getattr(ctypes, "WinDLL")
        self._user32: Any = win_dll("user32", use_last_error=True)
        self._kernel32: Any = win_dll("kernel32", use_last_error=True)
        self._hookproc = getattr(ctypes, "WINFUNCTYPE")(ctypes.c_ssize_t, ctypes.c_int, wt.WPARAM, wt.LPARAM)
        self._declare()

    def _declare(self) -> None:
        user32, kernel32 = self._user32, self._kernel32
        user32.GetForegroundWindow.restype = wt.HWND
        user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        user32.GetWindowTextLengthW.argtypes = [wt.HWND]
        user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
        user32.IsWindow.argtypes = [wt.HWND]
        user32.WindowFromPoint.argtypes = [wt.POINT]
        user32.WindowFromPoint.restype = wt.HWND
        user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
        user32.GetAncestor.restype = wt.HWND
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, self._hookproc, wt.HINSTANCE, wt.DWORD]
        user32.SetWindowsHookExW.restype = wt.HHOOK
        user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
        user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
        user32.MsgWaitForMultipleObjects.argtypes = [wt.DWORD, ctypes.c_void_p, wt.BOOL, wt.DWORD, wt.DWORD]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
        kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wt.HINSTANCE

    def foreground(self) -> Mapping[str, Any] | None:
        return self._describe(self._user32.GetForegroundWindow())

    def _describe(self, hwnd: Any) -> Mapping[str, Any] | None:
        user32 = self._user32
        if not hwnd or not user32.IsWindow(hwnd):
            return None
        pid = wt.DWORD(0)
        if not user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
            return None
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, name, len(name))
        title = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
        user32.GetWindowTextW(hwnd, title, len(title))
        return {"hwnd": int(hwnd), "class_name": name.value, "title": title.value, "pid": int(pid.value)}

    def pick(self, timeout: float) -> Mapping[str, Any] | None:
        state = _PickState()
        hooks: list[Any] = []
        # The callbacks must stay referenced until unhooked, or Windows calls freed memory.
        mouse_proc, keyboard_proc = self._mouse_proc(state, hooks), self._keyboard_proc(state, hooks)
        try:
            module = self._kernel32.GetModuleHandleW(None)
            for kind, proc in ((_WH_MOUSE_LL, mouse_proc), (_WH_KEYBOARD_LL, keyboard_proc)):
                hook = self._user32.SetWindowsHookExW(kind, proc, module, 0)
                if not hook:
                    raise OSError(f"cannot install hook {kind} (error {getattr(ctypes, "get_last_error")()})")
                hooks.append(hook)
            self._pump(state, time.monotonic() + timeout)
        finally:
            for hook in hooks:
                self._user32.UnhookWindowsHookEx(hook)
        if state.point is None or state.cancelled:
            return None
        return self._describe(self._user32.GetAncestor(self._user32.WindowFromPoint(state.point), _GA_ROOT))

    def _mouse_proc(self, state: _PickState, hooks: list[Any]) -> Any:
        def proc(code: int, wparam: int, lparam: int) -> int:
            if code >= 0 and state.point is None and is_pick_message(wparam):
                info = ctypes.cast(lparam, ctypes.POINTER(_MouseHook)).contents
                state.point = wt.POINT(info.pt.x, info.pt.y)
                return 1
            return int(self._user32.CallNextHookEx(hooks[0] if hooks else None, code, wparam, lparam))

        return self._hookproc(proc)

    def _keyboard_proc(self, state: _PickState, hooks: list[Any]) -> Any:
        def proc(code: int, wparam: int, lparam: int) -> int:
            if code >= 0 and wparam in (_WM_KEYDOWN, _WM_SYSKEYDOWN):
                info = ctypes.cast(lparam, ctypes.POINTER(_KeyboardHook)).contents
                if info.vkCode == _VK_ESCAPE:
                    state.cancelled = True
                    return 1
            return int(self._user32.CallNextHookEx(hooks[-1] if hooks else None, code, wparam, lparam))

        return self._hookproc(proc)

    def _pump(self, state: _PickState, deadline: float) -> None:
        user32 = self._user32
        msg = wt.MSG()
        while state.point is None and not state.cancelled:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            user32.MsgWaitForMultipleObjects(0, None, False, int(min(remaining, 0.1) * 1000) + 1, _QS_ALLINPUT)
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, _PM_REMOVE):
                user32.DispatchMessageW(ctypes.byref(msg))

    def close(self) -> None:
        return None


class _MouseHook(ctypes.Structure):
    _fields_ = [
        ("pt", wt.POINT),
        ("mouseData", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KeyboardHook(ctypes.Structure):
    _fields_ = [
        ("vkCode", wt.DWORD),
        ("scanCode", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class WindowsBackend:
    """Focused-window detection by polling and picking through low-level input hooks on Windows."""

    name = "windows"
    supports_pick = True

    def __init__(
        self,
        transport: WindowsTransport | None = None,
        poll_interval: float = POLL_INTERVAL,
        pick_timeout: float = PICK_TIMEOUT,
    ) -> None:
        self._given = transport
        self._poll_interval = poll_interval
        self._pick_timeout = pick_timeout
        self._transport: WindowsTransport | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pick_lock = threading.Lock()
        self._lifecycle = threading.Lock()

    def available(self) -> BackendStatus:
        """Report active on Windows and unsupported elsewhere."""
        if sys.platform != "win32":
            return BackendStatus("unsupported", "Windows only")
        return BackendStatus("active")

    def _build(self) -> WindowsTransport:
        return self._given if self._given is not None else _Win32Transport()

    def start(
        self, on_change: Callable[[WindowInfo], None], on_failure: Callable[[Exception], None] | None = None
    ) -> None:
        """Start polling, reporting the foreground window at once; raises when the transport cannot be built."""
        with self._lifecycle:
            self._stop_locked()
            transport = self._build()
            self._transport = transport
            self._stop_event = stop_event = threading.Event()
            self._thread = threading.Thread(
                target=self._listen,
                args=(transport, stop_event, on_change, on_failure),
                name="windows-focus",
                daemon=True,
            )
            self._thread.start()

    def _listen(
        self,
        transport: WindowsTransport,
        stop_event: threading.Event,
        on_change: Callable[[WindowInfo], None],
        on_failure: Callable[[Exception], None] | None,
    ) -> None:
        last: tuple[Any, ...] | None = None
        while not stop_event.is_set():
            try:
                current = transport.foreground()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                if not stop_event.is_set():
                    _log.exception("Windows focus poll failed")
                    if on_failure is not None:
                        on_failure(exc)
                return
            key = None if current is None else _key(current)
            if current is not None and key != last and not stop_event.is_set():
                last = key
                self._report(on_change, current)
            stop_event.wait(self._poll_interval)

    @staticmethod
    def _report(on_change: Callable[[WindowInfo], None], current: Mapping[str, Any]) -> None:
        try:
            on_change(window_from_win32(current))
        except Exception:  # pylint: disable=broad-exception-caught
            _log.exception("focus callback failed")

    def stop(self) -> None:
        """Stop polling; never raises."""
        with self._lifecycle:
            self._stop_locked()

    def _stop_locked(self) -> None:
        self._stop_event.set()
        transport, thread = self._transport, self._thread
        self._transport = self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        if transport is not None:
            _quietly(transport.close)

    def pick(self, on_result: Callable[[WindowInfo | None], None]) -> None:
        """Let the user click a window; on_result gets the window or None, exactly once."""
        if not self._pick_lock.acquire(blocking=False):  # pylint: disable=consider-using-with
            on_result(None)
            return
        try:
            threading.Thread(target=self._run_pick, args=(on_result,), name="windows-pick", daemon=True).start()
        except Exception:  # pylint: disable=broad-exception-caught
            _log.exception("cannot start the window pick thread")
            self._pick_lock.release()
            on_result(None)

    def _run_pick(self, on_result: Callable[[WindowInfo | None], None]) -> None:
        result: WindowInfo | None = None
        try:
            described = self._build().pick(self._pick_timeout)
            result = None if described is None else window_from_win32(described)
        except Exception:  # pylint: disable=broad-exception-caught
            _log.exception("window pick failed")
        finally:
            self._pick_lock.release()
        try:
            on_result(result)
        except Exception:  # pylint: disable=broad-exception-caught
            _log.exception("pick callback failed")


def _key(window: Mapping[str, Any]) -> tuple[Any, ...]:
    return (window.get("hwnd"), window.get("class_name"), window.get("title"), window.get("pid"))


def _quietly(action: Callable[[], object]) -> None:
    try:
        action()
    except Exception:  # pylint: disable=broad-exception-caught
        _log.debug("ignored error during cleanup", exc_info=True)
