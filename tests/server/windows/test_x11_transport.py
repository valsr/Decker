from array import array
from typing import Any

import pytest
from assertpy import assert_that

from decker.server.windows.x11 import X11Transport

pytest.importorskip("Xlib")

# Constants from Xlib.X, spelled out so event shapes are explicit.
PROPERTY_NOTIFY = 28
BUTTON_PRESS = 4
KEY_PRESS = 2
ATOMS = [
    "_NET_ACTIVE_WINDOW",
    "_NET_WM_NAME",
    "_NET_WM_PID",
    "_NET_WM_WINDOW_TYPE",
    "_NET_WM_WINDOW_TYPE_DIALOG",
    "_NET_CLIENT_LIST",
]


class FakeEvent:
    def __init__(self, kind: int, **fields: Any) -> None:
        self.type = kind
        for key, value in fields.items():
            setattr(self, key, value)


class FakeReply:
    def __init__(self, value: Any) -> None:
        self.value = value


class FakeWindow:
    def __init__(
        self,
        ident: int,
        display: "FakeDisplay",
        props: dict[str, Any] | None = None,
        wm_class: Any = ("inst", "Clicked"),
    ) -> None:
        self.id = ident
        self.display = display
        self.props = props or {}
        self.wm_class = wm_class
        self.wm_name: str | None = "legacy"

    def grab_pointer(self, *args: Any) -> int:
        self.display.log.append("grab_pointer")
        return self.display.grab_status

    def grab_keyboard(self, *args: Any) -> int:
        self.display.log.append("grab_keyboard")
        return 0

    def query_tree(self) -> Any:
        return FakeEvent(0, children=[])

    def get_wm_class(self) -> Any:
        return self.wm_class

    def get_wm_name(self) -> str | None:
        return self.wm_name

    def get_full_property(self, atom: int, kind: int) -> FakeReply | None:
        value = self.props.get(self.display.get_atom_name(atom))
        return None if value is None else FakeReply(value)

    def change_attributes(self, **kwargs: Any) -> None:
        self.display.log.append("change_attributes")


class FakeFont:
    def create_glyph_cursor(self, *args: Any) -> int:
        return 5


class FakeDisplay:
    def __init__(self, events: list[FakeEvent] | None = None) -> None:
        import os

        self.events = events or []
        self.log: list[str] = []
        self.grab_status = 0
        self.root = FakeWindow(1, self)
        self.windows: dict[int, FakeWindow] = {}
        self._pipe = os.pipe()

    def child(self, ident: int) -> FakeWindow:
        return self.create_resource_object("window", ident)

    def screen(self) -> Any:
        return FakeEvent(0, root=self.root)

    def open_font(self, name: str) -> FakeFont:
        return FakeFont()

    def intern_atom(self, name: str) -> int:
        if name not in ATOMS:
            ATOMS.append(name)
        return 100 + ATOMS.index(name)

    def get_atom_name(self, atom: int) -> str:
        return ATOMS[atom - 100]

    def keysym_to_keycode(self, keysym: int) -> int:
        return 9

    def create_resource_object(self, kind: str, ident: int) -> FakeWindow:
        return self.windows.setdefault(ident, FakeWindow(ident, self))

    def pending_events(self) -> int:
        return len(self.events)

    def next_event(self) -> FakeEvent:
        return self.events.pop(0)

    def fileno(self) -> int:
        return self._pipe[0]

    def ungrab_pointer(self, when: int) -> None:
        self.log.append("ungrab_pointer")

    def ungrab_keyboard(self, when: int) -> None:
        self.log.append("ungrab_keyboard")

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.log.append("close")


def _real(display: FakeDisplay) -> X11Transport:
    from decker.server.windows.x11 import _XlibTransport

    return _XlibTransport(display)


def _click(button: int, child: FakeWindow) -> FakeEvent:
    return FakeEvent(BUTTON_PRESS, child=child, detail=button)


def test_pick_click_takes_child_of_root_and_ungrabs() -> None:
    display = FakeDisplay()
    display.events.append(_click(1, display.child(77)))
    result = _real(display).pick(1.0)
    assert result is not None
    assert_that(result["WM_CLASS"]).is_equal_to(("inst", "Clicked"))
    assert_that(display.log).contains("grab_pointer", "ungrab_pointer", "ungrab_keyboard")


def test_pick_ignores_scroll_buttons_until_a_real_click() -> None:
    display = FakeDisplay()
    display.events = [_click(button, display.child(66)) for button in (4, 5, 6, 7)]
    display.events.append(_click(1, display.child(77)))
    result = _real(display).pick(1.0)
    assert result is not None
    assert_that(display.events).is_empty()


def test_pick_scroll_only_then_timeout_gives_none() -> None:
    display = FakeDisplay()
    display.events.append(_click(4, display.child(66)))
    assert_that(_real(display).pick(0.05)).is_none()


