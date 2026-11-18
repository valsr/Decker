from typing import Any

import pytest
from assertpy import assert_that

from decker.common.platforms import (
    HostPlatform,
    PlatformSpec,
    detect_platform,
    parse_platform_spec,
    platform_supports,
)


@pytest.mark.parametrize(
    "name,expected",
    [("linux", "linux"), ("win32", "windows"), ("darwin", "macos"), ("freebsd13", "freebsd")],
)
def test_detect_platform_maps_sys_platform_names(name: str, expected: str) -> None:
    assert_that(detect_platform({}, name).os).is_equal_to(expected)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("KDE", "kde"),
        ("ubuntu:GNOME", "gnome"),
        ("X-Cinnamon", "other"),
        ("kde", "kde"),
        ("", "unknown"),
        (None, "unknown"),
    ],
)
def test_detect_linux_desktop_spellings(value: str | None, expected: str) -> None:
    environ = {} if value is None else {"XDG_CURRENT_DESKTOP": value}
    assert_that(detect_platform(environ, "linux").desktop).is_equal_to(expected)


@pytest.mark.parametrize(
    "value,expected",
    [("wayland", "wayland"), ("x11", "x11"), ("tty", "unknown"), (None, "unknown")],
)
def test_detect_linux_session(value: str | None, expected: str) -> None:
    environ = {} if value is None else {"XDG_SESSION_TYPE": value}
    assert_that(detect_platform(environ, "linux").session).is_equal_to(expected)


def test_detect_non_linux_has_unknown_desktop_and_session() -> None:
    environ = {"XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "wayland"}
    host = detect_platform(environ, "win32")
    assert_that(host).is_equal_to(HostPlatform("windows", "unknown", "unknown"))


def test_label_formats() -> None:
    assert_that(HostPlatform("linux", "kde", "wayland").label()).is_equal_to("Linux (KDE, Wayland)")
    assert_that(HostPlatform("linux", "gnome", "wayland").label()).is_equal_to("Linux (GNOME, Wayland)")
    assert_that(HostPlatform("linux", "other").label()).is_equal_to("Linux (Other)")
    assert_that(HostPlatform("linux").label()).is_equal_to("Linux")
    assert_that(HostPlatform("windows").label()).is_equal_to("Windows")
    assert_that(HostPlatform("macos").label()).is_equal_to("macOS")
    assert_that(HostPlatform("freebsd").label()).is_equal_to("Freebsd")
    assert_that(HostPlatform("linux", "kde", "x11").to_payload()).is_equal_to(
        {"os": "linux", "desktop": "kde", "session": "x11"}
    )


def test_parse_returns_none_when_nothing_declared() -> None:
    assert_that(parse_platform_spec(None, None)).is_none()


@pytest.mark.parametrize(
    "platforms,linux",
    [
        ([], None),
        ("linux", None),
        (["linux", 3], None),
        (["windows"], {"desktops": ["kde"]}),
        (None, {"desktops": []}),
        (None, "kde"),
        (None, {"sessions": "x11"}),
    ],
)
def test_parse_rejects_malformed_values(platforms: Any, linux: Any) -> None:
    with pytest.raises(ValueError):
        parse_platform_spec(platforms, linux)


def test_parse_lowercases_and_keeps_unknown_names() -> None:
    spec = parse_platform_spec([" Linux ", "FreeBSD"], {"desktops": ["KDE"], "sessions": ["Wayland "]})
    assert_that(spec).is_equal_to(PlatformSpec(("linux", "freebsd"), ("kde",), ("wayland",)))


def test_supports_everything_without_a_spec() -> None:
    assert_that(platform_supports(None, HostPlatform("windows"))).is_true()


def test_supports_requires_the_host_os() -> None:
    spec = PlatformSpec(os=("linux",))
    assert_that(platform_supports(spec, HostPlatform("linux"))).is_true()
    assert_that(platform_supports(spec, HostPlatform("windows"))).is_false()


@pytest.mark.parametrize("os_name", ["linux", "windows", "macos"])
def test_unknown_os_only_matches_nothing_known(os_name: str) -> None:
    assert_that(platform_supports(PlatformSpec(os=("freebsd",)), HostPlatform(os_name))).is_false()


def test_linux_constraints_filter_desktop_and_session() -> None:
    spec = PlatformSpec(os=("linux",), desktops=("kde",), sessions=("wayland",))
    assert_that(platform_supports(spec, HostPlatform("linux", "kde", "wayland"))).is_true()
    assert_that(platform_supports(spec, HostPlatform("linux", "gnome", "wayland"))).is_false()
    assert_that(platform_supports(spec, HostPlatform("linux", "kde", "x11"))).is_false()


def test_unknown_host_values_satisfy_any_constraint() -> None:
    assert_that(platform_supports(PlatformSpec(desktops=("kde",)), HostPlatform("linux"))).is_true()
    assert_that(platform_supports(PlatformSpec(sessions=("wayland",)), HostPlatform("linux"))).is_true()


def test_linux_constraints_ignore_non_linux_hosts() -> None:
    spec = PlatformSpec(desktops=("kde",), sessions=("wayland",))
    assert_that(platform_supports(spec, HostPlatform("windows"))).is_true()


def test_to_payload_contains_only_set_keys() -> None:
    assert_that(PlatformSpec().to_payload()).is_equal_to({})
    assert_that(PlatformSpec(os=("linux",)).to_payload()).is_equal_to({"platforms": ["linux"]})
    assert_that(PlatformSpec(sessions=("x11",)).to_payload()).is_equal_to({"linux": {"sessions": ["x11"]}})
    full = PlatformSpec(("linux",), ("kde",), ("x11",)).to_payload()
    assert_that(full).is_equal_to({"platforms": ["linux"], "linux": {"desktops": ["kde"], "sessions": ["x11"]}})
