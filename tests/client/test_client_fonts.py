from assertpy import assert_that
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QApplication

from decker.client.fonts import register_bundled_fonts


def test_bundled_fonts_register_the_dejavu_family(qapp: QApplication) -> None:
    families = register_bundled_fonts()

    assert_that(families).contains("DejaVu Sans")
    assert_that(QFontDatabase.families()).contains("DejaVu Sans")
