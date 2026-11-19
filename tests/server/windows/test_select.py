from assertpy import assert_that

from decker.server.windows.select import select_backend, select_backend_name

PLASMA = {"XDG_CURRENT_DESKTOP": "KDE", "WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":1"}


def test_select_plasma_wayland() -> None:
    assert_that(select_backend_name(PLASMA, "linux")).is_equal_to("kwin")


def test_select_x11() -> None:
    assert_that(select_backend_name({"DISPLAY": ":0", "XDG_CURRENT_DESKTOP": "KDE"}, "linux")).is_equal_to("x11")


def test_select_windows() -> None:
    assert_that(select_backend_name({}, "win32")).is_equal_to("windows")


def test_select_no_session_is_unavailable() -> None:
    assert_that(select_backend_name({}, "linux")).is_equal_to("none")
    backend = select_backend({}, "linux")
    status = backend.available()
    assert_that(status.state).is_equal_to("unavailable")
    assert_that(status.reason).is_equal_to("no desktop session")
    assert_that(backend.supports_pick).is_false()


def test_select_gnome_wayland_is_unsupported() -> None:
    env = {"XDG_CURRENT_DESKTOP": "GNOME", "WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}
    assert_that(select_backend_name(env, "linux")).is_equal_to("unsupported")
    status = select_backend(env, "linux").available()
    assert_that(status.state).is_equal_to("unsupported")
    assert_that(status.reason).contains("GNOME")
