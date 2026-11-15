from typing import Any

from assertpy import assert_that
from PyQt6.QtWidgets import QLabel, QLineEdit, QSpinBox

from decker.client.widgets.action_config_panel import ActionConfigPanel
from decker.common.appearance_schema import APPEARANCE_SCHEMA

_COUNTER_SCHEMA: list[dict[str, Any]] = [
    {"section": "Counting"},
    {"key": "step", "type": "int", "label": "Step", "default": 1, "min": 1, "max": 9999},
    {"key": "double_step", "type": "int", "label": "Double step", "optional": True},
    {"key": "max", "type": "int", "label": "Max", "default": 0, "min": 0, "special_value": "No limit"},
]
_DEFAULTS: dict[str, Any] = {e["key"]: e.get("default") for e in APPEARANCE_SCHEMA if "key" in e}


def _show(panel: ActionConfigPanel, settings=None, appearance=None, save=None) -> None:
    panel.show_action_config(
        _COUNTER_SCHEMA, settings or {}, appearance or dict(_DEFAULTS), dict(_DEFAULTS), save or (lambda s, a: None)
    )


def _labels(panel: ActionConfigPanel) -> list[str]:
    return [lb.text() for lb in panel.findChildren(QLabel)]


class TestActionConfigPanel:  # pylint: disable=protected-access
    def test_starts_on_placeholder(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        widget = panel.widget(0)
        assert isinstance(widget, QLabel)
        assert_that(widget.text()).is_equal_to("Select a key to configure")
        assert_that(panel.currentIndex()).is_equal_to(0)

    def test_show_placeholder_returns_to_page_zero(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        _show(panel)
        assert_that(panel.currentIndex()).is_equal_to(1)
        panel.show_placeholder()
        assert_that(panel.currentIndex()).is_equal_to(0)

    def test_counter_schema_renders_step_double_step_max(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        _show(panel, {"step": 5, "double_step": 10, "max": 20})
        assert_that(_labels(panel)).contains("Background", "Step:", "Double step:", "Max:", "Counting")
        assert_that(panel._settings_form.values()).is_equal_to({"step": 5, "double_step": 10, "max": 20})
        assert isinstance(panel._settings_form._fields["step"].widget, QSpinBox)
        assert isinstance(panel._settings_form._fields["double_step"].widget, QLineEdit)

    def test_save_sends_settings_and_changed_appearance_only(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        captured: list[tuple[dict, dict]] = []
        _show(panel, {"step": 1}, save=lambda s, a: captured.append((s, a)))
        panel._settings_form._fields["step"].set(7)
        panel._appearance_form._fields["background"].set("#8a1c1c")

        panel._on_save()

        settings, appearance = captured[0]
        assert_that(settings["step"]).is_equal_to(7)
        assert_that(appearance).is_equal_to({"background": "#8a1c1c"})

    def test_save_without_callback_is_noop(self, qapp):  # pylint: disable=unused-argument
        ActionConfigPanel()._on_save()  # pylint: disable=protected-access

    def test_resent_identical_values_keep_edits(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        _show(panel, {"step": 1})
        panel._appearance_form._fields["title"].set("typing…")

        _show(panel, {"step": 1})

        assert_that(panel._appearance_form.values()["title"]).is_equal_to("typing…")

    def test_new_values_repopulate(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        _show(panel, {"step": 1})
        panel._appearance_form._fields["title"].set("typing…")

        _show(panel, {"step": 1}, {**_DEFAULTS, "title": "Saved"})

        assert_that(panel._appearance_form.values()["title"]).is_equal_to("Saved")

    def test_reopening_after_placeholder_repopulates(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        _show(panel, {"step": 1})
        panel._appearance_form._fields["title"].set("typing…")
        panel.show_placeholder()

        _show(panel, {"step": 1})

        assert_that(panel._appearance_form.values()["title"]).is_equal_to("")

    def test_echo_of_saved_state_keeps_later_edits(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        _show(panel, {"step": 1})
        panel._settings_form._fields["step"].set(7)
        panel._appearance_form._fields["background"].set("#8a1c1c")
        panel._on_save()
        panel._appearance_form._fields["title"].set("second edit")

        saved_appearance = {**_DEFAULTS, "background": "#8a1c1c"}
        _show(panel, panel._settings_form.values(), saved_appearance)

        assert_that(panel._appearance_form.values()["title"]).is_equal_to("second edit")
