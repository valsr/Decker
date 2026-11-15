from assertpy import assert_that
from PyQt6.QtGui import QValidator
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


class TestCounterForm:  # pylint: disable=protected-access
    def test_defaults_for_new_fields(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        panel.show_counter_config({}, lambda _: None)

        settings = panel.counter_settings()

        assert_that(settings["double_step"]).is_none()
        assert_that(settings["background"]).is_equal_to("#1f618d")
        assert_that(settings["title"]).is_equal_to("")
        assert_that(settings["title_position"]).is_equal_to("bottom")
        assert_that(settings["title_color"]).is_equal_to("#ffffff")
        assert_that(settings["title_outline"]).is_equal_to("")
        assert_that(panel._outline_color_btn.isEnabled()).is_false()

    def test_loads_and_saves_every_field(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        stored = {
            "step": 2,
            "double_step": 10,
            "max": 50,
            "background": "#8a1c1c",
            "title": "Reps",
            "title_position": "top",
            "title_font": "DejaVu Sans",
            "title_size": 16,
            "title_color": "#ffd60a",
            "title_outline": "#000000",
            "title_outline_width": 2,
        }
        captured: list[dict] = []
        panel.show_counter_config(stored, captured.append)

        panel._on_save()

        assert_that(captured[0]).is_equal_to({**stored, "title_font": panel._font_combo.currentFont().family()})
        assert_that(panel._outline_color_btn.isEnabled()).is_true()

    def test_empty_double_step_saves_none(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        panel.show_counter_config({"double_step": 4}, lambda _: None)

        panel._double_step_edit.setText("")

        assert_that(panel.counter_settings()["double_step"]).is_none()

    def test_double_step_only_accepts_integers(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        edit = panel._double_step_edit
        validator = edit.validator()
        assert validator is not None

        assert_that(validator.validate("abc", 0)[0]).is_equal_to(QValidator.State.Invalid)
        assert_that(validator.validate("12", 0)[0]).is_equal_to(QValidator.State.Acceptable)

    def test_unticking_outline_saves_no_outline(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        panel.show_counter_config({"title_outline": "#123456"}, lambda _: None)

        panel._outline_check.setChecked(False)

        assert_that(panel.counter_settings()["title_outline"]).is_equal_to("")

    def test_refresh_with_same_settings_keeps_unsaved_edits(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        panel.show_counter_config({"step": 1}, lambda _: None)
        panel._title_edit.setText("typing…")

        panel.show_counter_config({"step": 1}, lambda _: None)

        assert_that(panel._title_edit.text()).is_equal_to("typing…")

    def test_refresh_with_new_settings_repopulates(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        panel.show_counter_config({"step": 1}, lambda _: None)
        panel._title_edit.setText("typing…")

        panel.show_counter_config({"step": 1, "title": "Saved"}, lambda _: None)

        assert_that(panel._title_edit.text()).is_equal_to("Saved")

    def test_reopening_after_placeholder_repopulates(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        panel.show_counter_config({"step": 1}, lambda _: None)
        panel._title_edit.setText("typing…")
        panel.show_placeholder()

        panel.show_counter_config({"step": 1}, lambda _: None)

        assert_that(panel._title_edit.text()).is_equal_to("")

    def test_bad_stored_values_fall_back(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()

        panel.show_counter_config({"step": "x", "title_position": "sideways", "double_step": "y"}, lambda _: None)

        assert_that(panel._step_spin.value()).is_equal_to(1)
        assert_that(panel._position_combo.currentData()).is_equal_to("top")
        assert_that(panel.counter_settings()["double_step"]).is_equal_to(0)
