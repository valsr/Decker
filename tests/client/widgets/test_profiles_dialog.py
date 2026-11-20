"""Tests for decker.client.widgets.profiles_dialog.ProfilesDialog."""

import json
from dataclasses import replace
from typing import Any

import pytest
from assertpy import assert_that
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget

from decker.client.events import DetectionStatusEvent
from decker.client.widgets import profiles_dialog
from decker.client.widgets.profiles_dialog import ProfilesDialog
from decker.client.widgets.toggle_switch import ToggleSwitch
from decker.common.model import (
    AppRule,
    DefaultRule,
    DeviceProfiles,
    DeviceRules,
    MatchCondition,
    PageInfo,
    ProfileInfo,
    WindowInfo,
)

# pylint: disable=protected-access,redefined-outer-name,unused-argument

_PROFILES = DeviceProfiles("dev1", [ProfileInfo(0, "Default", ""), ProfileInfo(2, "Work", "pack:a/b.svg")], 0)
_PAGES = {0: [PageInfo("d1", "Home")], 2: [PageInfo("w1", "Mail"), PageInfo("w2", "Docs")]}
_R1 = AppRule("r1", "Browser", True, [MatchCondition("window_class", "equals", "firefox")], 2, "w1")
_R2 = AppRule("r2", "Editor", False, [MatchCondition("title", "contains", "vim")], 0, "")
_RULES = DeviceRules("dev1", [_R1, _R2], DefaultRule(False, 0, ""))
_ACTIVE = DetectionStatusEvent("active", "", "kwin", True, WindowInfo(window_class="konsole"))


class FakeRulesApi:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def app_rule_add(self, device_id: str, rule: AppRule) -> AppRule | None:
        self.calls.append(("add", device_id, rule))
        return rule

    def app_rule_update(self, device_id: str, rule: AppRule) -> bool:
        self.calls.append(("update", device_id, rule))
        return True

    def app_rule_delete(self, device_id: str, rule_id: str) -> bool:
        self.calls.append(("delete", device_id, rule_id))
        return True

    def app_rule_move(self, device_id: str, rule_id: str, position: int) -> bool:
        self.calls.append(("move", device_id, rule_id, position))
        return True

    def app_default_rule_set(self, device_id: str, default_rule: DefaultRule) -> bool:
        self.calls.append(("default", device_id, default_rule))
        return True

    def window_pick(self) -> bool:
        return True


@pytest.fixture()
def api() -> FakeRulesApi:
    return FakeRulesApi()


@pytest.fixture()
def calls() -> list[tuple[Any, ...]]:
    return []


class FakePages:
    """Pages lookup that counts calls and can simulate an RPC failure."""

    def __init__(self) -> None:
        self.calls: list[int] = []
        self.fail = False

    def __call__(self, profile_id: int) -> list[PageInfo] | None:
        self.calls.append(profile_id)
        return None if self.fail else _PAGES.get(profile_id, [])


@pytest.fixture()
def pages() -> FakePages:
    return FakePages()


def _recording_call(calls: list[tuple[Any, ...]]) -> Any:
    def call(method: str, *args: Any) -> Any:
        calls.append((method, *args))
        if method == "profile_add":
            return json.dumps({"profile_id": 5, "name": "Created", "icon": ""})
        return True

    return call


@pytest.fixture()
def dialog(qapp, api, calls, pages):
    dlg = ProfilesDialog(_recording_call(calls), api, pages)
    dlg.set_profiles(_PROFILES)
    dlg.set_rules(_RULES)
    dlg.set_status(_ACTIVE)
    dlg.select_profile(2)
    dlg.show()
    yield dlg
    dlg.close()


def _focus(widget: QWidget) -> None:
    window = widget.window()
    assert window is not None
    window.activateWindow()
    QApplication.processEvents()
    widget.setFocus()
    QApplication.processEvents()
    assert QApplication.focusWidget() is widget


def _select_rule(dialog: ProfilesDialog, row: int) -> None:
    dialog._rule_list.setCurrentRow(row)


