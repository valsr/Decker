"""Tests for decker.client.widgets.repositories_section."""

import threading
from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that
from PyQt6.QtWidgets import QInputDialog, QMessageBox

from decker.client.context import AppContext
from decker.client.widgets import plugins_tab
from decker.client.widgets.repositories_section import (
    REPOSITORY_TRUST_WARNING,
    RepositoriesSection,
)

# pylint: disable=protected-access,redefined-outer-name,unused-argument

_REPOS = [
    {"url": "https://a.example/index.json", "name": "Alpha", "plugin_count": 3, "last_checked": 1.0, "error": ""},
    {"url": "https://b.example/index.json", "name": "", "plugin_count": 0, "last_checked": None, "error": "boom"},
]


@pytest.fixture
def manager(qapp):
    AppContext.reset()
    cm = MagicMock()
    answers = {
        "repositories_list": _REPOS,
        "update_check_schedule": "monthly",
        "repository_add": "",
        "repository_remove": True,
        "update_check_set_schedule": True,
        "repositories_check": {"updates": [{"id": "x"}], "missing": []},
    }
    cm.call.side_effect = lambda method, *args: answers.get(method)
    cm.answers = answers
    AppContext.get().connection_manager = cm
    yield cm
    AppContext.reset()
    plugins_tab._install_allowed_cache = False


def _settle(section, qapp):
    while section._worker is not None and section._worker.is_alive():
        section._worker.join(1)
    qapp.processEvents()


@pytest.fixture
def section(manager, qapp):
    plugins_tab._install_allowed_cache = True
    widget = RepositoriesSection()
    widget.refresh()
    _settle(widget, qapp)
    return widget


def _methods(manager):
    return [c.args[0] for c in manager.call.call_args_list]


def test_lists_repositories_with_error(section):
    assert_that(section._list.count()).is_equal_to(2)
    first, second = section._list.item(0).text(), section._list.item(1).text()
    assert_that(first).contains("Alpha", "https://a.example/index.json", "3 plugins")
    assert_that(second).contains("boom", "never")
    assert_that(section._schedule.currentText()).is_equal_to("Monthly")


def test_add_shows_trust_warning_and_calls_rpc(section, manager, qapp):
    with (
        patch.object(QInputDialog, "getText", return_value=("https://c.example/i.json", True)),
        patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes) as question,
    ):
        section._add_btn.click()
    _settle(section, qapp)

    assert_that(question.call_args.args[2]).is_equal_to(REPOSITORY_TRUST_WARNING)
    manager.call.assert_any_call("repository_add", "https://c.example/i.json")


def test_add_failure_shows_error(section, manager, qapp):
    manager.answers["repository_add"] = "unreachable"
    with (
        patch.object(QInputDialog, "getText", return_value=("https://c.example/i.json", True)),
        patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
    ):
        section._add_btn.click()
    _settle(section, qapp)

    assert_that(section._status.text()).is_equal_to("unreachable")


def test_add_cancelled_on_warning_does_not_call(section, manager):
    with (
        patch.object(QInputDialog, "getText", return_value=("https://c.example/i.json", True)),
        patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No),
    ):
        section._add_btn.click()

    assert_that(_methods(manager)).does_not_contain("repository_add")


def test_remove_confirms_and_calls_rpc(section, manager, qapp):
    section._list.setCurrentRow(0)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        section._remove_btn.click()
    _settle(section, qapp)

    manager.call.assert_any_call("repository_remove", "https://a.example/index.json")


def test_schedule_change_calls_rpc(section, manager, qapp):
    section._schedule.setCurrentText("Daily")
    _settle(section, qapp)

    manager.call.assert_any_call("update_check_set_schedule", "daily")


def test_check_for_updates_runs_off_ui_thread(section, manager, qapp):
    threads: list[int] = []

    def fake(method, *args):
        if method == "repositories_check":
            threads.append(threading.get_ident())
        return manager.answers.get(method)

    manager.call.side_effect = fake
    section._check_btn.click()
    _settle(section, qapp)

    assert_that(threads).is_length(1)
    assert_that(threads[0]).is_not_equal_to(threading.get_ident())
    assert_that(section._status.text()).contains("1 update(s)")


def test_controls_disabled_when_not_allowed(manager, qapp):
    plugins_tab._install_allowed_cache = False
    widget = RepositoriesSection()
    widget.refresh()
    _settle(widget, qapp)
    widget._list.setCurrentRow(0)

    assert_that(widget._add_btn.isEnabled()).is_false()
    assert_that(widget._remove_btn.isEnabled()).is_false()
    assert_that(widget._schedule.isEnabled()).is_false()


def test_check_when_not_connected_restores_controls(section):
    AppContext.get().connection_manager = None
    section._check_btn.click()

    assert_that(section._check_btn.isEnabled()).is_true()
    assert_that(section._status.text()).is_equal_to("Not connected to the server.")


def test_failed_schedule_change_reverts_combo(section, manager, qapp):
    manager.answers["update_check_set_schedule"] = False
    section._schedule.setCurrentText("Daily")
    _settle(section, qapp)
    _settle(section, qapp)

    assert_that(section._schedule.currentText()).is_equal_to("Monthly")
    assert_that(section._status.text()).is_equal_to("Could not change the schedule.")