@pytest.mark.parametrize("button", [2, 3])
def test_pick_accepts_middle_and_right_buttons(button: int) -> None:
    display = FakeDisplay()
    display.events.append(_click(button, display.child(77)))
    assert_that(_real(display).pick(1.0)).is_not_none()


def test_pick_escape_returns_none_and_ungrabs() -> None:
    display = FakeDisplay([FakeEvent(KEY_PRESS, detail=9)])
    assert_that(_real(display).pick(1.0)).is_none()
    assert_that(display.log).contains("ungrab_pointer", "ungrab_keyboard")


def test_pick_timeout_returns_none_and_ungrabs() -> None:
    display = FakeDisplay()
    assert_that(_real(display).pick(0.05)).is_none()
    assert_that(display.log).contains("ungrab_pointer", "ungrab_keyboard")


def test_pick_grab_failure_raises_after_ungrab() -> None:
    display = FakeDisplay()
    display.grab_status = 1
    with pytest.raises(RuntimeError):
        _real(display).pick(1.0)
    assert_that(display.log).contains("ungrab_pointer")


def test_pick_error_during_wait_still_ungrabs() -> None:
    display = FakeDisplay()

    def broken() -> FakeEvent:
        raise ConnectionError("lost")

    display.pending_events = lambda: 1  # type: ignore[method-assign]
    display.next_event = broken  # type: ignore[method-assign]
    with pytest.raises(ConnectionError):
        _real(display).pick(1.0)
    assert_that(display.log).contains("ungrab_pointer", "ungrab_keyboard")


def _focused(display: FakeDisplay, ident: int = 50) -> FakeWindow:
    window = display.create_resource_object("window", ident)
    display.root.props["_NET_ACTIVE_WINDOW"] = array("I", [ident])
    return window


def test_active_window_parses_real_property_shapes() -> None:
    display = FakeDisplay()
    transport = _real(display)
    window = _focused(display)
    window.wm_class = ("navigator", "firefox")
    window.props = {
        "_NET_WM_NAME": "Zażółć – Firefox".encode("utf-8"),
        "_NET_WM_PID": array("I", [4321]),
        "_NET_WM_WINDOW_TYPE": array("I", [display.intern_atom("_NET_WM_WINDOW_TYPE_DIALOG")]),
    }
    props = transport.active_window()
    assert props is not None
    assert_that(props["WM_CLASS"]).is_equal_to(("navigator", "firefox"))
    assert_that(props["_NET_WM_NAME"]).is_equal_to("Zażółć – Firefox")
    assert_that(props["_NET_WM_PID"]).is_equal_to(4321)
    assert_that(props["_NET_WM_WINDOW_TYPE"]).is_equal_to(["_NET_WM_WINDOW_TYPE_DIALOG"])
    assert_that(props["WM_NAME"]).is_equal_to("legacy")


def test_active_window_without_optional_properties() -> None:
    display = FakeDisplay()
    transport = _real(display)
    window = _focused(display)
    window.wm_class = None
    window.wm_name = None
    props = transport.active_window()
    assert props is not None
    assert_that(props["_NET_WM_PID"]).is_equal_to(0)
    assert_that(props["_NET_WM_WINDOW_TYPE"]).is_empty()
    assert_that(props["_NET_WM_NAME"]).is_none()


def test_active_window_none_when_unset_or_zero() -> None:
    display = FakeDisplay()
    transport = _real(display)
    assert_that(transport.active_window()).is_none()
    display.root.props["_NET_ACTIVE_WINDOW"] = array("I", [0])
    assert_that(transport.active_window()).is_none()


def test_active_window_vanished_is_none() -> None:
    from Xlib import error

    display = FakeDisplay()
    transport = _real(display)
    window = _focused(display)

    class Gone(error.BadWindow):
        def __init__(self) -> None:  # pylint: disable=super-init-not-called
            Exception.__init__(self, "gone")

    def gone() -> Any:
        raise Gone()

    window.get_wm_class = gone  # type: ignore[method-assign]
    assert_that(transport.active_window()).is_none()


def test_poll_reports_only_active_window_property_notify() -> None:
    display = FakeDisplay()
    transport = _real(display)
    other = display.intern_atom("_NET_CLIENT_LIST")
    active = display.intern_atom("_NET_ACTIVE_WINDOW")
    display.events.append(FakeEvent(PROPERTY_NOTIFY, atom=other))
    assert_that(transport.poll(0.01)).is_false()
    display.events.append(FakeEvent(PROPERTY_NOTIFY, atom=other))
    display.events.append(FakeEvent(PROPERTY_NOTIFY, atom=active))
    assert_that(transport.poll(0.01)).is_true()
    assert_that(display.events).is_empty()


def test_transport_selects_property_changes_on_root_and_closes() -> None:
    display = FakeDisplay()
    transport = _real(display)
    assert_that(display.log).contains("change_attributes")
    transport.close()
    assert_that(display.log).contains("close")
