"""The system's freedesktop icon theme, indexed so it can be served as virtual icon packs."""

import configparser
import hashlib
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

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
    """The icon theme to use: configured, else the GTK or KDE setting, else Adwaita, else hicolor (installed ones only)."""
    candidates = [configured.strip(), _gtk_theme(home), _kde_theme(home), *_FALLBACK_THEMES]
    for name in candidates:
        if name and any((base / name / "index.theme").is_file() for base in search_dirs):
            return name
    return "hicolor"


def build_index(theme: str, search_dirs: Sequence[Path]) -> ThemeIndex:
    """Index ``theme`` and the themes it inherits from (ending at hicolor); unreadable parts are skipped."""
    chain = _theme_chain(theme, search_dirs)
    best: dict[tuple[str, str], tuple[int, tuple[int, int], Path]] = {}
    index_files: list[Path] = []
    for position, name in enumerate(chain):
        for base in search_dirs:
            root = base / name
            parser = _read_ini(root / "index.theme")
            if parser is None:
                continue
            index_files.append(root / "index.theme")
            _scan_theme(root, parser, position, best)
    icons: dict[str, dict[str, Path]] = {}
    for (category, icon_name), (_position, _quality, path) in best.items():
        icons.setdefault(category, {})[icon_name] = path
    return ThemeIndex(theme, f"{theme}-{_fingerprint(index_files)}", icons)


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
