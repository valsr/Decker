"""Font lookup: fontconfig when present, else an index of the OS font folders, else the bundled DejaVu Sans."""

import functools
import logging
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path

from PIL import ImageFont

BUNDLED_FONT_DIR: Path = Path(__file__).resolve().parent.parent / "assets" / "fonts"
BUNDLED_REGULAR: Path = BUNDLED_FONT_DIR / "DejaVuSans.ttf"
BUNDLED_BOLD: Path = BUNDLED_FONT_DIR / "DejaVuSans-Bold.ttf"

_BOLD_WEIGHT = 180  # fontconfig weight at or above which a face counts as really bold (FC_WEIGHT_BOLD is 200)
_FONT_SUFFIXES = {".ttf", ".otf", ".ttc"}
_index: dict[tuple[str, str], tuple[str, int]] | None = None  # pylint: disable=invalid-name
_index_lock = threading.Lock()
_bundled_index: dict[tuple[str, str], tuple[str, int]] | None = None  # pylint: disable=invalid-name


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


_PLAIN_STYLES = {"regular", "book", "roman", "normal", ""}
_STYLE_WORDS = {"bold", "italic", "oblique"}
_MAX_FACES = 32  # faces read from one .ttc collection
_Key = tuple[str, str]
_Face = tuple[str, int]


def _style_of(style_name: str) -> str | None:
    """The index style for a face's style name, or None for weights and widths the index does not model."""
    words = style_name.lower().split()
    if any(w not in _STYLE_WORDS and w not in _PLAIN_STYLES for w in words):
        return None
    bold = "bold" in words
    italic = "italic" in words or "oblique" in words
    return "bolditalic" if bold and italic else "bold" if bold else "italic" if italic else "regular"


def _face_name(path: Path, face: int) -> tuple[str, str]:
    family, style = ImageFont.truetype(str(path), 10, index=face).getname()
    return family or "", style or ""


def _faces_of(path: Path) -> list[tuple[int, str, str]]:
    faces: list[tuple[int, str, str]] = []
    for face in range(_MAX_FACES if path.suffix.lower() == ".ttc" else 1):
        try:
            family, style = _face_name(path, face)
        except (OSError, ValueError) as exc:
            if face == 0:
                logging.debug("skipping font file %s: %s", path, exc)
            break
        faces.append((face, family, style))
    return faces


def _font_files(directory: Path) -> Iterator[Path]:
    def on_error(exc: OSError) -> None:
        logging.debug("cannot scan font folder: %s", exc)

    for root, dirs, files in os.walk(directory, onerror=on_error, followlinks=False):
        dirs.sort()
        for name in sorted(files):
            if Path(name).suffix.lower() in _FONT_SUFFIXES:
                yield Path(root) / name


def build_face_index(directories: Sequence[Path]) -> dict[_Key, _Face]:
    """Map ``(lower-cased family, style)`` to ``(file, face number)``, read from each file's own metadata."""
    index: dict[_Key, _Face] = {}
    exact: set[_Key] = set()  # keys whose entry cannot be displaced (only Book/Roman/Normal regulars can be)
    for directory in directories:
        for path in _font_files(directory):
            for face, family, style in _faces_of(path):
                kind = _style_of(style)
                if not family or kind is None:
                    continue
                key = (family.lower(), kind)
                is_exact = kind != "regular" or style.lower() == "regular"
                if key not in index or (is_exact and key not in exact):
                    index[key] = (str(path), face)
                    if is_exact:
                        exact.add(key)
    return index


def build_font_index(directories: Sequence[Path]) -> dict[_Key, str]:
    """Map ``(lower-cased family, style)`` to a font file."""
    return {key: path for key, (path, _) in build_face_index(directories).items()}


def _get_index() -> dict[_Key, _Face]:
    global _index  # pylint: disable=global-statement
    with _index_lock:
        if _index is None:
            _index = build_face_index(font_directories())
        return _index


def _bundled_key(family: str, style: str) -> tuple[str, str] | None:
    """Index key for a bundled face; Pillow reports Condensed as a style word of the base family."""
    words = style.split()
    if "Condensed" in words:
        family += " Condensed"
        words.remove("Condensed")
    kind = _style_of(" ".join(words))
    return (family.lower(), kind) if family and kind else None