class TestProfiles:
    def test_is_non_modal_and_lists_profiles(self, dialog):
        assert_that(dialog.isModal()).is_false()
        assert_that(dialog._profile_list.count()).is_equal_to(2)

    def test_select_profile_shows_its_fields(self, dialog):
        assert_that(dialog._name_edit.text()).is_equal_to("Work")
        assert_that(dialog._icon.value()["ref"]).is_equal_to("pack:a/b.svg")

    def test_profile_actions_call_existing_rpcs(self, dialog, calls, monkeypatch):
        dialog._name_edit.setText(" Games ")
        dialog._name_edit.editingFinished.emit()
        dialog._icon.set_value({"ref": "pack:a/c.svg"})
        dialog._icon.value_changed.emit()
        dialog._clone_button.click()
        monkeypatch.setattr(profiles_dialog, "_confirm_delete_profile", lambda *_: True)
        dialog._delete_profile_button.click()
        dialog._add_profile_button.click()

        assert_that(calls).is_equal_to(
            [
                ("profile_rename", 2, "Games"),
                ("profile_set_icon", 2, "pack:a/c.svg", ""),
                ("profile_clone", 2),
                ("profile_delete", 2),
                ("profile_add",),
            ]
        )

    def test_declined_delete_calls_nothing(self, dialog, calls, monkeypatch):
        monkeypatch.setattr(profiles_dialog, "_confirm_delete_profile", lambda *_: False)

        dialog._delete_profile_button.click()

        assert_that(calls).is_empty()

    def test_blank_or_unchanged_rename_is_ignored(self, dialog, calls):
        dialog._name_edit.setText("  ")
        dialog._name_edit.editingFinished.emit()
        dialog._name_edit.setText("Work")
        dialog._name_edit.editingFinished.emit()

        assert_that(calls).is_empty()

    def test_last_profile_cannot_be_deleted(self, dialog):
        dialog.set_profiles(DeviceProfiles("dev1", [ProfileInfo(2, "Work", "")], 2))

        assert_that(dialog._delete_profile_button.isEnabled()).is_false()

    def test_confirmation_text_warns_about_pages(self, qapp, monkeypatch):
        seen: list[Any] = []

        def question(*args: Any) -> Any:
            seen.append(args[2])
            return profiles_dialog.QMessageBox.StandardButton.Yes

        monkeypatch.setattr(profiles_dialog.QMessageBox, "question", question)

        assert_that(profiles_dialog._confirm_delete_profile(None, "Work")).is_true()
        assert_that(seen[0]).contains("Work").contains("pages")


class TestRules:
    def test_rows_show_name_and_target_summary(self, dialog):
        texts = [dialog._rule_list.item(i).text() for i in range(dialog._rule_list.count())]

        assert_that(texts[0]).contains("Browser").contains("-> Work / Mail")
        assert_that(texts[1]).contains("Editor").contains("-> Default / profile default")
        assert_that(dialog._rule_list.item(0).checkState()).is_equal_to(Qt.CheckState.Checked)
        assert_that(dialog._rule_list.item(1).checkState()).is_equal_to(Qt.CheckState.Unchecked)

    def test_add_rule_calls_app_rule_add_with_conditions(self, dialog, api):
        dialog._add_rule_button.click()

        kind, device_id, rule = api.calls[0]
        assert_that(kind).is_equal_to("add")
        assert_that(device_id).is_equal_to("dev1")
        assert_that(rule.conditions).is_not_empty()
        assert_that(rule.rule_id).is_equal_to("")
        assert_that(rule.enabled).is_true()

    def test_edit_rule_saves_immediately_via_app_rule_update(self, dialog, api):
        _select_rule(dialog, 0)

        dialog._editor._name.setText("Web")
        dialog._editor._name.editingFinished.emit()

        assert_that(api.calls).is_length(1)
        kind, device_id, rule = api.calls[0]
        assert_that((kind, device_id, rule.rule_id, rule.name)).is_equal_to(("update", "dev1", "r1", "Web"))

    def test_toggling_the_checkbox_saves_enabled(self, dialog, api):
        dialog._rule_list.item(1).setCheckState(Qt.CheckState.Checked)

        assert_that(api.calls[0][2]).is_equal_to(AppRule("r2", "Editor", True, _R2.conditions, 0, ""))

    def test_delete_rule(self, dialog, api):
        _select_rule(dialog, 1)

        dialog._delete_rule_button.click()

        assert_that(api.calls).is_equal_to([("delete", "dev1", "r2")])

    def test_move_buttons_call_app_rule_move(self, dialog, api):
        _select_rule(dialog, 1)
        dialog._up_button.click()
        _select_rule(dialog, 0)
        dialog._down_button.click()

        assert_that(api.calls).is_equal_to([("move", "dev1", "r2", 0), ("move", "dev1", "r1", 1)])

    def test_move_buttons_disabled_at_the_ends(self, dialog):
        _select_rule(dialog, 0)
        assert_that(dialog._up_button.isEnabled()).is_false()
        _select_rule(dialog, 1)
        assert_that(dialog._down_button.isEnabled()).is_false()

    def test_default_rule_row_only_toggles_and_retargets(self, dialog, api):
        dialog._default_enable.setChecked(True)
        dialog._default_profile.setCurrentIndex(dialog._default_profile.findData(2))
        dialog._default_profile.activated.emit(dialog._default_profile.currentIndex())
        dialog._default_page.setCurrentIndex(dialog._default_page.findData("w2"))
        dialog._default_page.activated.emit(dialog._default_page.currentIndex())

        assert_that([c[2] for c in api.calls]).is_equal_to(
            [DefaultRule(True, 0, ""), DefaultRule(True, 2, ""), DefaultRule(True, 2, "w2")]
        )
        assert_that(dialog._rule_list.count()).is_equal_to(2)  # the default row is not in the movable list
        assert_that(hasattr(dialog, "_default_delete")).is_false()

    def test_selecting_a_rule_never_selects_the_default_row(self, dialog):
        dialog._default_enable.setChecked(False)
        _select_rule(dialog, -1)

        assert_that(dialog._editor.isEnabled()).is_false()

    def test_empty_contains_value_is_flagged_before_saving(self, dialog, api):
        _select_rule(dialog, 1)
        row = dialog._editor._rows["title"]

        row.value.setText("")
        row.value.editingFinished.emit()

        assert_that(api.calls).is_empty()
        assert_that(dialog._editor.error()).is_not_empty()

    def test_refresh_on_set_rules_keeps_selection(self, dialog):
        _select_rule(dialog, 1)

        dialog.set_rules(DeviceRules("dev1", [_R2, _R1], DefaultRule(True, 2, "w1")))

        assert_that(dialog._rule_list.currentRow()).is_equal_to(0)
        assert_that(dialog._editor.rule().rule_id).is_equal_to("r2")
        assert_that(dialog._default_enable.isChecked()).is_true()

    def test_refresh_keeps_selected_profile(self, dialog):
        dialog.set_profiles(DeviceProfiles("dev1", [ProfileInfo(0, "Default", ""), ProfileInfo(2, "Wk", "")], 0))

        assert_that(dialog._name_edit.text()).is_equal_to("Wk")

    def test_deleted_selected_rule_clears_the_editor(self, dialog):
        _select_rule(dialog, 0)

        dialog.set_rules(DeviceRules("dev1", [_R2], DefaultRule()))

        assert_that(dialog._rule_list.currentRow()).is_equal_to(-1)
        assert_that(dialog._editor.isEnabled()).is_false()


