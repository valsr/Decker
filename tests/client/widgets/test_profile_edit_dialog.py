"""Tests for decker.client.widgets.profile_edit_dialog.ProfileEditDialog."""

from unittest.mock import MagicMock

import pytest
from assertpy import assert_that
from PyQt6.QtWidgets import QMessageBox

from decker.client.widgets import profile_edit_dialog
from decker.client.widgets.profile_edit_dialog import (
    ProfileEditDialog,
    _confirm_delete_profile,
)
from decker.common.model import ProfileInfo

# pylint: disable=protected-access,redefined-outer-name

_PROFILE = ProfileInfo(2, "Work", "pack:a/b.svg")


@pytest.fixture()
def dialog(qapp):
    return ProfileEditDialog(_PROFILE, can_delete=True)


class TestFields:
    def test_shows_the_profiles_name_and_icon(self, dialog):
        assert_that(dialog.name()).is_equal_to("Work")
        assert_that(dialog.icon()).is_equal_to("pack:a/b.svg")

    def test_clearing_the_icon_means_the_decker_icon(self, dialog):
        dialog._icon.clear_icon()

        assert_that(dialog.icon()).is_equal_to("")

    def test_has_no_colour_swatch(self, dialog):
        assert_that(dialog._icon._colour.isVisibleTo(dialog)).is_false()


class TestAccept:
    def test_saving_records_the_outcome(self, dialog):
        dialog._name.setText("  Games ")

        dialog._save_button.click()

        assert_that(dialog.outcome).is_equal_to("save")
        assert_that(dialog.name()).is_equal_to("Games")

    @pytest.mark.parametrize("text", ["", "   "])
    def test_blank_name_is_refused(self, dialog, text):
        dialog._name.setText(text)

        dialog._save_button.click()

        assert_that(dialog.outcome).is_equal_to("")
        assert_that(dialog.result()).is_equal_to(0)

    def test_cancel_has_no_outcome(self, dialog):
        dialog.reject()

        assert_that(dialog.outcome).is_equal_to("")


class TestDeleteAndClone:
    def test_delete_asks_first(self, dialog, monkeypatch):
        asked = []
        monkeypatch.setattr(
            profile_edit_dialog, "_confirm_delete_profile", lambda parent, name: asked.append(name) or True
        )

        dialog._delete_button.click()

        assert_that(asked).is_equal_to(["Work"])
        assert_that(dialog.outcome).is_equal_to("delete")

    def test_declined_delete_keeps_the_dialog(self, dialog, monkeypatch):
        monkeypatch.setattr(profile_edit_dialog, "_confirm_delete_profile", lambda *_: False)

        dialog._delete_button.click()

        assert_that(dialog.outcome).is_equal_to("")

    def test_delete_is_disabled_for_the_last_profile(self, qapp):
        last = ProfileEditDialog(_PROFILE, can_delete=False)

        assert_that(last._delete_button.isEnabled()).is_false()

    def test_clone_records_the_outcome(self, dialog):
        dialog._clone_button.click()

        assert_that(dialog.outcome).is_equal_to("clone")

    def test_confirmation_warns_that_pages_are_deleted_too(self, qapp, monkeypatch):
        question = MagicMock(return_value=QMessageBox.StandardButton.Yes)
        monkeypatch.setattr(profile_edit_dialog.QMessageBox, "question", question)

        assert_that(_confirm_delete_profile(None, "Work")).is_true()

        text = question.call_args.args[2]
        assert_that(text).contains("Work").contains("pages")

    def test_confirmation_cancel_is_false(self, qapp, monkeypatch):
        monkeypatch.setattr(
            profile_edit_dialog.QMessageBox, "question", MagicMock(return_value=QMessageBox.StandardButton.Cancel)
        )

        assert_that(_confirm_delete_profile(None, "Work")).is_false()
