from typing import Any

from assertpy import assert_that
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QLabel, QLineEdit, QPushButton, QSpinBox

from decker.client.widgets.action_config_panel import ActionConfigPanel
from decker.common.text_style import TEXT_STYLE_DEFAULTS

_COUNTER_SCHEMA: list[dict[str, Any]] = [
    {"section": "Counting"},
    {"key": "step", "type": "int", "label": "Step", "default": 1, "min": 1, "max": 9999},
    {"key": "double_step", "type": "int", "label": "Double step", "optional": True},
    {"key": "max", "type": "int", "label": "Max", "default": 0, "min": 0, "special_value": "No limit"},
]
_DEFAULTS: dict[str, Any] = {
    "background": "#000000",
    "title": dict(TEXT_STYLE_DEFAULTS),
    "icon": {"ref": "", "color": "#ffffff"},
}


def _show(panel: ActionConfigPanel, settings=None, appearance=None, save=None, title: str = "") -> None:
    panel.show_action_config(
        _COUNTER_SCHEMA,
        settings or {},
        appearance or dict(_DEFAULTS),
        dict(_DEFAULTS),
        save or (lambda s, a: None),
        title=title,
    )


def _labels(panel: ActionConfigPanel) -> list[str]:
    return [lb.text() for lb in panel.findChildren(QLabel)]


