"""Chooses the window backend for the desktop session."""

import importlib
from typing import Mapping

from decker.server.windows.backend import WindowBackend
from decker.server.windows.unsupported import UnsupportedBackend

_MODULES: dict[str, tuple[str, str]] = {
    "kwin": ("decker.server.windows.kwin", "KWinBackend"),
    "x11": ("decker.server.windows.x11", "X11Backend"),
    "windows": ("decker.server.windows.windows", "WindowsBackend"),
}


def select_backend_name(env: Mapping[str, str], platform: str) -> str:
    """Name the backend for this session: kwin, x11, windows, unsupported or none."""
    if platform == "win32":
        return "windows"
    wayland = bool(env.get("WAYLAND_DISPLAY"))
    if wayland:
        return "kwin" if "KDE" in env.get("XDG_CURRENT_DESKTOP", "") else "unsupported"
    return "x11" if env.get("DISPLAY") else "none"


def select_backend(env: Mapping[str, str], platform: str) -> WindowBackend:
    """Build the window backend for the running desktop session."""
    name = select_backend_name(env, platform)
    if name == "none":
        return UnsupportedBackend("no desktop session", name="none", state="unavailable")
    if name == "unsupported":
        desktop = env.get("XDG_CURRENT_DESKTOP") or "this"
        return UnsupportedBackend(f"focused-window detection is not supported on {desktop} Wayland")
    module_name, class_name = _MODULES[name]
    try:
        backend_class = getattr(importlib.import_module(module_name), class_name)
    except ImportError:
        return UnsupportedBackend("backend module not available", name=name, state="unavailable")
    backend: WindowBackend = backend_class()
    return backend
