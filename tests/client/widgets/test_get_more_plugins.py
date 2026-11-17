"""Tests for decker.client.widgets.get_more_plugins."""

import threading
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that

from decker.client.context import AppContext
from decker.client.events import (
    PluginInstallFinishedEvent,
    PluginInstallProgressEvent,
    PluginsChangedEvent,
    ServerDisconnectedEvent,
)
from decker.client.events.event_manager import EventManager
from decker.client.widgets import plugins_tab
from decker.client.widgets.get_more_plugins import (
    GetMorePluginsDialog,
    button_state,
    human_size,
)

# pylint: disable=protected-access,redefined-outer-name,unused-argument


def _plugin(plugin_id, name, **overrides):
    version = {"version": "2.0.0", "decker": ">=0.1", "size": 2048, "released": "2026-01-01", "compatible": True}
    plugin = {
        "id": plugin_id,
        "name": name,
        "author": "Acme",
        "description": f"{name} description",
        "category": "Tools",
        "homepage": "https://acme.example",
        "repository": "https://repo.example/index.json",
        "shadowed_by": [],
        "installed_version": None,
        "latest_compatible": "2.0.0",
        "versions": [{**version, "contributes": {"actions": ["Do it"], "icon_packs": []}}],
    }
    plugin.update(overrides)
    return plugin


_CATALOG = [
    _plugin("a.fresh", "Fresh"),
    _plugin("a.update", "Updatable", installed_version="1.0.0", category="Media", author="Zed"),
    _plugin("a.done", "Done", installed_version="2.0.0"),
    _plugin(
        "a.old",
        "Incompatible",
        latest_compatible=None,
        versions=[
            {"version": "9.0.0", "decker": ">=9", "size": 1, "released": "", "compatible": False, "contributes": {}}
        ],
    ),
]


@pytest.fixture
def manager(qapp):
    AppContext.reset()
    EventManager.reset()
    cm = MagicMock()
    answers = {"repository_catalog": _CATALOG, "repository_icon": "", "plugin_install_from_repository": "job-1"}
    cm.call.side_effect = lambda method, *args: answers.get(method)
    cm.answers = answers
    AppContext.get().connection_manager = cm
    plugins_tab._install_allowed_cache = True
    yield cm
    AppContext.reset()
    EventManager.reset()
    plugins_tab._install_allowed_cache = False


def _settle(dialog, qapp):
    for _ in range(3):
        for worker in (dialog._worker, dialog._icon_worker):
            while worker is not None and worker.is_alive():
                worker.join(1)
        qapp.processEvents()


@pytest.fixture
def dialog(manager, qapp):
    widget = GetMorePluginsDialog()
    _settle(widget, qapp)
    yield widget
    widget.close()
    widget.deleteLater()


def test_filters_by_search_and_category(dialog):
    assert_that(dialog._rows).is_length(4)
    assert_that(dialog._category.itemText(0)).is_equal_to("All categories")
    assert_that([dialog._category.itemText(i) for i in range(dialog._category.count())]).contains("Media", "Tools")

    dialog._search.setText("ZED")
    assert_that(list(dialog._rows)).is_equal_to(["a.update"])
    dialog._search.setText("a.fresh")
    assert_that(list(dialog._rows)).is_equal_to(["a.fresh"])
    dialog._search.setText("")
    dialog._category.setCurrentText("Media")
    assert_that(list(dialog._rows)).is_equal_to(["a.update"])


def test_button_states(dialog):
    states = {pid: (row.button.text(), row.button.isEnabled()) for pid, row in dialog._rows.items()}
    assert_that(states["a.fresh"]).is_equal_to(("Install", True))
    assert_that(states["a.update"]).is_equal_to(("Update", True))
    assert_that(states["a.done"]).is_equal_to(("Installed", False))
    assert_that(states["a.old"]).is_equal_to(("Requires Decker >=9", False))


