"""Font lookup: fontconfig when present, else an index of the OS font folders, else the bundled DejaVu Sans."""

import functools
import logging
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

from PIL import ImageFont

_ASSET_FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
BUNDLED_REGULAR: Path = _ASSET_FONTS / "DejaVuSans.ttf"
BUNDLED_BOLD: Path = _ASSET_FONTS / "DejaVuSans-Bold.ttf"

_BOLD_WEIGHT = 180  # fontconfig weight at or above which a face counts as really bold (FC_WEIGHT_BOLD is 200)
_FONT_SUFFIXES = {".ttf", ".otf", ".ttc"}
_index: dict[tuple[str, str], str] | None = None
_index_lock = threading.Lock()


def font_directories() -> list[Path]:
    """The folders that hold installed fonts on this OS."""
    home = Path.home()
    if sys.platform == "win32":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        local = os.environ.get("LOCALAPPDATA")
        user = Path(local) if local else home / "AppData" / "Local"
        return [Path(windir) / "Fonts", user / "Microsoft" / "Windows" / "Fonts"]
    if sys.platform == "darwin":
        return [Path("/System/Library/Fonts"), Path("/Library/Fonts"), home / "Library" / "Fonts"]
    data_home = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    data_dirs = (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(os.pathsep)
    result = [data_home / "fonts", home / ".fonts"]
    result += [Path(d) / "fonts" for d in data_dirs if d]
    result += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts")]
    return list(dict.fromkeys(result))


def _style_of(style_name: str) -> str:
    words = style_name.lower().split()
    bold = "bold" in words
    italic = "italic" in words or "oblique" in words
    return "bolditalic" if bold and italic else "bold" if bold else "italic" if italic else "regular"


def _font_files(directory: Path) -> list[Path]:
    try:
        return sorted(p for p in directory.rglob("*") if p.suffix.lower() in _FONT_SUFFIXES and p.is_file())
    except OSError as exc:
        logging.debug("cannot scan font folder %s: %s", directory, exc)
        return []


def build_font_index(directories: Sequence[Path]) -> dict[tuple[str, str], str]:
    """Map ``(lower-cased family, style)`` to a font file, read from each file's own metadata."""
    index: dict[tuple[str, str], str] = {}
    for directory in directories:
        for path in _font_files(directory):
            try:
                family, style = ImageFont.truetype(str(path), 10).getname()
            except (OSError, ValueError) as exc:
                logging.debug("skipping font file %s: %s", path, exc)
                continue
            if family:
                index.setdefault((family.lower(), _style_of(style or "")), str(path))
    return index


def _get_index() -> dict[tuple[str, str], str]:
    global _index  # pylint: disable=global-statement
    with _index_lock:
        if _index is None:
            _index = build_font_index(font_directories())
        return _index


def _fc_match(pattern: str) -> tuple[str | None, bool] | None:
    if not shutil.which("fc-match"):
        return None
    try:
        result = subprocess.run(
            ["fc-match", pattern, "--format=%{file}\n%{weight}"], capture_output=True, text=True, timeout=2, check=True
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logging.debug("fc-match failed for %r: %s", pattern, exc)
        return None
    path, _, weight = result.stdout.partition("\n")
    if not path.strip():
        return None
    return path.strip(), weight.strip().isdigit() and int(weight) >= _BOLD_WEIGHT


def _from_index(family: str, bold: bool, italic: bool) -> tuple[str, bool] | None:
    index = _get_index()
    name = family.lower()
    wanted = "bolditalic" if bold and italic else "bold" if bold else "italic" if italic else "regular"
    for style in dict.fromkeys((wanted, "bold" if bold else "regular", "regular")):
        if (name, style) in index:
            return index[(name, style)], "bold" in style
    return None


@functools.lru_cache(maxsize=64)
def font_file(family: str, bold: bool = False, italic: bool = False) -> tuple[str | None, bool]:
    """Resolve a family (and style) to ``(file, is_really_bold)``; falls back to the bundled DejaVu Sans."""
    pattern = family + (":bold" if bold else "") + (":italic" if italic else "")
    matched = _fc_match(pattern)
    if matched:
        return matched
    found = _from_index(family, bold, italic)
    if found:
        return found
    return (str(BUNDLED_BOLD), True) if bold else (str(BUNDLED_REGULAR), False)
