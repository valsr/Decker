"""X11 window backend: PropertyNotify of _NET_ACTIVE_WINDOW reports focus, a pointer grab picks a window."""

# python-xlib is Linux-only, so it is imported lazily inside the transport.
# pylint: disable=import-outside-toplevel

import logging
import os
import select
import threading
import time
from typing import Any, Callable, Mapping, Protocol

import psutil

from decker.common.model import WindowInfo
from decker.server.windows.backend import BackendStatus

PICK_TIMEOUT = 60.0
_POLL_INTERVAL = 0.25
_TYPE_PREFIX = "_NET_WM_WINDOW_TYPE_"
_KNOWN_TYPES = {"normal", "dialog", "utility", "dock", "splash", "menu", "toolbar"}
_XC_CROSSHAIR = 34
_PICK_BUTTONS = (1, 2, 3)

_log = logging.getLogger(__name__)


class X11Transport(Protocol):
    """The X11 operations the backend needs; the only part faked in tests."""

    def poll(self, timeout: float) -> bool:
        """Wait up to timeout for the active window to change; True when it did."""
        ...

    def active_window(self) -> Mapping[str, Any] | None:
        """Properties of the active window, or None when there is none or it vanished."""
        ...

    def pick(self, timeout: float) -> Mapping[str, Any] | None:
        """Grab the pointer and return the clicked top-level window's properties; None on Escape or timeout."""
        ...

    def close(self) -> None:
        """Close the connection."""
        ...


def _executable(pid: int) -> str:
    if pid <= 0:
        return ""
    try:
        return os.path.basename(psutil.Process(pid).exe())
    except (psutil.Error, OSError):
        return ""


def _window_type(atoms: Any) -> str:
    for atom in atoms or ():
        name = str(atom).removeprefix(_TYPE_PREFIX).lower()
        if str(atom).startswith(_TYPE_PREFIX) and name in _KNOWN_TYPES:
            return name
    return "normal"


def window_from_x11(props: Mapping[str, Any]) -> WindowInfo:
    """Map the properties of an X11 window to a WindowInfo."""
    wm_class = tuple(props.get("WM_CLASS") or ())
    pid = int(props.get("_NET_WM_PID") or 0)
    return WindowInfo(
        window_class=str(wm_class[-1]) if wm_class else "",
        window_type=_window_type(props.get("_NET_WM_WINDOW_TYPE")),
        title=str(props.get("_NET_WM_NAME") or props.get("WM_NAME") or ""),
        executable=_executable(pid),
        desktop_file="",
        pid=pid,
    )


class _XlibTransport:  # pylint: disable=missing-function-docstring
    def __init__(self, display: Any) -> None:
        from Xlib import X

        self._display = display
        self._root = display.screen().root
        self._active_atom = display.intern_atom("_NET_ACTIVE_WINDOW")
        self._root.change_attributes(event_mask=X.PropertyChangeMask)
        display.flush()

    def poll(self, timeout: float) -> bool:
        if self._drain():
            return True
        select.select([self._display.fileno()], [], [], timeout)
        return self._drain()

    def _drain(self) -> bool:
        from Xlib import X

        changed = False
        while self._display.pending_events():
            event = self._display.next_event()
            if event.type == X.PropertyNotify and event.atom == self._active_atom:
                changed = True
        return changed

    def active_window(self) -> Mapping[str, Any] | None:
        from Xlib import X, error

        try:
            prop = self._root.get_full_property(self._active_atom, X.AnyPropertyType)
            ident = int(prop.value[0]) if prop is not None and len(prop.value) else 0
            if not ident:
                return None
            return self._properties(self._display.create_resource_object("window", ident))
        except error.XError:
            return None

    def _properties(self, window: Any) -> Mapping[str, Any]:
        from Xlib import X

        display = self._display

        def full(name: str) -> Any:
            prop = window.get_full_property(display.intern_atom(name), X.AnyPropertyType)
            return None if prop is None else prop.value

        props: dict[str, Any] = {"WM_CLASS": window.get_wm_class(), "WM_NAME": window.get_wm_name()}
        title = full("_NET_WM_NAME")
        props["_NET_WM_NAME"] = title.decode("utf-8", "replace") if isinstance(title, bytes) else title
        pid = full("_NET_WM_PID")
        props["_NET_WM_PID"] = int(pid[0]) if pid is not None and len(pid) else 0
        types = full("_NET_WM_WINDOW_TYPE")
        props["_NET_WM_WINDOW_TYPE"] = [display.get_atom_name(int(atom)) for atom in types] if types is not None else []
        return props

    def pick(self, timeout: float) -> Mapping[str, Any] | None:
        display = self._display
        try:
            self._grab()
            return self._await_click(time.monotonic() + timeout)
        finally:
            for ungrab in (display.ungrab_keyboard, display.ungrab_pointer):
                try:
                    ungrab(0)
                except Exception:  # pylint: disable=broad-exception-caught
                    _log.debug("ungrab failed", exc_info=True)
            try:
                display.flush()
            except Exception:  # pylint: disable=broad-exception-caught
                _log.debug("flush after ungrab failed", exc_info=True)

    def _grab(self) -> None:
        from Xlib import X

        font = self._display.open_font("cursor")
        cursor = font.create_glyph_cursor(font, _XC_CROSSHAIR, _XC_CROSSHAIR + 1, (0, 0, 0), (65535, 65535, 65535))
        status = self._root.grab_pointer(
            False, X.ButtonPressMask, X.GrabModeAsync, X.GrabModeAsync, X.NONE, cursor, X.CurrentTime
        )
        if status != X.GrabSuccess:
            raise RuntimeError(f"cannot grab the pointer (status {status})")
        status = self._root.grab_keyboard(False, X.GrabModeAsync, X.GrabModeAsync, X.CurrentTime)
        if status != X.GrabSuccess:
            raise RuntimeError(f"cannot grab the keyboard (status {status})")

    def _await_click(self, deadline: float) -> Mapping[str, Any] | None:
        from Xlib import XK, X

        display = self._display
        escape = display.keysym_to_keycode(XK.XK_Escape)  # pylint: disable=no-member
        while True:
            while display.pending_events():
                event = display.next_event()
                if event.type == X.ButtonPress and event.detail in _PICK_BUTTONS:
                    return self._clicked(event.child)
                if event.type == X.KeyPress and event.detail == escape:
                    return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            select.select([display.fileno()], [], [], min(remaining, _POLL_INTERVAL))

    def _clicked(self, child: Any) -> Mapping[str, Any] | None:
        from Xlib import error

        if not child or getattr(child, "id", child) == 0:
            return None
        try:
            return self._properties(self._client_window(child))
        except error.XError:
            return None

    def _client_window(self, top: Any) -> Any:
        """Find the window carrying WM_CLASS beneath a possible reparenting frame."""
        queue = [top]
        while queue:
            window = queue.pop(0)
            if window.get_wm_class():
                return window
            queue.extend(window.query_tree().children)
        return top

    def close(self) -> None:
        self._display.close()