class TestStatus:
    def test_unsupported_field_warning(self, dialog):
        dialog.set_status(DetectionStatusEvent("active", "", "windows", False, None))

        assert_that(dialog._rule_list.item(1).toolTip()).is_equal_to("")
        _select_rule(dialog, 0)
        dialog.set_rules(
            DeviceRules(
                "dev1",
                [AppRule("r3", "T", True, [MatchCondition("window_type", "equals", "dialog")], 0)],
                DefaultRule(),
            )
        )
        assert_that(dialog._rule_list.item(0).toolTip()).contains("Window type")
        assert_that(dialog._rule_list.item(0).text()).starts_with("⚠")

    def test_new_button_row_and_profile_icons(self, dialog):
        row = [dialog._add_profile_button, dialog._clone_button, dialog._delete_profile_button]

        assert_that([b.text() for b in row]).is_equal_to(["+ New", "Clone", "Delete"])
        assert_that(len({b.parentWidget() for b in row})).is_equal_to(1)
        assert_that(dialog._profile_list.item(0).icon().isNull()).is_false()  # the Decker icon stands in

    def test_no_selected_rule_disables_and_clears_the_editor_without_an_error(self, dialog):
        _select_rule(dialog, 1)
        _select_rule(dialog, -1)

        assert_that(dialog._editor.isEnabled()).is_false()
        assert_that(dialog._editor._error.isHidden()).is_true()
        assert_that(dialog._editor._name.text()).is_equal_to("")

    def test_default_row_is_a_toggle_switch(self, dialog):
        assert_that(isinstance(dialog._default_enable, ToggleSwitch)).is_true()
        assert_that(dialog._default_enable.isCheckable()).is_true()

    def test_bottom_rows_line_up_icon_with_switch_to_and_buttons_with_spy_and_close(self, dialog):
        grid = dialog.layout()

        assert_that(grid.itemAtPosition(3, 0).layout().indexOf(dialog._icon)).is_greater_than_or_equal_to(0)
        assert_that(grid.getItemPosition(grid.indexOf(dialog._editor.switch_row))[:2]).is_equal_to((3, 1))
        assert_that(grid.itemAtPosition(4, 0).layout().indexOf(dialog._clone_button)).is_greater_than_or_equal_to(0)
        right = grid.itemAtPosition(4, 1).layout()
        assert_that(right.indexOf(dialog._spy_button)).is_greater_than_or_equal_to(0)
        assert_that(right.indexOf(dialog._close_button)).is_greater_than_or_equal_to(0)

    def test_there_is_no_window_detection_line(self, dialog):
        assert_that(hasattr(dialog, "_status_label")).is_false()

    def test_spy_button_emits_spy_requested(self, dialog):
        seen: list[int] = []
        dialog.spy_requested.connect(lambda: seen.append(1))

        dialog._spy_button.click()

        assert_that(seen).is_equal_to([1])


