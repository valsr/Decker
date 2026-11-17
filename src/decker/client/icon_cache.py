"""Two-level cache of rasterized icon thumbnails: an in-memory LRU in front of PNG files on disk.

A thumbnail is keyed by pack id, plugin version, icon path, size and tint, so a plugin update (new version) never
shows a stale icon, and the older versions are deleted. Nothing here ever raises: a cache problem is a cache miss.
"""

import hashlib
import logging
import os
import re
import shutil
import uuid
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from PyQt6.QtGui import QPixmap

from decker.common import paths

logger = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_DEFAULT_MAX_MEMORY = 2048
_MemoryKey = tuple[str, str, str, int, str]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()[:32]


def _slug(value: str) -> str:
    """``value`` as a directory name; anything that is not plainly safe is replaced by a hash."""
    return value if _SAFE_NAME.match(value) and value not in (".", "..") else _digest(value)


def _tint_slug(tint: str | None) -> str:
    return "none" if tint is None else _slug(tint.lstrip("#").lower())


class IconThumbnailCache:
    """Memory LRU + PNG files under ``root`` (default: the configured ``<prefix>/.decker/cache/icons``)."""

    def __init__(self, root: Path | None = None, max_memory: int = _DEFAULT_MAX_MEMORY) -> None:
        self._root_override = root
        self._max_memory = max_memory
        self._versions: dict[str, str] = {}
        self._memory: OrderedDict[_MemoryKey, QPixmap] = OrderedDict()
        self._warned = False

    def version_of(self, pack_id: str) -> str | None:
        """The plugin version the server reported for ``pack_id``, or None when unknown."""
        return self._versions.get(pack_id)

    def update_packs(self, packs: Iterable[Mapping[str, Any]]) -> None:
        """Learn each pack's plugin version and delete what an update or an uninstall made stale."""
        listed: set[str] = set()
        versions: dict[str, str] = {}
        for pack in packs:
            if not isinstance(pack, Mapping) or not pack.get("id"):
                continue
            pack_id = str(pack["id"])
            listed.add(pack_id)
            if pack.get("plugin_version"):
                versions[pack_id] = str(pack["plugin_version"])
        self._versions = versions
        for key in [k for k in self._memory if versions.get(k[0]) != k[1]]:
            del self._memory[key]
        self._prune_disk(listed, versions)

    def get(self, pack_id: str, path: str, size: int, tint: str | None) -> QPixmap | None:
        """The cached thumbnail (memory, then disk), or None on a miss or when the pack's version is unknown."""
        version = self._versions.get(pack_id)
        if version is None:
            return None
        key = (pack_id, version, path, size, tint or "")
        hit = self._memory.get(key)
        if hit is not None:
            self._memory.move_to_end(key)
            return hit
        pixmap = self._read(self._file(pack_id, version, path, size, tint))
        if pixmap is not None:
            self._remember(key, pixmap)
        return pixmap

    def put(self, pack_id: str, path: str, size: int, tint: str | None, pixmap: QPixmap) -> None:
        """Store a thumbnail in memory and on disk (atomically); does nothing when the pack's version is unknown."""
        version = self._versions.get(pack_id)
        if version is None:
            return
        self._remember((pack_id, version, path, size, tint or ""), pixmap)
        self._write(self._file(pack_id, version, path, size, tint), pixmap)

    def _root(self) -> Path:
        return self._root_override if self._root_override is not None else paths.icon_cache()

    def _file(self, pack_id: str, version: str, path: str, size: int, tint: str | None) -> Path:
        return self._root() / _slug(pack_id) / _slug(version) / f"{size}-{_tint_slug(tint)}" / f"{_digest(path)}.png"

    def _remember(self, key: _MemoryKey, pixmap: QPixmap) -> None:
        self._memory[key] = pixmap
        self._memory.move_to_end(key)
        while len(self._memory) > self._max_memory:
            self._memory.popitem(last=False)

    def _read(self, file: Path) -> QPixmap | None:
        try:
            if not file.is_file():
                return None
            pixmap = QPixmap(str(file)) if file.stat().st_size > 0 else QPixmap()
            if pixmap.isNull():
                file.unlink(missing_ok=True)  # corrupt or empty: forget it, the next render replaces it
                return None
            return pixmap
        except OSError as exc:
            self._note("read", exc)
            return None

    def _write(self, file: Path, pixmap: QPixmap) -> None:
        temp = file.with_name(f"{file.name}.{os.getpid()}-{uuid.uuid4().hex[:8]}.tmp")
        try:
            file.parent.mkdir(parents=True, exist_ok=True)
            if pixmap.save(str(temp), "PNG"):
                os.replace(temp, file)
            else:
                temp.unlink(missing_ok=True)
        except OSError as exc:
            self._note("write", exc)
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def _prune_disk(self, listed: set[str], versions: dict[str, str]) -> None:
        root = self._root()
        keep_packs = {_slug(pack_id) for pack_id in listed}
        keep_versions = {_slug(pack_id): _slug(version) for pack_id, version in versions.items()}
        try:
            entries = list(root.iterdir()) if root.is_dir() else []
        except OSError as exc:
            self._note("prune", exc)
            return
        for entry in entries:
            self._prune_pack(entry, keep_packs, keep_versions)

    def _prune_pack(self, pack_dir: Path, keep_packs: set[str], keep_versions: dict[str, str]) -> None:
        """Delete what an uninstall or update made stale below one pack directory; a failure stops only this pack."""
        try:
            if pack_dir.name not in keep_packs:
                _remove(pack_dir)
            elif pack_dir.name in keep_versions and not pack_dir.is_symlink() and pack_dir.is_dir():
                for version_dir in list(pack_dir.iterdir()):
                    if version_dir.name != keep_versions[pack_dir.name]:
                        _remove(version_dir)
        except OSError as exc:
            self._note("prune", exc)

    def _note(self, what: str, exc: OSError) -> None:
        if not self._warned:  # once, not once per icon: a broken cache directory would otherwise spam the log
            self._warned = True
            logger.debug("icon cache %s failed (further failures are not logged): %s", what, exc)


def _remove(path: Path) -> None:
    """Delete a cache directory, or just the link if it is a symlink (never follow it); anything else is not ours."""
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


_INSTANCE: IconThumbnailCache | None = None


def icon_cache() -> IconThumbnailCache:
    """The process-wide thumbnail cache."""
    global _INSTANCE  # pylint: disable=global-statement
    if _INSTANCE is None:
        _INSTANCE = IconThumbnailCache()
    return _INSTANCE
