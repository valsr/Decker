"""Tests for decker.client.assets stylesheet loading."""

from assertpy import assert_that

from decker.client import config as client_config
from decker.client.assets import load_stylesheet, read_custom_stylesheet, resolve_theme
from decker.client.themes import DARK, LIGHT, render_stylesheet


class TestLoadStylesheet:
    def test_bundled_themes_render_template_with_their_colours(
        self, isolated_config
    ):  # pylint: disable=unused-argument
        assert_that(resolve_theme("dark")).is_equal_to((render_stylesheet(DARK), DARK))
        assert_that(resolve_theme("light")).is_equal_to((render_stylesheet(LIGHT), LIGHT))

    def test_custom_theme_has_no_palette_colours(self, isolated_config, tmp_path):  # pylint: disable=unused-argument
        sheet = tmp_path / "mine.qss"
        sheet.write_text("QWidget {}", encoding="utf-8")

        assert_that(resolve_theme("custom", str(sheet))).is_equal_to(("QWidget {}", None))

    def test_unreadable_custom_uses_dark_colours(self, isolated_config, tmp_path):  # pylint: disable=unused-argument
        assert_that(resolve_theme("custom", str(tmp_path / "missing.qss"))[1]).is_same_as(DARK)

    def test_uses_configured_theme_by_default(self, isolated_config):  # pylint: disable=unused-argument
        client_config.set_theme("light")

        assert_that(load_stylesheet()).is_equal_to(load_stylesheet("light"))

    def test_custom_reads_given_file(self, isolated_config, tmp_path):  # pylint: disable=unused-argument
        sheet = tmp_path / "mine.qss"
        sheet.write_text("QWidget { color: red; }", encoding="utf-8")

        assert_that(load_stylesheet("custom", str(sheet))).is_equal_to("QWidget { color: red; }")

    def test_custom_reads_configured_file(self, isolated_config, tmp_path):  # pylint: disable=unused-argument
        sheet = tmp_path / "mine.qss"
        sheet.write_text("QWidget { color: blue; }", encoding="utf-8")
        client_config.set_theme("custom", str(sheet))

        assert_that(load_stylesheet()).is_equal_to("QWidget { color: blue; }")

    def test_unreadable_custom_falls_back_to_dark(self, isolated_config, tmp_path):  # pylint: disable=unused-argument
        assert_that(load_stylesheet("custom", str(tmp_path / "missing.qss"))).is_equal_to(load_stylesheet("dark"))


class TestReadCustomStylesheet:
    def test_empty_path_is_none(self):
        assert_that(read_custom_stylesheet("")).is_none()

    def test_missing_file_is_none(self, tmp_path):
        assert_that(read_custom_stylesheet(str(tmp_path / "missing.qss"))).is_none()