class TestRefreshDoesNotClobberEditing:
    def test_refresh_while_typing_keeps_text_and_focus(self, dialog):
        _select_rule(dialog, 0)
        row = dialog._editor._rows["window_class"]
        _focus(row.value)
        row.value.setText("typed")

        dialog.set_rules(DeviceRules("dev1", [_R1, _R2], DefaultRule(True, 0, "")))

        assert_that(dialog._editor._rows["window_class"]).is_same_as(row)
        assert_that(row.value.text()).is_equal_to("typed")
        assert_that(dialog._editor.focusWidget()).is_same_as(row.value)

    def test_refresh_with_a_different_server_rule_updates_an_unfocused_editor(self, dialog):
        _select_rule(dialog, 0)

        dialog.set_rules(DeviceRules("dev1", [replace(_R1, name="Renamed"), _R2], DefaultRule()))

        assert_that(dialog._editor._name.text()).is_equal_to("Renamed")

    def test_echo_of_the_users_own_edit_does_not_rebuild_the_editor(self, dialog):
        _select_rule(dialog, 0)
        row = dialog._editor._rows["window_class"]
        dialog._editor._name.setText("Web")
        dialog._editor._name.editingFinished.emit()

        dialog.set_rules(DeviceRules("dev1", [replace(_R1, name="Web"), _R2], DefaultRule()))

        assert_that(dialog._editor._rows["window_class"]).is_same_as(row)


class TestPages:
    def test_deleted_page_is_kept_when_saving_another_field(self, dialog, api):
        gone = replace(_R1, page_id="gone")
        dialog.set_rules(DeviceRules("dev1", [gone, _R2], DefaultRule()))
        _select_rule(dialog, 0)

        assert_that(dialog._editor._page.currentText()).is_equal_to("(missing page)")
        dialog._editor._name.setText("Web")
        dialog._editor._name.editingFinished.emit()

        assert_that(api.calls[-1][2].page_id).is_equal_to("gone")

    def test_failed_lookup_keeps_the_previous_pages_and_page_id(self, dialog, api, pages):
        _select_rule(dialog, 0)
        pages.fail = True

        dialog.set_rules(DeviceRules("dev1", [replace(_R1, name="Other"), _R2], DefaultRule()))
        dialog._editor._name.setText("Web")
        dialog._editor._name.editingFinished.emit()

        names = [dialog._editor._page.itemText(i) for i in range(dialog._editor._page.count())]
        assert_that(names).is_equal_to(["Profile default", "Mail", "Docs"])
        assert_that(api.calls[-1][2].page_id).is_equal_to("w1")

    def test_failed_lookup_without_history_still_keeps_page_id(self, qapp, api, calls):
        dlg = ProfilesDialog(_recording_call(calls), api, lambda _id: None)
        dlg.set_profiles(_PROFILES)
        dlg.set_rules(_RULES)
        dlg.show()
        dlg._rule_list.setCurrentRow(0)

        dlg._editor._name.setText("Web")
        dlg._editor._name.editingFinished.emit()

        assert_that(api.calls[-1][2].page_id).is_equal_to("w1")
        dlg.close()

    def test_default_row_keeps_a_missing_page(self, dialog):
        dialog.set_rules(DeviceRules("dev1", [_R1], DefaultRule(True, 2, "gone")))

        assert_that(dialog._default_page.currentData()).is_equal_to("gone")

    def test_no_pages_rpc_while_hidden_and_one_render_on_show(self, qapp, api, calls, pages):
        dlg = ProfilesDialog(_recording_call(calls), api, pages)
        dlg.set_profiles(_PROFILES)
        dlg.set_rules(_RULES)
        dlg.set_status(_ACTIVE)
        assert_that(pages.calls).is_empty()

        dlg.show()

        assert_that(pages.calls).is_not_empty()
        assert_that(dlg._rule_list.count()).is_equal_to(2)
        dlg.close()

    def test_set_status_does_not_look_up_pages(self, dialog, pages):
        pages.calls.clear()

        dialog.set_status(DetectionStatusEvent("active", "", "windows", False, None))

        assert_that(pages.calls).is_empty()

    def test_status_warning_updates_rows_in_place(self, dialog):
        dialog.set_rules(
            DeviceRules(
                "dev1", [AppRule("r3", "T", True, [MatchCondition("window_type", "equals", "d")], 0)], DefaultRule()
            )
        )

        dialog.set_status(DetectionStatusEvent("active", "", "windows", False, None))

        assert_that(dialog._rule_list.item(0).text()).starts_with("⚠").contains("-> Default")


