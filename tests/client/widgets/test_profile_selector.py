"""Tests for decker.client.widgets.profile_selector.ProfileSelector."""

import pytest
from assertpy import assert_that
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QIcon, QKeyEvent
from PyQt6.QtWidgets import QLineEdit

from decker.client.widgets.profile_selector import ProfileSelector
from decker.common.model import ProfileInfo

# pylint: disable=protected-access,redefined-outer-name

_PROFILES = [ProfileInfo(0, "Default", ""), ProfileInfo(2, "Work", "pack:a/b.svg"), ProfileInfo(1, "Play", "")]


@pytest.fixture()
def selector(qapp):
    widget = ProfileSelector()
    widget.set_profiles(_PROFILES, 2)
    return widget


def _rows(selector):
    return [selector.popup_list.item(i).text() for i in range(selector.popup_list.count())]


def _ids(selector):
    return [selector.popup_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(selector.popup_list.count())]


def _editor(selector):
    return selector.popup_list.findChild(QLineEdit)


class TestDisplay:
    def test_button_shows_the_active_profile(self, selector):
        assert_that(selector.text()).is_equal_to("Work")
        assert_that(selector.toolTip()).is_equal_to("Work")

    def test_lists_profiles_in_dropdown_order_with_the_active_one_current(self, selector):
        assert_that(_rows(selector)).is_equal_to(["Default", "Work", "Play"])
        assert_that(_ids(selector)).is_equal_to([0, 2, 1])
        assert_that(selector.popup_list.currentRow()).is_equal_to(1)

    def test_set_profiles_replaces_stale_rows(self, selector):
        selector.set_profiles([ProfileInfo(0, "Only", "")], 0)

        assert_that(_rows(selector)).is_equal_to(["Only"])
        assert_that(selector.text()).is_equal_to("Only")

    def test_icons_come_from_the_provider_with_a_decker_fallback(self, qapp):
        widget = ProfileSelector()
        asked: list = []

        def provider(ref):
            asked.append(ref)
            return QIcon() if ref.startswith("pack:") else None

        widget.set_profiles(_PROFILES, 0, provider)

        assert_that(asked).contains("pack:a/b.svg")
        assert_that(widget.icon().isNull()).is_false()  # the Decker icon
        items = [widget.popup_list.item(i) for i in (0, 2)]
        assert_that(all(item is not None and not item.icon().isNull() for item in items)).is_true()


class TestSelecting:
    def test_clicking_another_profile_selects_it_after_the_double_click_window(self, selector):
        seen: list = []
        selector.profile_selected.connect(seen.append)
        selector._on_item_clicked(selector.popup_list.item(2))

        assert_that(seen).is_empty()  # waits to see whether it is a double click
        selector._select_timer.timeout.emit()

        assert_that(seen).is_equal_to([1])

    def test_clicking_the_active_profile_does_not_emit(self, selector):
        seen: list = []
        selector.profile_selected.connect(seen.append)
        selector._on_item_clicked(selector.popup_list.item(1))
        selector._select_timer.timeout.emit()

        assert_that(seen).is_empty()

    def test_double_click_renames_instead_of_selecting(self, selector):
        seen: list = []
        selector.profile_selected.connect(seen.append)
        selector.show_popup()
        item = selector.popup_list.item(2)
        selector._on_item_clicked(item)
        selector._on_item_double_clicked(item)
        selector._select_timer.timeout.emit()

        assert_that(seen).is_empty()
        assert_that(_editor(selector)).is_not_none()

    def test_add_and_edit_entries_emit(self, selector):
        added: list = []
        edited: list = []
        selector.add_requested.connect(lambda: added.append(True))
        selector.edit_requested.connect(edited.append)

        selector._add_button.click()
        selector._edit_button.click()

        assert_that(added).is_equal_to([True])
        assert_that(edited).is_equal_to([2])


class TestRename:
    def _rename(self, selector, text, key="enter"):
        selector.show_popup()
        selector.start_rename(1)
        editor = _editor(selector)
        assert_that(editor).is_not_none()
        editor.setText(text)
        if key == "enter":
            editor.editingFinished.emit()
        elif key == "escape":
            editor.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))

    def test_enter_accepts(self, selector):
        seen: list = []
        selector.rename_requested.connect(lambda i, n: seen.append((i, n)))

        self._rename(selector, "Games")

        assert_that(seen).is_equal_to([(1, "Games")])

    def test_escape_cancels(self, selector):
        seen: list = []
        selector.rename_requested.connect(lambda i, n: seen.append((i, n)))

        self._rename(selector, "Games", "escape")

        assert_that(seen).is_empty()
        assert_that(_rows(selector)).is_equal_to(["Default", "Work", "Play"])

    def test_clicking_away_accepts(self, selector):
        seen: list = []
        selector.rename_requested.connect(lambda i, n: seen.append((i, n)))

        self._rename(selector, "Games", None)
        selector.hide_popup()

        assert_that(seen).is_equal_to([(1, "Games")])

    @pytest.mark.parametrize("text", ["", "   ", "Play"])
    def test_blank_or_unchanged_names_emit_nothing_and_restore_the_row(self, selector, text):
        seen: list = []
        selector.rename_requested.connect(lambda i, n: seen.append((i, n)))

        self._rename(selector, text)

        assert_that(seen).is_empty()
        assert_that(_rows(selector)).is_equal_to(["Default", "Work", "Play"])

    def test_names_are_trimmed(self, selector):
        seen: list = []
        selector.rename_requested.connect(lambda i, n: seen.append((i, n)))

        self._rename(selector, "  Games  ")

        assert_that(seen).is_equal_to([(1, "Games")])

    def test_start_rename_of_unknown_profile_is_ignored(self, selector):
        selector.start_rename(9)

        assert_that(_editor(selector)).is_none()


class TestRefresh:
    def test_an_identical_refresh_keeps_a_rename_in_progress(self, selector):
        selector.show_popup()
        selector.start_rename(1)
        _editor(selector).setText("Gam")

        selector.set_profiles(_PROFILES, 2)

        assert_that(selector._rename_edit).is_not_none()
        assert_that(selector._rename_edit.text()).is_equal_to("Gam")

    def test_a_changed_profile_list_cancels_the_rename(self, selector):
        selector.show_popup()
        selector.start_rename(1)

        selector.set_profiles(_PROFILES[:2], 2)

        assert_that(selector._rename_edit).is_none()
