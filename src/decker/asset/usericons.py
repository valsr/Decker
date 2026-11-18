"""The user's own imported icons, stored as plain files in the user icons folder."""

import re
from pathlib import Path
from typing import Any

from decker.common.paths import user_icons
from decker.plugin.icons import MAX_ICON_BYTES

USER_PACK_ID = "decker.user"
USER_PLUGIN_ID = "decker.user"
USER_PLUGIN_NAME = "User"

_EXTENSIONS = (".svg", ".png", ".gif")
_MAX_ID_LENGTH = 64
_INVALID = re.compile(r"[^a-z0-9_-]+")


def normalize_id(name: str) -> str:
    """Return the icon id for a name (lowercase ``[a-z0-9_-]``), or ``""`` when nothing usable remains."""
    text = _INVALID.sub("-", name.lower()).strip("-_")
    return text[:_MAX_ID_LENGTH].strip("-_")


class UserIcons:
    """Listing and reading of the icons in the user icons folder."""

    def __init__(self, directory: Path | None = None) -> None:
        self._directory: Path | None = directory

    @property
    def directory(self) -> Path:
        """The icons folder (the default is resolved on every use)."""
        return self._directory if self._directory is not None else user_icons()

    def list_icons(self) -> list[str]:
        """Sorted file names of the icons present."""
        try:
            entries = list(self.directory.iterdir())
        except OSError:
            return []
        return sorted(p.name for p in entries if p.suffix.lower() in _EXTENSIONS and p.is_file())

    def read_icon(self, name: str) -> bytes | None:
        """Return the icon's bytes, or None when it is not listed or too large."""
        if name not in self.list_icons():
            return None
        path = self.directory / name
        try:
            if path.stat().st_size > MAX_ICON_BYTES:
                return None
            return path.read_bytes()
        except OSError:
            return None

    def pack_info(self) -> dict[str, Any]:
        """The pack entry for the icon pack listing."""
        return {
            "id": USER_PACK_ID,
            "name": USER_PLUGIN_NAME,
            "description": "Icons you imported",
            "plugin_id": USER_PLUGIN_ID,
            "plugin_name": USER_PLUGIN_NAME,
            "plugin_version": "1",
            "icon_count": len(self.list_icons()),
        }

    def exists(self, icon_id: str) -> bool:
        """Whether an icon with this id exists under any supported extension."""
        return any(Path(name).stem == icon_id for name in self.list_icons())

    def suggest_id(self, name: str) -> str:
        """The first free id for a name: ``id``, ``id-2``, ``id-3``, ..."""
        base = normalize_id(name) or "icon"
        candidate, number = base, 2
        while self.exists(candidate):
            candidate = f"{base}-{number}"
            number += 1
        return candidate
