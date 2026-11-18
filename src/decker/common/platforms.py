import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

OS_NAMES: tuple[str, ...] = ("linux", "windows", "macos")
LINUX_DESKTOPS: tuple[str, ...] = ("kde", "gnome", "other")
LINUX_SESSIONS: tuple[str, ...] = ("wayland", "x11")
UNKNOWN = "unknown"

_OS_LABELS = {"macos": "macOS"}
_SYS_PLATFORMS = {"win32": "windows", "darwin": "macos"}


@dataclass(frozen=True)
class HostPlatform:
    os: str
    desktop: str = UNKNOWN
    session: str = UNKNOWN

    def label(self) -> str:
        """Human readable name, e.g. "Linux (KDE, Wayland)"; unknown parts are omitted."""
        name = _OS_LABELS.get(self.os, self.os.capitalize())
        parts: list[str] = []
        if self.desktop != UNKNOWN:
            parts.append("KDE" if self.desktop == "kde" else self.desktop.capitalize())
        if self.session != UNKNOWN:
            parts.append(self.session.capitalize())
        return f"{name} ({', '.join(parts)})" if parts else name

    def to_payload(self) -> dict[str, str]:
        return {"os": self.os, "desktop": self.desktop, "session": self.session}


def _detect_desktop(environ: Mapping[str, str]) -> str:
    value = environ.get("XDG_CURRENT_DESKTOP", "").strip().lower()
    if not value:
        return UNKNOWN
    if "kde" in value:
        return "kde"
    if "gnome" in value:
        return "gnome"
    return "other"


def detect_platform(environ: Mapping[str, str] | None = None, platform_name: str | None = None) -> HostPlatform:
    """Describe the host from environment variables and `sys.platform`."""
    env = os.environ if environ is None else environ
    raw = (sys.platform if platform_name is None else platform_name).lower()
    if raw.startswith("linux"):
        session = env.get("XDG_SESSION_TYPE", "").strip().lower()
        return HostPlatform("linux", _detect_desktop(env), session if session in LINUX_SESSIONS else UNKNOWN)
    if raw in _SYS_PLATFORMS:
        return HostPlatform(_SYS_PLATFORMS[raw])
    return HostPlatform(raw.rstrip("0123456789.") or raw)


@dataclass(frozen=True)
class PlatformSpec:
    os: tuple[str, ...] | None = None
    desktops: tuple[str, ...] | None = None
    sessions: tuple[str, ...] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.os is not None:
            payload["platforms"] = list(self.os)
        linux: dict[str, list[str]] = {}
        if self.desktops is not None:
            linux["desktops"] = list(self.desktops)
        if self.sessions is not None:
            linux["sessions"] = list(self.sessions)
        if linux:
            payload["linux"] = linux
        return payload


def _parse_names(value: Any, what: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{what} must be a non-empty list of names")
    names: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{what} must contain only non-empty strings")
        names.append(item.strip().lower())
    return tuple(names)


def _parse_linux(linux: Any) -> tuple[tuple[str, ...] | None, tuple[str, ...] | None]:
    if not isinstance(linux, dict):
        raise ValueError("'linux' must be an object")
    desktops = _parse_names(linux["desktops"], "'linux.desktops'") if "desktops" in linux else None
    sessions = _parse_names(linux["sessions"], "'linux.sessions'") if "sessions" in linux else None
    return desktops, sessions


def parse_platform_spec(platforms: Any, linux: Any) -> PlatformSpec | None:
    """Validate the `platforms`/`linux` manifest fields; raise ValueError with a message when malformed."""
    if platforms is None and linux is None:
        return None
    os_names = _parse_names(platforms, "'platforms'") if platforms is not None else None
    desktops, sessions = _parse_linux(linux) if linux is not None else (None, None)
    if linux is not None and os_names is not None and "linux" not in os_names:
        raise ValueError("'linux' requires 'platforms' to include linux")
    return PlatformSpec(os_names, desktops, sessions)


def platform_supports(spec: PlatformSpec | None, host: HostPlatform) -> bool:
    """Whether the host satisfies the spec; unknown host desktop/session satisfy any constraint."""
    if spec is None:
        return True
    if spec.os is not None and host.os not in spec.os:
        return False
    if host.os != "linux":
        return True
    if spec.desktops is not None and host.desktop != UNKNOWN and host.desktop not in spec.desktops:
        return False
    return spec.sessions is None or host.session == UNKNOWN or host.session in spec.sessions
