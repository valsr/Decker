from assertpy import assert_that
from PyQt6.QtWidgets import QLabel

from decker.client.widgets.action_config_panel import ActionConfigPanel


class TestActionConfigPanel:
    def test_page_zero_is_placeholder(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        assert_that(panel.count()).is_greater_than_or_equal_to(1)
        assert_that(panel.currentIndex()).is_equal_to(0)

    def test_placeholder_text(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        widget = panel.widget(0)
        assert isinstance(widget, QLabel)
        assert_that(widget.text()).is_equal_to("Select a key to configure")

    def test_show_placeholder_returns_to_page_zero(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        panel.show_counter_config({}, lambda _: None)
        assert_that(panel.currentIndex()).is_equal_to(1)
        panel.show_placeholder()
        assert_that(panel.currentIndex()).is_equal_to(0)

    def test_show_counter_config_switches_to_page_one(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        panel.show_counter_config({"step": 3, "max": 10}, lambda _: None)
        assert_that(panel.currentIndex()).is_equal_to(1)

    def test_show_counter_config_populates_spinboxes(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        panel.show_counter_config({"step": 5, "max": 20}, lambda _: None)
        assert_that(panel._step_spin.value()).is_equal_to(5)  # pylint: disable=protected-access
        assert_that(panel._max_spin.value()).is_equal_to(20)  # pylint: disable=protected-access

    def test_save_callback_is_called_with_settings(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        captured: list[dict] = []
        panel.show_counter_config({"step": 2, "max": 0}, captured.append)
        panel._step_spin.setValue(7)  # pylint: disable=protected-access
        panel._max_spin.setValue(50)  # pylint: disable=protected-access
        panel._on_save()  # pylint: disable=protected-access
        assert_that(captured).is_length(1)
        assert_that(captured[0]["step"]).is_equal_to(7)
        assert_that(captured[0]["max"]).is_equal_to(50)

    def test_defaults_when_settings_empty(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        panel.show_counter_config({}, lambda _: None)
        assert_that(panel._step_spin.value()).is_equal_to(1)  # pylint: disable=protected-access
        assert_that(panel._max_spin.value()).is_equal_to(0)  # pylint: disable=protected-access
