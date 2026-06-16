from assertpy import assert_that
from PyQt6.QtWidgets import QLabel

from decker.client.widgets.action_config_panel import ActionConfigPanel


class TestActionConfigPanel:
    def test_page_zero_is_placeholder(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        assert_that(panel.count()).is_equal_to(1)
        assert_that(panel.currentIndex()).is_equal_to(0)

    def test_placeholder_text(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        widget = panel.widget(0)
        assert isinstance(widget, QLabel)
        assert_that(widget.text()).is_equal_to("Select a key to configure")