def _open_default() -> X11Transport:
    from Xlib import display as xdisplay

    return _XlibTransport(xdisplay.Display())


class X11Backend:
    """Focused-window detection and picking on X11 through python-xlib."""

    name = "x11"
    supports_pick = True

    def __init__(self, connect: Callable[[], X11Transport] = _open_default, pick_timeout: float = PICK_TIMEOUT) -> None:
        self._connect = connect
        self._pick_timeout = pick_timeout
        self._transport: X11Transport | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pick_lock = threading.Lock()
        self._lifecycle = threading.Lock()

    def available(self) -> BackendStatus:
        """Report whether an X display is set and can be opened."""
        if not os.environ.get("DISPLAY"):
            return BackendStatus("unavailable", "DISPLAY is not set")
        try:
            transport = self._connect()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return BackendStatus("unavailable", f"cannot open the X display ({exc})")
        _quietly(transport.close)
        return BackendStatus("active")

    def start(
        self, on_change: Callable[[WindowInfo], None], on_failure: Callable[[Exception], None] | None = None
    ) -> None:
        """Connect and start the listener, which reports the active window at once; raises when it cannot connect."""
        with self._lifecycle:
            self._stop_locked()
            transport = self._connect()
            self._transport = transport
            self._stop_event = stop_event = threading.Event()
            self._thread = threading.Thread(
                target=self._listen, args=(transport, stop_event, on_change, on_failure), name="x11-focus", daemon=True
            )
            self._thread.start()

    def _listen(
        self,
        transport: X11Transport,
        stop_event: threading.Event,
        on_change: Callable[[WindowInfo], None],
        on_failure: Callable[[Exception], None] | None,
    ) -> None:
        changed = True
        while not stop_event.is_set():
            try:
                props = transport.active_window() if changed else None
                changed = transport.poll(_POLL_INTERVAL)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                if not stop_event.is_set():
                    _log.exception("X11 focus listener failed")
                    if on_failure is not None:
                        on_failure(exc)
                return
            if props is None or stop_event.is_set():
                continue
            try:
                on_change(window_from_x11(props))
            except Exception:  # pylint: disable=broad-exception-caught
                _log.exception("focus callback failed")

    def stop(self) -> None:
        """Stop the listener and close the connection; never raises."""
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
            threading.Thread(target=self._run_pick, args=(on_result,), name="x11-pick", daemon=True).start()
        except Exception:  # pylint: disable=broad-exception-caught
            _log.exception("cannot start the window pick thread")
            self._pick_lock.release()
            on_result(None)

    def _run_pick(self, on_result: Callable[[WindowInfo | None], None]) -> None:
        result: WindowInfo | None = None
        try:
            result = self._grab_window()
        except Exception:  # pylint: disable=broad-exception-caught
            _log.exception("window pick failed")
        finally:
            self._pick_lock.release()
        try:
            on_result(result)
        except Exception:  # pylint: disable=broad-exception-caught
            _log.exception("pick callback failed")

    def _grab_window(self) -> WindowInfo | None:
        transport = self._connect()
        try:
            props = transport.pick(self._pick_timeout)
        finally:
            _quietly(transport.close)
        return None if props is None else window_from_x11(props)


def _quietly(action: Callable[[], object]) -> None:
    try:
        action()
    except Exception:  # pylint: disable=broad-exception-caught
        _log.debug("ignored error during cleanup", exc_info=True)
