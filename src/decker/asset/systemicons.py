"""The system's freedesktop icon theme, indexed so it can be served as virtual icon packs."""

import configparser
import hashlib
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from decker.common import config
from decker.plugin.icons import MAX_ICON_BYTES

SYSTEM_PLUGIN_ID = "decker.system"
SYSTEM_PLUGIN_NAME = "System Icons"
PACK_PREFIX = "decker.system."
CATEGORIES: tuple[tuple[str, str], ...] = (
    ("actions", "Actions"),
    ("applications", "Applications"),
    ("categories", "Categories"),
    ("devices", "Devices"),
    ("emblems", "Emblems"),
    ("emotes", "Emotes"),
    ("mimetypes", "Mimetypes"),
    ("places", "Places"),
    ("status", "Status"),
    ("other", "Other"),
)
IMAGE_SUFFIXES = (".svg", ".png", ".jpg", ".jpeg")
_KNOWN_CATEGORIES = {key for key, _label in CATEGORIES} - {"other"}
_FALLBACK_THEMES = ("Adwaita", "hicolor")


@dataclass(frozen=True)
class ThemeIndex:
    """The icons of one theme chain: category key -> icon name -> the file to serve."""

    theme: str
    version: str
    icons: Mapping[str, Mapping[str, Path]]


def category_of(context: str | None) -> str:
    """The pack key for a theme directory's ``Context`` (anything unknown, or none, is "other")."""
    key = (context or "").strip().lower()
    return key if key in _KNOWN_CATEGORIES else "other"