def _get_bundled_index() -> dict[_Key, _Face]:
    global _bundled_index  # pylint: disable=global-statement
    with _index_lock:
        if _bundled_index is None:
            index: dict[_Key, _Face] = {}
            for path in _font_files(BUNDLED_FONT_DIR):
                try:
                    family, style = ImageFont.truetype(str(path), 10).getname()
                except (OSError, ValueError) as exc:
                    logging.debug("skipping bundled font %s: %s", path, exc)
                    continue
                if key := _bundled_key(family or "", style or ""):
                    index[key] = (str(path), 0)
            _bundled_index = index
        return _bundled_index


def _style_key(bold: bool, italic: bool) -> str:
    return "bolditalic" if bold and italic else "bold" if bold else "italic" if italic else "regular"


def _from_bundled(family: str, bold: bool, italic: bool) -> tuple[str, bool, int] | None:
    wanted = _style_key(bold, italic)
    found = _get_bundled_index().get((family.lower(), wanted))
    return (found[0], bold, found[1]) if found else None


def _is_bundled_family(family: str) -> bool:
    return any(name == family.lower() for name, _ in _get_bundled_index())


def _fc_match(pattern: str) -> tuple[str, bool, int] | None:
    if not shutil.which("fc-match"):
        return None
    try:
        result = subprocess.run(
            ["fc-match", pattern, "--format=%{file}\n%{weight}\n%{index}"],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logging.debug("fc-match failed for %r: %s", pattern, exc)
        return None
    path, _, rest = result.stdout.partition("\n")
    weight, _, face = rest.partition("\n")
    if not path.strip():
        return None
    return (
        path.strip(),
        weight.strip().isdigit() and int(weight) >= _BOLD_WEIGHT,
        int(face) if face.strip().isdigit() else 0,
    )


def _from_index(family: str, bold: bool, italic: bool) -> tuple[str, bool, int] | None:
    index = _get_index()
    name = family.lower()
    wanted = _style_key(bold, italic)
    for style in dict.fromkeys((wanted, "bold" if bold else "regular", "regular")):
        if (name, style) in index:
            path, face = index[(name, style)]
            return path, "bold" in style, face
    return None


def _exact_from_index(family: str, bold: bool, italic: bool) -> tuple[str, bool, int] | None:
    wanted = _style_key(bold, italic)
    found = _get_index().get((family.lower(), wanted))
    return (found[0], bold, found[1]) if found else None


@functools.lru_cache(maxsize=64)
def _resolve(family: str, bold: bool, italic: bool) -> tuple[str, bool, int]:
    if _is_bundled_family(family):
        # fontconfig answers every query, so an unknown bundled family would get an unrelated fallback face
        exact = _exact_from_index(family, bold, italic)
        return exact or _from_bundled(family, bold, italic) or _bundled(bold)
    pattern = family + (":bold" if bold else "") + (":italic" if italic else "")
    return _fc_match(pattern) or _from_index(family, bold, italic) or _bundled(bold)


def _bundled(bold: bool) -> tuple[str, bool, int]:
    return (str(BUNDLED_BOLD), True, 0) if bold else (str(BUNDLED_REGULAR), False, 0)


def font_file(family: str, bold: bool = False, italic: bool = False) -> tuple[str | None, bool]:
    """Resolve a family (and style) to ``(file, is_really_bold)``; falls back to the bundled DejaVu Sans."""
    path, real_bold, _ = _resolve(family, bold, italic)
    return path, real_bold


def font_face(path: str, family: str, bold: bool = False, italic: bool = False) -> int:
    """The face number to open in ``path`` (non-zero only for a collection file resolved for this family)."""
    resolved, _, face = _resolve(family, bold, italic)
    return face if resolved == path else 0


def clear_font_cache() -> None:
    """Forget resolved fonts (the OS index is kept; the bundled index is rebuilt on next use)."""
    global _bundled_index  # pylint: disable=global-statement
    _resolve.cache_clear()
    with _index_lock:
        _bundled_index = None
