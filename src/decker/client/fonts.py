"""Makes the bundled DejaVu Sans known to Qt so the default font exists on every OS."""

import logging
from pathlib import Path

from PyQt6.QtGui import QFontDatabase

_FONT_FILES = [
    Path(__file__).resolve().parent.parent / "assets" / "fonts" / name
    for name in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")
]


def register_bundled_fonts() -> list[str]:
    """Register the bundled font files with Qt and return the family names that were loaded."""
    families: list[str] = []
    for path in _FONT_FILES:
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            logging.warning("could not load bundled font %s", path)
            continue
        families += [f for f in QFontDatabase.applicationFontFamilies(font_id) if f not in families]
    return families
