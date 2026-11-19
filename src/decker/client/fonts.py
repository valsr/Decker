"""Makes the bundled DejaVu family known to Qt so the default font exists on every OS."""

import logging

from PyQt6.QtGui import QFontDatabase

from decker.server.fonts import BUNDLED_FONT_DIR


def register_bundled_fonts() -> list[str]:
    """Register the bundled font files with Qt and return the family names that were loaded."""
    families: list[str] = []
    for path in sorted(BUNDLED_FONT_DIR.glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            logging.warning("could not load bundled font %s", path)
            continue
        families += [f for f in QFontDatabase.applicationFontFamilies(font_id) if f not in families]
    return families
