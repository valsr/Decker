"""Plasma (KWin 6) window backend: a KWin script reports focus over D-Bus, queryWindowInfo picks a window."""

# jeepney is Linux-only, so it is imported lazily inside the transport.
# pylint: disable=import-outside-toplevel

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

import psutil

from decker.common.model import WindowInfo
from decker.server.windows.backend import BackendStatus

SCRIPT_NAME = "decker-window-watcher"
BUS_NAME = "org.decker.WindowWatcher"
PICK_TIMEOUT = 120.0
_CALL_TIMEOUT = 5.0
_POLL_INTERVAL = 0.25
_NET_TYPE_NAMES: dict[int, str] = {0: "normal"}
_PRIMARY_OWNER = 1
_KWIN = "org.kde.KWin"

_log = logging.getLogger(__name__)


class DBusError(Exception):
    """A D-Bus error reply; name is the D-Bus error name."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


@dataclass(frozen=True)
class DBusCall:
    """One D-Bus method call."""

    destination: str
    path: str
    interface: str
    member: str
    signature: str = ""
    args: tuple[Any, ...] = ()


class DBusTransport(Protocol):
    """The D-Bus operations the backend needs; the only part faked in tests."""

    def request_name(self, name: str) -> int:
        """Claim a bus name and return the RequestName reply code."""
        ...

    def release_name(self, name: str) -> None:
        """Give up a bus name."""
        ...

    def call(self, request: DBusCall, timeout: float) -> tuple[Any, ...]:
        """Call a method and return the reply body; raises DBusError on an error reply."""
        ...

    def poll(self, timeout: float) -> str | None:
        """Wait for one incoming Focused call, answer it and return its string argument."""
        ...

    def close(self) -> None:
        """Close the connection."""
        ...


class _JeepneyTransport:  # pylint: disable=missing-function-docstring
    def __init__(self) -> None:
        from jeepney.io.blocking import open_dbus_connection

        self._conn = open_dbus_connection(bus="SESSION")

    def request_name(self, name: str) -> int:
        from jeepney.bus_messages import DBus

        reply = self._conn.send_and_get_reply(DBus().RequestName(name), timeout=_CALL_TIMEOUT)
        return int(reply.body[0])

    def release_name(self, name: str) -> None:
        from jeepney.bus_messages import DBus

        self._conn.send_and_get_reply(DBus().ReleaseName(name), timeout=_CALL_TIMEOUT)

    def call(self, request: DBusCall, timeout: float) -> tuple[Any, ...]:
        from jeepney import (
            DBusAddress,
            MessageType,
            new_method_call,
        )

        address = DBusAddress(request.path, bus_name=request.destination, interface=request.interface)
        reply = self._conn.send_and_get_reply(
            new_method_call(address, request.member, request.signature, request.args), timeout=timeout
        )
        if reply.header.message_type == MessageType.error:
            raise DBusError(str(reply.header.fields.get(4, "")))
        return tuple(reply.body)

    def poll(self, timeout: float) -> str | None:
        from jeepney import (
            MessageType,
            new_method_return,
        )

        try:
            message = self._conn.receive(timeout=timeout)
        except TimeoutError:
            return None
        if message.header.message_type != MessageType.method_call:
            return None
        self._conn.send_message(new_method_return(message))
        if message.header.fields.get(3) != "Focused" or not message.body:
            return None
        return str(message.body[0])

    def close(self) -> None:
        self._conn.close()


def _executable(pid: int) -> str:
    if pid <= 0:
        return ""
    try:
        return os.path.basename(psutil.Process(pid).exe())
    except psutil.Error:
        return ""


def window_from_kwin(payload: Mapping[str, Any]) -> WindowInfo:
    """Map a focus report or a queryWindowInfo result to a WindowInfo."""
    pid = int(payload.get("pid") or 0)
    if "windowType" in payload:
        window_type = str(payload["windowType"])
    else:
        window_type = _NET_TYPE_NAMES.get(payload.get("type", -1), "")
    return WindowInfo(
        window_class=str(payload.get("resourceClass") or ""),
        window_type=window_type,
        title=str(payload.get("caption") or ""),
        executable=_executable(pid),
        desktop_file=str(payload.get("desktopFileName") or payload.get("desktopFile") or ""),
        pid=pid,
    )


def _kwin_call(path: str, interface: str, member: str, signature: str = "", args: tuple[Any, ...] = ()) -> DBusCall:
    return DBusCall(_KWIN, path, interface, member, signature, args)


def _open_default() -> DBusTransport:
    return _JeepneyTransport()


class KWinBackend:
    """Focused-window detection and picking on Plasma 6 through a KWin script and D-Bus."""

    name = "kwin"
    supports_pick = True

    def __init__(self, connect: Callable[[], DBusTransport] = _open_default) -> None:
        self._connect = connect
        self._control: DBusTransport | None = None
        self._receiver: DBusTransport | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pick_lock = threading.Lock()
        self._lifecycle = threading.Lock()

    @staticmethod
    def script_path() -> Path:
        """Location of the packaged KWin script."""
        return Path(__file__).with_name("kwin_script.js")

    def available(self) -> BackendStatus:
        """Report whether a session bus with KWin 6 is reachable."""
        try:
            transport = self._connect()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return BackendStatus("unavailable", f"no D-Bus session bus ({exc})")
        try:
            return self._probe(transport)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return BackendStatus("unavailable", f"cannot query {_KWIN} ({exc})")
        finally:
            _quietly(transport.close)

    @staticmethod
    def _probe(transport: DBusTransport) -> BackendStatus:
        has_owner = transport.call(
            DBusCall(
                "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner", "s", (_KWIN,)
            ),
            _CALL_TIMEOUT,
        )
        if not has_owner or not has_owner[0]:
            return BackendStatus("unavailable", f"{_KWIN} is not on the session bus")
        info = transport.call(_kwin_call("/KWin", _KWIN, "supportInformation"), _CALL_TIMEOUT)
        match = re.search(r"KWin version:\s*(\d+)", str(info[0]) if info else "")
        if match and int(match.group(1)) < 6:
            return BackendStatus("unavailable", f"KWin 6 or newer is required, found {match.group(1)}")
        return BackendStatus("active")

    def start(
        self, on_change: Callable[[WindowInfo], None], on_failure: Callable[[Exception], None] | None = None
    ) -> None:
        """Claim the callback bus name, then (re)load the KWin script; raises when that is impossible."""
        with self._lifecycle:
            self._stop_locked()
            try:
                self._start_locked(on_change, on_failure)
            except BaseException:
                self._stop_locked()
                raise

    def _start_locked(
        self, on_change: Callable[[WindowInfo], None], on_failure: Callable[[Exception], None] | None
    ) -> None:
        receiver = self._receiver = self._connect()
        if receiver.request_name(BUS_NAME) != _PRIMARY_OWNER:
            raise RuntimeError(f"cannot claim D-Bus name {BUS_NAME}; another Decker server may be running")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._listen, args=(receiver, on_change, on_failure), name="kwin-focus", daemon=True
        )
        self._thread.start()
        control = self._control = self._connect()
        scripting = "org.kde.kwin.Scripting"
        control.call(_kwin_call("/Scripting", scripting, "unloadScript", "s", (SCRIPT_NAME,)), _CALL_TIMEOUT)
        loaded = control.call(
            _kwin_call("/Scripting", scripting, "loadScript", "ss", (str(self.script_path()), SCRIPT_NAME)),
            _CALL_TIMEOUT,
        )
        if not loaded or int(loaded[0]) < 0:
            raise RuntimeError(f"KWin did not load the {SCRIPT_NAME} script")
        control.call(_kwin_call("/Scripting", scripting, "start"), _CALL_TIMEOUT)

    def _listen(
        self,
        receiver: DBusTransport,
        on_change: Callable[[WindowInfo], None],
        on_failure: Callable[[Exception], None] | None,
    ) -> None:
        while not self._stop_event.is_set():
            try:
                raw = receiver.poll(_POLL_INTERVAL)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                if not self._stop_event.is_set():
                    _log.exception("KWin focus listener failed")
                    if on_failure is not None:
                        on_failure(exc)
                return
            if raw is None:
                continue
            try:
                payload = json.loads(raw)
                info = window_from_kwin(payload)
            except (ValueError, TypeError, AttributeError, OverflowError):
                _log.warning("ignoring malformed focus report")
                continue
            try:
                on_change(info)
            except Exception:  # pylint: disable=broad-exception-caught
                _log.exception("focus callback failed")

    def stop(self) -> None:
        """Unload the script, release the bus name and stop the listener; never raises."""
        with self._lifecycle:
            self._stop_locked()

    def _stop_locked(self) -> None:
        self._stop_event.set()
        control, receiver, thread = self._control, self._receiver, self._thread
        self._control = self._receiver = self._thread = None
        if control is not None:
            unload = _kwin_call("/Scripting", "org.kde.kwin.Scripting", "unloadScript", "s", (SCRIPT_NAME,))
            _quietly(lambda: control.call(unload, _CALL_TIMEOUT))
            _quietly(control.close)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        if receiver is not None:
            _quietly(lambda: receiver.release_name(BUS_NAME))
            _quietly(receiver.close)

    def pick(self, on_result: Callable[[WindowInfo | None], None]) -> None:
        """Ask KWin to let the user click a window; on_result gets the window or None, exactly once."""
        if not self._pick_lock.acquire(blocking=False):  # pylint: disable=consider-using-with
            on_result(None)
            return
        threading.Thread(target=self._run_pick, args=(on_result,), name="kwin-pick", daemon=True).start()

    def _run_pick(self, on_result: Callable[[WindowInfo | None], None]) -> None:
        result: WindowInfo | None = None
        try:
            result = self._query_window()
        except DBusError as exc:
            _log.info("window pick ended: %s", exc.name)
        except Exception:  # pylint: disable=broad-exception-caught
            _log.exception("window pick failed")
        finally:
            self._pick_lock.release()
        try:
            on_result(result)
        except Exception:  # pylint: disable=broad-exception-caught
            _log.exception("pick callback failed")

    def _query_window(self) -> WindowInfo | None:
        transport = self._connect()  # pylint: disable=consider-using-with
        try:
            body = transport.call(_kwin_call("/KWin", _KWIN, "queryWindowInfo"), PICK_TIMEOUT)
        finally:
            _quietly(transport.close)
        values = {key: variant[1] for key, variant in body[0].items()}
        return window_from_kwin(values)


def _quietly(action: Callable[[], object]) -> None:
    try:
        action()
    except Exception:  # pylint: disable=broad-exception-caught
        _log.debug("ignored error during cleanup", exc_info=True)
