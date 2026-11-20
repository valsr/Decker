"""Tests for decker.client.widgets.rule_editor.RuleEditor."""

import pytest
from assertpy import assert_that
from PyQt6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from decker.client.widgets.rule_editor import RuleEditor
from decker.common.model import AppRule, MatchCondition, PageInfo, ProfileInfo

# pylint: disable=protected-access,redefined-outer-name,unused-argument

_PROFILES = [ProfileInfo(0, "Default", ""), ProfileInfo(2, "Work", "")]
_PAGES = {0: [PageInfo("d1", "Home")], 2: [PageInfo("w1", "Mail"), PageInfo("w2", "Docs")]}
_RULE = AppRule("r1", "Browser", True, [MatchCondition("window_class", "equals", "firefox")], 2, "w2")


@pytest.fixture()
def editor(qapp):
    widget = RuleEditor(lambda profile_id: _PAGES.get(profile_id, []))
    widget.set_profiles(_PROFILES)
    widget.set_rule(_RULE)
    return widget


def test_set_rule_round_trips(editor):
    assert_that(editor.rule()).is_equal_to(_RULE)


def test_changed_is_not_emitted_by_set_rule(qapp):
    widget = RuleEditor(lambda _id: [])
    widget.set_profiles(_PROFILES)
    seen: list[int] = []
    widget.changed.connect(lambda: seen.append(1))

    widget.set_rule(_RULE)

    assert_that(seen).is_empty()


def test_editing_the_name_emits_changed_and_updates_rule(editor):
    seen: list[int] = []
    editor.changed.connect(lambda: seen.append(1))

    editor._name.setText("Web")
    editor._name.editingFinished.emit()

    assert_that(seen).is_length(1)
    assert_that(editor.rule().name).is_equal_to("Web")


def test_each_category_has_a_row_whose_toggle_adds_or_drops_the_condition(editor):
    assert_that(list(editor._rows)).is_equal_to(["window_class", "window_type", "title", "executable", "desktop_file"])
    assert_that([r.enabled for r in editor._rows.values()]).is_equal_to([True, False, False, False, False])

    title = editor._rows["title"]
    title.value.setText("Docs")
    title.toggle.click()

    assert_that(editor.rule().conditions).is_equal_to(
        [MatchCondition("window_class", "equals", "firefox"), MatchCondition("title", "equals", "Docs")]
    )
    editor._rows["window_class"].toggle.click()
    assert_that(editor.rule().conditions).is_equal_to([MatchCondition("title", "equals", "Docs")])
    assert_that(editor._rows["window_class"].value.isEnabled()).is_false()


def test_extra_conditions_on_a_category_survive_a_round_trip(qapp):
    widget = RuleEditor(lambda _id: [])
    widget.set_profiles(_PROFILES)
    rule = AppRule(
        "r1",
        "B",
        True,
        [MatchCondition("title", "contains", "a"), MatchCondition("title", "contains", "b")],
        2,
        "",
    )

    widget.set_rule(rule)

    assert_that(widget.rule()).is_equal_to(rule)


def test_set_condition_switches_the_category_on_with_is_and_saves(editor):
    seen: list[int] = []
    editor.changed.connect(lambda: seen.append(1))
    row = editor._rows["executable"]
    row.op.setCurrentIndex(row.op.findData("regex"))

    editor.set_condition("executable", "/usr/bin/kate")

    assert_that(row.enabled).is_true()
    assert_that(row.condition()).is_equal_to(MatchCondition("executable", "equals", "/usr/bin/kate"))
    assert_that(seen).is_length(1)


def test_clear_empties_the_editor_without_complaining(editor):
    editor.clear()

    assert_that(editor._error.isHidden()).is_true()
    assert_that(editor._name.text()).is_equal_to("")
    assert_that([r.enabled for r in editor._rows.values()]).is_equal_to([False] * 5)


def test_page_dropdown_lists_only_chosen_profile_pages(editor):
    names = [editor._page.itemText(i) for i in range(editor._page.count())]
    assert_that(names).is_equal_to(["Profile default", "Mail", "Docs"])

    editor._profile.setCurrentIndex(editor._profile.findData(0))
    editor._profile.activated.emit(editor._profile.currentIndex())

    names = [editor._page.itemText(i) for i in range(editor._page.count())]
    assert_that(names).is_equal_to(["Profile default", "Home"])
    assert_that(editor.rule().profile_id).is_equal_to(0)
    assert_that(editor.rule().page_id).is_equal_to("")