def test_install_calls_rpc_and_disables_buttons(dialog, manager, qapp):
    dialog._rows["a.fresh"].button.click()
    _settle(dialog, qapp)

    installs = [c.args for c in manager.call.call_args_list if c.args[0] == "plugin_install_from_repository"]
    assert_that(installs).is_equal_to([("plugin_install_from_repository", "a.fresh")])
    assert_that(dialog._rows["a.fresh"].button.isEnabled()).is_false()
    assert_that(dialog._rows["a.update"].button.isEnabled()).is_false()
    dialog._on_progress(PluginInstallProgressEvent(job_id="other", message="Uploading x"))
    assert_that(dialog._rows["a.fresh"].button.text()).is_equal_to("Installing…")
    dialog._on_progress(PluginInstallProgressEvent(job_id="job-1", message="Downloading…"))
    assert_that(dialog._rows["a.fresh"].button.text()).is_equal_to("Downloading…")
    dialog._on_finished(
        PluginInstallFinishedEvent(job_id="other", ok=True, plugin_id="x", version="1", previous_version="", message="")
    )
    assert_that(dialog._installing).is_equal_to("a.fresh")


def test_install_error_is_reported_and_buttons_return(dialog, manager, qapp):
    manager.answers["plugin_install_from_repository"] = "error: nope"
    dialog._rows["a.fresh"].button.click()
    _settle(dialog, qapp)

    assert_that(dialog._status.text()).contains("nope")
    assert_that(dialog._rows["a.fresh"].button.isEnabled()).is_true()


def test_finished_event_refreshes(dialog, manager, qapp):
    dialog._rows["a.fresh"].button.click()
    _settle(dialog, qapp)
    manager.answers["repository_catalog"] = [_plugin("a.fresh", "Fresh", installed_version="2.0.0")]

    dialog._on_finished(
        PluginInstallFinishedEvent(
            job_id="job-1", ok=True, plugin_id="a.fresh", version="2.0.0", previous_version="", message=""
        )
    )
    _settle(dialog, qapp)

    assert_that(list(dialog._rows)).is_equal_to(["a.fresh"])
    assert_that(dialog._rows["a.fresh"].button.text()).is_equal_to("Installed")
    assert_that(dialog._status.text()).contains("Installed a.fresh")


def test_details_pane_shows_size_and_repository(dialog):
    dialog._list.setCurrentRow(0)
    text = dialog._details.text()
    assert_that(text).contains("2.0 KiB", "https://repo.example/index.json", "Acme", "https://acme.example", "&gt;=0.1")
    assert_that(text).contains("Do it")


def test_icons_load_one_at_a_time_off_the_ui_thread(dialog, manager, qapp):
    _settle(dialog, qapp)
    ids = [c.args[1] for c in manager.call.call_args_list if c.args[0] == "repository_icon"]
    assert_that(ids).contains("a.fresh", "a.old")


def test_human_size():
    assert_that(human_size(512)).is_equal_to("512 B")
    assert_that(human_size(3 * 1024 * 1024)).is_equal_to("3.0 MiB")


def test_not_connected_reports_and_keeps_buttons_usable(dialog, qapp):
    AppContext.get().connection_manager = None
    dialog.refresh()
    assert_that(dialog._status.text()).contains("Not connected")

    dialog._rows["a.fresh"].button.click()
    assert_that(dialog._installing).is_none()
    assert_that(dialog._status.text()).contains("Not connected")
    assert_that(dialog._rows["a.fresh"].button.isEnabled()).is_true()


def test_rpc_exception_restores_buttons(dialog, manager, qapp):
    manager.call.side_effect = RuntimeError("boom")
    dialog._rows["a.fresh"].button.click()
    _settle(dialog, qapp)

    assert_that(dialog._installing).is_none()
    assert_that(dialog._status.text()).contains("Install failed")
    assert_that(dialog._rows["a.fresh"].button.isEnabled()).is_true()

    dialog.refresh()
    _settle(dialog, qapp)
    assert_that(dialog._status.text()).contains("Could not load")


