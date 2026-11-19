"""Tests for decker.client.widgets.rule_editor.RuleEditor."""

import pytest
from assertpy import assert_that

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


def test_add_and_remove_condition_rows(editor):
    editor._add_condition_button.click()

    assert_that(editor.rule().conditions).is_length(2)
    editor._rows[0].remove.click()
    assert_that(editor.rule().conditions).is_length(1)


def test_page_dropdown_lists_only_chosen_profile_pages(editor):
    names = [editor._page.itemText(i) for i in range(editor._page.count())]
    assert_that(names).is_equal_to(["Profile default", "Mail", "Docs"])

    editor._profile.setCurrentIndex(editor._profile.findData(0))
    editor._profile.activated.emit(editor._profile.currentIndex())

    names = [editor._page.itemText(i) for i in range(editor._page.count())]
    assert_that(names).is_equal_to(["Profile default", "Home"])
    assert_that(editor.rule().profile_id).is_equal_to(0)
    assert_that(editor.rule().page_id).is_equal_to("")


def test_field_and_operator_display_names(editor):
    row = editor._rows[0]

    assert_that([row.field.itemText(i) for i in range(row.field.count())]).is_equal_to(
        ["Window class", "Window type", "Title", "Executable", "Desktop file"]
    )
    assert_that([row.op.itemText(i) for i in range(row.op.count())]).is_equal_to(
        ["is", "contains", "does not contain", "matches regex"]
    )


def test_empty_contains_value_is_flagged_before_saving(editor):
    seen: list[int] = []
    editor.changed.connect(lambda: seen.append(1))
    row = editor._rows[0]

    row.value.setText("")
    row.op.setCurrentIndex(row.op.findData("contains"))
    row.op.activated.emit(row.op.currentIndex())
    row.value.editingFinished.emit()

    assert_that(editor.error()).contains("value is required")
    assert_that(editor._error.isHidden()).is_false()
    assert_that(row.value.property("invalid")).is_true()
    assert_that(seen).is_empty()


def test_valid_edit_clears_the_error(editor):
    row = editor._rows[0]
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
    assert_that(editor._rows[0].field.toolTip()).contains("not supplied")

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