def test_operator_display_names(editor):
    row = editor._rows["window_class"]

    assert_that([row.op.itemText(i) for i in range(row.op.count())]).is_equal_to(
        ["is", "contains", "does not contain", "matches regex"]
    )


def test_empty_contains_value_is_flagged_before_saving(editor):
    seen: list[int] = []
    editor.changed.connect(lambda: seen.append(1))
    row = editor._rows["window_class"]

    row.value.setText("")
    row.op.setCurrentIndex(row.op.findData("contains"))
    row.op.activated.emit(row.op.currentIndex())
    row.value.editingFinished.emit()

    assert_that(editor.error()).contains("value is required")
    assert_that(editor._error.isHidden()).is_false()
    assert_that(row.value.property("invalid")).is_true()
    assert_that(seen).is_empty()


def test_valid_edit_clears_the_error(editor):
    row = editor._rows["window_class"]
    row.value.setText("")
    row.op.setCurrentIndex(row.op.findData("contains"))
    row.op.activated.emit(row.op.currentIndex())
    assert_that(editor.error()).is_not_empty()

    row.value.setText("fox")
    row.value.editingFinished.emit()

    assert_that(editor.error()).is_equal_to("")
    assert_that(editor._error.isHidden()).is_true()


def test_unsupported_field_warning(editor):
    assert_that(editor._warning.isHidden()).is_true()

    editor.set_unsupported_fields({"window_class"})

    assert_that(editor._warning.isHidden()).is_false()
    assert_that(editor._warning.text()).contains("Window class")
    assert_that(editor._rows["window_class"].toolTip()).contains("not supplied")

    editor.set_unsupported_fields({"title"})
    assert_that(editor._warning.isHidden()).is_true()


def test_missing_page_entry_keeps_the_page_id(qapp):
    widget = RuleEditor(lambda profile_id: _PAGES.get(profile_id, []))
    widget.set_profiles(_PROFILES)
    widget.set_rule(AppRule("r1", "B", True, _RULE.conditions, 2, "gone"))

    assert_that(widget._page.currentText()).is_equal_to("(missing page)")
    assert_that(widget.rule().page_id).is_equal_to("gone")
    widget._page.setCurrentIndex(widget._page.findData(""))
    assert_that(widget.rule().page_id).is_equal_to("")


def test_blank_name_is_an_error(editor):
    seen: list[int] = []
    editor.changed.connect(lambda: seen.append(1))

    editor._name.setText("  ")
    editor._name.editingFinished.emit()

    assert_that(editor.error()).contains("name")
    assert_that(editor._name.property("invalid")).is_true()
    assert_that(seen).is_empty()


def _shown(editor: RuleEditor) -> QPushButton:
    host = QWidget()
    layout = QVBoxLayout(host)
    other = QPushButton("other")
    layout.addWidget(editor)
    layout.addWidget(other)
    host.show()
    host.activateWindow()
    QApplication.processEvents()
    setattr(editor, "_host", host)  # keep alive
    return other


def test_has_focus_means_a_field_is_focused_right_now(editor):
    other = _shown(editor)
    other.setFocus()
    QApplication.processEvents()
    assert_that(editor.has_focus()).is_false()

    editor._rows["window_class"].value.setFocus()
    QApplication.processEvents()
    assert_that(editor.has_focus()).is_true()

    other.setFocus()
    QApplication.processEvents()
    assert_that(editor.has_focus()).is_false()


def test_focus_left_is_emitted_when_focus_moves_outside(editor):
    other = _shown(editor)
    seen: list[int] = []
    editor.focus_left.connect(lambda: seen.append(1))

    editor._rows["window_class"].value.setFocus()
    editor._name.setFocus()
    QApplication.processEvents()
    assert_that(seen).is_empty()
    other.setFocus()
    QApplication.processEvents()

    assert_that(seen).is_equal_to([1])


def test_set_profiles_with_an_unchanged_list_leaves_the_combos_alone(editor):
    editor._profile.setItemText(0, "marker")

    editor.set_profiles(_PROFILES)

    assert_that(editor._profile.itemText(0)).is_equal_to("marker")