def test_finished_before_job_id_is_replayed(dialog, manager, qapp):
    dialog._installing = "a.fresh"
    dialog._on_finished(
        PluginInstallFinishedEvent(
            job_id="job-1", ok=True, plugin_id="a.fresh", version="2.0.0", previous_version="", message=""
        )
    )
    assert_that(dialog._installing).is_equal_to("a.fresh")
    dialog._after_start("job-1")
    _settle(dialog, qapp)
    assert_that(dialog._installing).is_none()


def test_plugins_changed_reloads_catalog_when_idle(dialog, manager, qapp):
    manager.answers["repository_catalog"] = [_plugin("a.fresh", "Fresh", installed_version="2.0.0")]

    EventManager.get().emit(PluginsChangedEvent())
    _settle(dialog, qapp)

    assert_that(list(dialog._rows)).is_equal_to(["a.fresh"])
    assert_that(dialog._rows["a.fresh"].button.text()).is_equal_to("Installed")


def test_plugins_changed_ignored_while_installing(dialog, manager, qapp):
    dialog._rows["a.fresh"].button.click()
    _settle(dialog, qapp)
    manager.answers["repository_catalog"] = []

    EventManager.get().emit(PluginsChangedEvent())
    _settle(dialog, qapp)

    assert_that(dialog._rows).is_length(4)


def test_icon_rpc_runs_on_a_worker_thread(manager, qapp):
    threads: list[int] = []

    def fake(method, *args):
        if method == "repository_icon":
            threads.append(threading.get_ident())
        return {"repository_catalog": [_plugin("a.fresh", "Fresh")]}.get(method, "")

    manager.call.side_effect = fake
    widget = GetMorePluginsDialog()
    _settle(widget, qapp)

    assert_that(threads).is_length(1)
    assert_that(threads[0]).is_not_equal_to(threading.get_ident())
    widget.close()


def test_shadowed_duplicates_are_hidden_and_noted_on_the_winner(manager, qapp):
    manager.answers["repository_catalog"] = [
        _plugin("a.dup", "Dup", repository="https://one.example/index.json"),
        _plugin(
            "a.dup",
            "Dup",
            repository="https://two.example/index.json",
            shadowed_by="https://one.example/index.json",
            installed_version="1.0.0",
        ),
    ]
    widget = GetMorePluginsDialog()
    _settle(widget, qapp)

    assert_that(widget._list.count()).is_equal_to(1)
    assert_that(widget._rows["a.dup"].button.text()).is_equal_to("Install")
    widget._list.setCurrentRow(0)
    text = widget._details.text()
    assert_that(text).contains("Also offered by https://two.example/index.json (not used)")
    assert_that(text).contains("Repository: https://one.example/index.json")
    widget.close()


def test_fallback_uses_the_newest_version_when_none_is_compatible():
    plugin = _plugin(
        "a.old",
        "Old",
        latest_compatible=None,
        versions=[
            {"version": "9.0.0", "decker": ">=9", "size": 1, "contributes": {}},
            {"version": "1.0.0", "decker": ">=1", "size": 1, "contributes": {}},
        ],
    )
    assert_that(button_state(plugin)).is_equal_to(("Requires Decker >=9", False))


def test_install_controls_disabled_when_not_allowed(manager, qapp):
    plugins_tab._install_allowed_cache = False
    widget = GetMorePluginsDialog()
    _settle(widget, qapp)

    assert_that(widget._rows["a.fresh"].button.isEnabled()).is_false()
    assert_that(widget._rows["a.update"].button.isEnabled()).is_false()
    assert_that(widget._rows["a.fresh"].button.toolTip()).is_not_empty()
    widget._on_install("a.fresh")
    assert_that(widget._installing).is_none()
    widget.close()


def test_disconnect_resets_the_in_flight_install(dialog, manager, qapp):
    dialog._rows["a.fresh"].button.click()
    _settle(dialog, qapp)
    assert_that(dialog._installing).is_equal_to("a.fresh")

    EventManager.get().emit(ServerDisconnectedEvent(reason="gone"))

    assert_that(dialog._installing).is_none()
    assert_that(dialog._status.text()).contains("a.fresh", "interrupted")
    assert_that(dialog._rows["a.fresh"].button.isEnabled()).is_true()