def icon_search_dirs(env: Mapping[str, str], home: Path) -> list[Path]:
    """The freedesktop icon base directories in lookup order (they may not all exist)."""
    data_home = Path(env.get("XDG_DATA_HOME") or home / ".local" / "share")
    data_dirs = [d for d in (env.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if d]
    return [data_home / "icons", home / ".icons", *(Path(d) / "icons" for d in data_dirs)]


def detect_theme(configured: str, home: Path, search_dirs: Sequence[Path]) -> str:
    """The icon theme: configured, else the GTK or KDE setting, else Adwaita, else hicolor (installed ones only)."""
    candidates = [configured.strip(), _gtk_theme(home), _kde_theme(home), *_FALLBACK_THEMES]
    for name in candidates:
        if name and any((base / name / "index.theme").is_file() for base in search_dirs):
            return name
    return "hicolor"


def build_index(theme: str, search_dirs: Sequence[Path]) -> ThemeIndex:
    """Index ``theme`` and the themes it inherits from (ending at hicolor); unreadable parts are skipped."""
    roots = _theme_roots(theme, search_dirs)
    best: dict[tuple[str, str], tuple[int, tuple[int, int], Path]] = {}
    for position, root in roots:
        parser = _read_ini(root / "index.theme")
        if parser is not None:
            _scan_theme(root, parser, position, best)
    icons: dict[str, dict[str, Path]] = {}
    for (category, icon_name), (_position, _quality, path) in best.items():
        icons.setdefault(category, {})[icon_name] = path
    return ThemeIndex(theme, _version(theme, roots), icons)


def theme_version(theme: str, search_dirs: Sequence[Path]) -> str:
    """The version string ``build_index`` would give, without scanning any icons."""
    return _version(theme, _theme_roots(theme, search_dirs))


def _version(theme: str, roots: Sequence[tuple[int, Path]]) -> str:
    return f"{theme}-{_fingerprint([root / 'index.theme' for _position, root in roots])}"


def _theme_roots(theme: str, search_dirs: Sequence[Path]) -> list[tuple[int, Path]]:
    """``(chain position, theme directory)`` for every directory in the search path that holds a theme of the chain."""
    chain = _theme_chain(theme, search_dirs)
    return [
        (position, base / name)
        for position, name in enumerate(chain)
        for base in search_dirs
        if (base / name / "index.theme").is_file()
    ]


def _fingerprint(index_files: Sequence[Path]) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    for path in index_files:
        try:
            digest.update(f"{path}:{path.stat().st_mtime_ns};".encode())
        except OSError:
            continue
    return digest.hexdigest()[:8]


def _theme_chain(theme: str, search_dirs: Sequence[Path]) -> list[str]:
    chain: list[str] = []
    queue = [theme]
    while queue:
        name = queue.pop(0)
        if name in chain:
            continue
        chain.append(name)
        for base in search_dirs:
            parser = _read_ini(base / name / "index.theme")
            if parser is not None:
                queue += [p.strip() for p in parser.get("Icon Theme", "Inherits", fallback="").split(",") if p.strip()]
                break
    if "hicolor" not in chain:
        chain.append("hicolor")
    return chain


def _scan_theme(
    root: Path,
    parser: configparser.ConfigParser,
    position: int,
    best: dict[tuple[str, str], tuple[int, tuple[int, int], Path]],
) -> None:
    for directory in (d.strip() for d in parser.get("Icon Theme", "Directories", fallback="").split(",")):
        if not directory or not parser.has_section(directory):
            continue
        section = parser[directory]
        category = category_of(section.get("Context"))
        scalable = section.get("Type", "").strip().lower() == "scalable" or "scalable" in directory.lower()
        quality = (1 if scalable else 0, _size(section))
        try:
            entries = list(os.scandir(root / directory))
        except OSError:
            continue
        for entry in entries:
            icon_name = _icon_name(entry.name)
            if icon_name is None:
                continue
            key = (category, icon_name)
            current = best.get(key)
            if current is None or (position, tuple(-q for q in quality)) < (current[0], tuple(-q for q in current[1])):
                best[key] = (position, quality, Path(entry.path))


def _size(section: configparser.SectionProxy) -> int:
    try:
        return int(section.get("Size", "0")) * max(int(section.get("Scale", "1")), 1)
    except ValueError:
        return 0


def _icon_name(filename: str) -> str | None:
    lowered = filename.lower()
    for suffix in IMAGE_SUFFIXES:
        if lowered.endswith(suffix) and len(filename) > len(suffix):
            return filename[: -len(suffix)]
    return None


def _read_ini(path: Path) -> configparser.ConfigParser | None:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str  # type: ignore[assignment,method-assign]  # keys are case-sensitive in desktop files
    try:
        with path.open(encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, UnicodeDecodeError, configparser.Error):
        return None
    return parser


def _gtk_theme(home: Path) -> str:
    parser = _read_ini(home / ".config" / "gtk-3.0" / "settings.ini")
    return _clean(parser.get("Settings", "gtk-icon-theme-name", fallback="")) if parser is not None else ""


def _kde_theme(home: Path) -> str:
    parser = _read_ini(home / ".config" / "kdeglobals")
    return _clean(parser.get("Icons", "Theme", fallback="")) if parser is not None else ""


def _clean(value: str) -> str:
    return value.strip().strip("'\"").strip()


def _configured_theme() -> str:
    return str(config.get_or_default("icons.system_theme", "") or "")


class SystemIcons:
    """The active icon theme served as virtual packs ``decker.system.<category>`` (read-only, built lazily)."""

    def __init__(
        self,
        search_dirs: Sequence[Path] | None = None,
        home: Path | None = None,
        configured_theme: Callable[[], str] | None = None,
        recheck_s: float = 2.0,
    ) -> None:
        self._home = home if home is not None else Path.home()
        self._search_dirs = list(search_dirs) if search_dirs is not None else icon_search_dirs(os.environ, self._home)
        self._configured = configured_theme or _configured_theme
        self._recheck_s = recheck_s
        self._index: ThemeIndex | None = None
        self._checked = 0.0
        self._lock = threading.Lock()
        self._build_lock = threading.Lock()

    def theme_name(self) -> str:
        """The theme in use (see ``detect_theme``)."""
        return detect_theme(self._configured(), self._home, self._search_dirs)

    def version(self) -> str:
        """``<theme>-<hash>``; changes when the theme or its index files change."""
        return self._snapshot().version

    def owns(self, pack_id: str) -> bool:
        """Whether ``pack_id`` is one of the ten system packs."""
        return _category_of_pack(pack_id) is not None

    def list_packs(self) -> list[dict[str, Any]]:
        """The non-empty category packs, shaped like plugin packs, in category order."""
        index = self._snapshot()
        return [
            {
                "id": f"{PACK_PREFIX}{key}",
                "name": label,
                "description": f"System icons: {label}",
                "plugin_id": SYSTEM_PLUGIN_ID,
                "plugin_name": SYSTEM_PLUGIN_NAME,
                "plugin_version": index.version,
                "icon_count": len(index.icons[key]),
            }
            for key, label in CATEGORIES
            if index.icons.get(key)
        ]

    def list_icons(self, pack_id: str) -> list[str]:
        """The category's icon names, sorted (empty for anything that is not a system pack)."""
        category = _category_of_pack(pack_id)
        return sorted(self._snapshot().icons.get(category, {})) if category is not None else []

    def read_icon(self, pack_id: str, name: Any) -> bytes | None:
        """The bytes of an icon, or None for an unknown name, a non-image or oversized file, or a read error."""
        category = _category_of_pack(pack_id)
        if category is None or not isinstance(name, str) or not name:
            return None
        path = self._snapshot().icons.get(category, {}).get(name)  # names are looked up, never joined into a path
        if path is None:
            return None
        try:
            resolved = path.resolve()
            if resolved.suffix.lower() not in IMAGE_SUFFIXES or not resolved.is_file():
                return None
            if resolved.stat().st_size > MAX_ICON_BYTES:
                return None
            return resolved.read_bytes()
        except OSError as exc:
            logging.debug("Could not read system icon %s: %s", path, exc)
            return None

    def _snapshot(self) -> ThemeIndex:
        now = time.monotonic()
        with self._lock:
            index, checked = self._index, self._checked
        if index is not None and now - checked < self._recheck_s:
            return index
        theme = self.theme_name()
        version = theme_version(theme, self._search_dirs)
        if index is not None and index.version == version:
            with self._lock:
                self._checked = now
            return index
        with self._build_lock:  # one build at a time; readers never wait on file I/O
            with self._lock:
                index = self._index
            if index is not None and index.version == version:
                return index
            built = build_index(theme, self._search_dirs)
            with self._lock:
                self._index, self._checked = built, now
            return built


def _category_of_pack(pack_id: str) -> str | None:
    if not isinstance(pack_id, str) or not pack_id.startswith(PACK_PREFIX):
        return None
    key = pack_id[len(PACK_PREFIX) :]
    return key if any(key == known for known, _label in CATEGORIES) else None