class TestActionConfigPanel:  # pylint: disable=protected-access
    def test_starts_on_placeholder(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        widget = panel.widget(0)
        assert isinstance(widget, QLabel)
        assert_that(widget.text()).is_equal_to("Hover a key and click ✎ (or focus it and press F2) to configure it")
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
        assert_that(_labels(panel)).contains("Title:", "Background:", "Step:", "Double step:", "Max:", "Counting")
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
        panel._appearance_form._fields["title"].set({"text": "typing…"})

        _show(panel, {"step": 1})

        assert_that(panel._appearance_form.values()["title"]["text"]).is_equal_to("typing…")

    def test_new_values_repopulate(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        _show(panel, {"step": 1})
        panel._appearance_form._fields["title"].set({"text": "typing…"})

        _show(panel, {"step": 1}, {**_DEFAULTS, "title": {**TEXT_STYLE_DEFAULTS, "text": "Saved"}})

        assert_that(panel._appearance_form.values()["title"]["text"]).is_equal_to("Saved")

    def test_reopening_after_placeholder_repopulates(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        _show(panel, {"step": 1})
        panel._appearance_form._fields["title"].set({"text": "typing…"})
        panel.show_placeholder()

        _show(panel, {"step": 1})

        assert_that(panel._appearance_form.values()["title"]["text"]).is_equal_to("")

    def test_echo_of_saved_state_keeps_later_edits(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        _show(panel, {"step": 1})
        panel._settings_form._fields["step"].set(7)
        panel._appearance_form._fields["background"].set("#8a1c1c")
        panel._on_save()
        panel._appearance_form._fields["title"].set({"text": "second edit"})

        saved_appearance = {**_DEFAULTS, "background": "#8a1c1c"}
        _show(panel, panel._settings_form.values(), saved_appearance)

        assert_that(panel._appearance_form.values()["title"]["text"]).is_equal_to("second edit")

    def test_legacy_stored_keys_populate_title_control(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()

        _show(panel, {"step": 1}, {"title": "Old", "title_size": 20, "show_title": False})

        title = panel._appearance_form.values()["title"]
        assert_that(title).contains_entry({"text": "Old"}, {"size": 20}, {"visible": False})

    def test_save_drops_legacy_keys(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        captured: list[tuple[dict, dict]] = []
        _show(panel, {"step": 1}, {"title": "Old", "title_size": 20}, save=lambda s, a: captured.append((s, a)))

        panel._on_save()

        appearance = captured[0][1]
        assert_that(appearance).contains_key("title")
        assert_that(appearance).does_not_contain_key("title_size")
        assert_that(appearance["title"]).contains_entry({"text": "Old"}, {"size": 20})

    def test_unchanged_title_is_not_saved(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        captured: list[tuple[dict, dict]] = []
        _show(panel, {"step": 1}, save=lambda s, a: captured.append((s, a)))

        panel._on_save()

        assert_that(captured[0][1]).is_empty()

    def test_title_and_background_share_one_row_above_the_settings(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        _show(panel, {"step": 1})

        row = panel._appearance_form
        title_y = row._fields["title"].widget.mapTo(panel, row._fields["title"].widget.rect().center()).y()
        bg_y = row._fields["background"].widget.mapTo(panel, row._fields["background"].widget.rect().center()).y()
        step = panel._settings_form._fields["step"].widget
        step_y = step.mapTo(panel, step.rect().center()).y()

        assert_that(abs(title_y - bg_y)).is_less_than(8)
        assert_that(step_y).is_greater_than(title_y)

    def test_background_alpha_survives_save(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        captured: list[tuple[dict, dict]] = []
        _show(panel, {"step": 1}, save=lambda s, a: captured.append((s, a)))
        panel._appearance_form._fields["background"].set("#11223380")

        panel._on_save()

        assert_that(captured[0][1]).is_equal_to({"background": "#11223380"})


class TestKeyEditorLayout:  # pylint: disable=protected-access
    def test_header_shows_the_action_name_and_no_key_id(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        _show(panel, title="Counter")

        assert_that(panel._header.text()).is_equal_to("Counter")
        assert_that(_labels(panel)).does_not_contain("ID")

    def test_save_sits_between_the_appearance_rows_and_the_action_settings(
        self, qapp
    ):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        _show(panel)
        panel.show()
        save = panel._save_btn
        assert isinstance(save, QPushButton)

        assert_that(save.geometry().top()).is_greater_than(panel._appearance_form.geometry().top() - 1)
        assert_that(panel._settings_form.mapTo(panel, panel._settings_form.rect().topLeft()).y()).is_greater_than(
            save.mapTo(panel, save.rect().topLeft()).y()
        )

    def test_preview_context_menu_clears_the_icon_override(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        icon = {"ref": "pack:a.b/x.svg", "color": "#ffffff"}
        _show(panel, appearance={**_DEFAULTS, "icon": icon})
        assert_that(panel._appearance_form.values()["icon"]).is_equal_to(icon)

        panel._preview.clear_icon_requested.emit()

        assert_that(panel._appearance_form.values()["icon"]["ref"]).is_equal_to("")
        assert_that(panel.is_dirty).is_true()

    def test_preview_set_icon_opens_the_picker(self, qapp, monkeypatch):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        _show(panel)
        opened: list[bool] = []
        monkeypatch.setattr(panel._appearance_form._fields["icon"].widget, "browse", lambda: opened.append(True))

        panel._preview.set_icon_requested.emit()

        assert_that(opened).is_equal_to([True])

    def test_clear_is_enabled_only_with_an_icon_override(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        _show(panel)
        assert_that(panel._preview._has_icon).is_false()

        _show(panel, appearance={**_DEFAULTS, "icon": {"ref": "pack:a.b/x.svg", "color": "#ffffff"}})

        assert_that(panel._preview._has_icon).is_true()


class TestDirtySave:  # pylint: disable=protected-access
    def test_clean_after_load(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        _show(panel, {"step": 1})

        assert_that(panel.is_dirty).is_false()
        assert_that(panel._save_btn.property("dirty")).is_false()

    def test_any_edit_marks_it_dirty_and_editing_back_cleans_it(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        _show(panel, {"step": 1})

        panel._settings_form._fields["step"].widget.setValue(7)  # type: ignore[attr-defined]
        assert_that(panel.is_dirty).is_true()
        assert_that(panel._save_btn.property("dirty")).is_true()

        panel._settings_form._fields["step"].widget.setValue(1)  # type: ignore[attr-defined]
        assert_that(panel.is_dirty).is_false()

    def test_appearance_edits_mark_it_dirty(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        _show(panel)

        panel._appearance_form._fields["background"].widget.set_color("#123456")  # type: ignore[attr-defined]
        panel._appearance_form._fields["background"].widget.color_changed.emit("#123456")  # type: ignore[attr-defined]

        assert_that(panel.is_dirty).is_true()

    def test_save_cleans_and_the_echo_does_not_retrigger(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        _show(panel, {"step": 1})
        panel._settings_form._fields["step"].widget.setValue(7)  # type: ignore[attr-defined]

        panel._on_save()
        assert_that(panel.is_dirty).is_false()

        _show(panel, panel._settings_form.values(), dict(_DEFAULTS))
        assert_that(panel.is_dirty).is_false()
        assert_that(panel._save_btn.property("dirty")).is_false()

    def test_loading_another_key_clears_it(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        _show(panel, {"step": 1})
        panel._settings_form._fields["step"].widget.setValue(7)  # type: ignore[attr-defined]
        assert_that(panel.is_dirty).is_true()

        panel.forget_loaded()
        _show(panel, {"step": 2})

        assert_that(panel.is_dirty).is_false()


class TestLivePreview:  # pylint: disable=protected-access
    def test_provider_is_asked_once_after_the_debounce(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        calls: list[dict] = []
        panel.set_preview_provider(lambda appearance: calls.append(appearance))
        _show(panel)
        calls.clear()

        for text in ("a", "ab", "abc"):
            panel._appearance_form._fields["title"].widget.value_changed.emit()  # type: ignore[attr-defined]
            panel._appearance_form._fields["title"].set({"text": text})
        assert_that(calls).is_empty()
        assert isinstance(panel._preview_timer, QTimer)
        assert_that(panel._preview_timer.interval()).is_equal_to(150)
        assert_that(panel._preview_timer.isActive()).is_true()
        panel._preview_timer.timeout.emit()

        assert_that(calls).is_length(1)
        assert_that(calls[0]["title"]["text"]).is_equal_to("abc")

    def test_provider_image_reaches_the_preview_and_empty_keeps_the_last(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        answers = iter(["image-one", "", None])
        shown: list[str | None] = []
        setattr(panel._preview, "set_image", shown.append)
        panel.set_preview_provider(lambda appearance: next(answers))
        _show(panel)

        panel._request_preview()
        panel._request_preview()

        assert_that(shown).is_equal_to(["image-one"])

    def test_preview_is_requested_when_a_key_loads(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        calls: list[dict] = []
        panel.set_preview_provider(lambda appearance: calls.append(appearance) or None)  # type: ignore[func-returns-value]

        _show(panel)

        assert_that(calls).is_length(1)

    def test_set_preview_image_updates_the_picture(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()
        shown: list[str | None] = []
        setattr(panel._preview, "set_image", shown.append)

        panel.set_preview_image("abc")

        assert_that(shown).is_equal_to(["abc"])

    def test_provider_failure_is_ignored(self, qapp):  # pylint: disable=unused-argument
        panel = ActionConfigPanel()

        def boom(_appearance: dict) -> str:
            raise RuntimeError("down")

        panel.set_preview_provider(boom)
        _show(panel)

        panel._request_preview()  # must not raise
