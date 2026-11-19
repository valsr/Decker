"""Locate the DejaVu fonts Decker bundles (stdlib only; needs Decker to set `DECKER_FONT_DIR`)."""

import os
from pathlib import Path

_FAMILIES: dict[str, tuple[str, str]] = {
    # family (lower case): (file prefix, italic word)
    "dejavu sans": ("DejaVuSans", "Oblique"),
    "dejavu sans condensed": ("DejaVuSansCondensed", "Oblique"),
    "dejavu sans mono": ("DejaVuSansMono", "Oblique"),
    "dejavu serif": ("DejaVuSerif", "Italic"),
    "dejavu serif condensed": ("DejaVuSerifCondensed", "Italic"),
}


def font_path(family: str = "DejaVu Sans", bold: bool = False, italic: bool = False) -> str | None:
    """Absolute path of a bundled DejaVu face, or None when it is unavailable (never raises)."""
    try:
        directory = os.environ.get("DECKER_FONT_DIR")
        entry = _FAMILIES.get(family.strip().lower())
        if not directory or entry is None or not os.path.isabs(directory):
            return None
        prefix, slant = entry
        style = ("Bold" if bold else "") + (slant if italic else "")
        candidate = Path(directory) / f"{prefix}{'-' + style if style else ''}.ttf"
        return str(candidate) if candidate.is_file() else None
    except (OSError, ValueError, AttributeError):
        return None
