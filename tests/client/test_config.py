"""Tests for decker.client.config theme accessors."""

import pytest
from assertpy import assert_that

from decker.client import config as client_config


class TestTheme:
    def test_defaults_to_dark(self, isolated_config):  # pylint: disable=unused-argument
        assert_that(client_config.get_theme()).is_equal_to("dark")
        assert_that(client_config.get_custom_style_sheet()).is_equal_to("")

    def test_legacy_style_sheet_without_theme_means_custom(self, isolated_config):
        isolated_config.set("client.style_sheet", "/tmp/mine.qss")

        assert_that(client_config.get_theme()).is_equal_to("custom")

    def test_unknown_theme_falls_back_to_dark(self, isolated_config):
        isolated_config.set("client.theme", "neon")

        assert_that(client_config.get_theme()).is_equal_to("dark")

    def test_set_theme_persists_light_without_touching_style_sheet(self, isolated_config):
        isolated_config.set("client.style_sheet", "/tmp/mine.qss")

        client_config.set_theme("light", "/ignored.qss")

        assert_that(client_config.get_theme()).is_equal_to("light")
        assert_that(client_config.get_custom_style_sheet()).is_equal_to("/tmp/mine.qss")

    def test_set_theme_custom_persists_path(self, isolated_config):  # pylint: disable=unused-argument
        client_config.set_theme("custom", "/tmp/mine.qss")

        assert_that(client_config.get_theme()).is_equal_to("custom")
        assert_that(client_config.get_custom_style_sheet()).is_equal_to("/tmp/mine.qss")

    def test_set_theme_rejects_unknown_name(self, isolated_config):  # pylint: disable=unused-argument
        with pytest.raises(ValueError):
            client_config.set_theme("neon")
