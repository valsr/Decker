"""Locate and read action icon images declared in plugin manifests."""

import logging
from pathlib import Path

MAX_ICON_BYTES = 256 * 1024
# Elgato manifests name icons without an extension; @2x is the high-resolution variant.
_CANDIDATE_SUFFIXES = ("", ".svg", "@2x.png", ".png")


def resolve_icon(plugin_dir: Path, icon: str | None) -> Path | None:
    """Return the icon file for a manifest Icon entry, or None if it is unset, missing or outside plugin_dir."""
    if not icon:
        return None
    root = plugin_dir.resolve()
    for suffix in _CANDIDATE_SUFFIXES:
        candidate = (root / f"{icon}{suffix}").resolve()
        if not candidate.is_relative_to(root):
            logging.warning("Ignoring icon %r: it points outside %s", icon, plugin_dir)
            return None
        if candidate.is_file():
            return candidate
    return None


def read_icon(plugin_dir: Path, icon: str | None) -> bytes | None:
    """Return the icon's bytes, or None if it cannot be found, read, or exceeds MAX_ICON_BYTES."""
    path = resolve_icon(plugin_dir, icon)
    if path is None:
        return None
    try:
        if path.stat().st_size > MAX_ICON_BYTES:
            logging.warning("Ignoring icon %s: larger than %d bytes", path, MAX_ICON_BYTES)
            return None
        return path.read_bytes()
    except OSError as exc:
        logging.warning("Could not read icon %s: %s", path, exc)
        return None
