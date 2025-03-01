from assertpy import assert_that

from decker_server.theme import set_theme, get_theme, Theme, primary, get_style, Style

class TestTheme:
    def test_set_and_get_theme(self):
        set_theme(Theme.LIGHT)
        current = get_theme()
        assert_that(current).is_equal_to(Theme.LIGHT)
        set_theme(Theme.DARK)  # Restore for further tests

    def test_primary_format(self):
        # Simply check that the output is a non-empty string.
        colored_text = primary("sample")
        assert_that(colored_text).is_not_empty()

    def test_get_style_dark_theme(self):
        set_theme(Theme.DARK)
        style_color = get_style(Style.INFO)
        # For dark theme, Style.INFO should be 'light_grey'
        assert_that(style_color).is_equal_to("light_grey")