class TestMinorFixes:
    def test_edit_after_toggle_saves_the_toggled_enabled(self, dialog, api):
        _select_rule(dialog, 1)
        dialog._rule_list.item(1).setCheckState(Qt.CheckState.Checked)

        dialog._editor._name.setText("Edited")
        dialog._editor._name.editingFinished.emit()

        assert_that(api.calls[-1][2].enabled).is_true()

    def test_blank_rule_name_is_flagged_and_not_saved(self, dialog, api):
        _select_rule(dialog, 0)

        dialog._editor._name.setText("   ")
        dialog._editor._name.editingFinished.emit()

        assert_that(api.calls).is_empty()
        assert_that(dialog._editor.error()).is_not_empty()

    def test_add_profile_selects_the_created_profile_without_activating(self, dialog, calls):
        dialog._add_profile_button.click()
        dialog.set_profiles(
            DeviceProfiles("dev1", [*_PROFILES.profiles, ProfileInfo(5, "Created", "")], _PROFILES.active_profile_id)
        )

        assert_that(dialog._name_edit.text()).is_equal_to("Created")
        assert_that([c[0] for c in calls]).does_not_contain("profile_activate")


class TestFocusAndResync:
    def _other_client_change(self, dialog, **changes):
        dialog.set_rules(DeviceRules("dev1", [replace(_R1, **changes), _R2], DefaultRule()))

    def test_after_focus_leaves_a_different_server_rule_updates_the_editor(self, dialog):
        _select_rule(dialog, 0)
        _focus(dialog._editor._rows["window_class"].value)
        _focus(dialog._add_rule_button)

        self._other_client_change(dialog, name="Theirs")

        assert_that(dialog._editor._name.text()).is_equal_to("Theirs")

    def test_a_focused_field_with_unsaved_text_is_not_rebuilt(self, dialog):
        _select_rule(dialog, 0)
        row = dialog._editor._rows["window_class"]
        _focus(row.value)
        row.value.setText("typed")

        self._other_client_change(dialog, name="Theirs")

        assert_that(dialog._editor._rows["window_class"]).is_same_as(row)
        assert_that(row.value.text()).is_equal_to("typed")
        assert_that(QApplication.focusWidget()).is_same_as(row.value)
        assert_that(dialog._editor._name.text()).is_equal_to("Browser")

    def test_blur_syncs_an_untouched_editor_to_the_latest_server_rule(self, dialog):
        _select_rule(dialog, 0)
        _focus(dialog._editor._rows["window_class"].value)
        self._other_client_change(dialog, name="Theirs")
        assert_that(dialog._editor._name.text()).is_equal_to("Browser")

        _focus(dialog._add_rule_button)

        assert_that(dialog._editor._name.text()).is_equal_to("Theirs")

    def test_blur_keeps_the_users_unsaved_text(self, dialog):
        _select_rule(dialog, 0)
        row = dialog._editor._rows["window_class"]
        _focus(row.value)
        row.value.setText("typed")
        self._other_client_change(dialog, name="Theirs")

        _focus(dialog._add_rule_button)

        assert_that(row.value.text()).is_equal_to("typed")
        assert_that(dialog._editor._name.text()).is_equal_to("Browser")

    def test_a_stale_editor_cannot_overwrite_another_clients_change(self, dialog, api):
        _select_rule(dialog, 0)
        _focus(dialog._editor._rows["window_class"].value)
        self._other_client_change(dialog, conditions=[MatchCondition("window_class", "equals", "chrome")])
        _focus(dialog._add_rule_button)

        dialog._editor._name.setText("Mine")
        dialog._editor._name.editingFinished.emit()

        saved = api.calls[-1][2]
        assert_that(saved.name).is_equal_to("Mine")
        assert_that(saved.conditions[0].value).is_equal_to("chrome")

    def test_rendering_does_not_reset_the_editors_profile_combo(self, dialog):
        _select_rule(dialog, 0)
        dialog._editor._profile.setItemText(0, "marker")

        self._other_client_change(dialog, name="Theirs")

        assert_that(dialog._editor._profile.itemText(0)).is_equal_to("marker")
