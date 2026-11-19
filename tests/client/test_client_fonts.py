from assertpy import assert_that
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QApplication

from decker.client.fonts import register_bundled_fonts
from decker.server.fonts import BUNDLED_FONT_DIR

_EXPECTED_FONTS = {
    f"DejaVu{family}{style}.ttf"
    for family, styles in {
        "Sans": ("", "-Bold", "-Oblique", "-BoldOblique", "-ExtraLight"),
        "SansCondensed": ("", "-Bold", "-Oblique", "-BoldOblique"),
        "SansMono": ("", "-Bold", "-Oblique", "-BoldOblique"),
        "Serif": ("", "-Bold", "-Italic", "-BoldItalic"),
        "SerifCondensed": ("", "-Bold", "-Italic", "-BoldItalic"),
    }.items()
    for style in styles
}


def test_bundled_folder_holds_the_full_family_and_the_licence() -> None:
    names = {p.name for p in BUNDLED_FONT_DIR.iterdir()}

    assert_that(names).is_equal_to(_EXPECTED_FONTS | {"LICENSE-DejaVu.txt"})
    assert_that(_EXPECTED_FONTS).is_length(21)


def test_bundled_fonts_register_the_dejavu_family(qapp: QApplication) -> None:
    families = register_bundled_fonts()

    assert_that(families).contains("DejaVu Sans", "DejaVu Serif", "DejaVu Sans Mono")
    assert_that(QFontDatabase.families()).contains("DejaVu Sans", "DejaVu Serif", "DejaVu Sans Mono")
