from pathlib import Path
from typing import Any

from assertpy import assert_that

from decker.plugin.loader import InstalledPlugin
from decker.plugin.manifest import PluginManifest
from decker.plugin.settings_store import PluginSettingsStore
from decker.server.plugins import PluginManager


def _plugin(tmp_path: Path, plugin_id: str, variables: list[dict[str, Any]]) -> InstalledPlugin:
    data = {
        "format": 2,
        "id": plugin_id,
        "name": "V",
        "version": "1.0.0",
        "author": "a",
        "decker": ">=0.6",
        "runtime": {"type": "python", "entry": "plugin.py"},
        "contributes": {"variables": variables},
    }
    return InstalledPlugin(PluginManifest.from_dict(data), tmp_path)


def _manager(tmp_path: Path) -> PluginManager:
    manager = PluginManager(tmp_path / "plugins", settings_store=PluginSettingsStore(tmp_path / "plugins.db"))
    manager._sdk_path = tmp_path  # pylint: disable=protected-access  # the process is never started here
    return manager


def test_adding_plugin_declares_variables(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    try:
        manager.add_plugin(_plugin(tmp_path, "com.t.one", [{"name": "media_volume"}, {"pattern": "m_{x}_v"}]))

        assert_that(manager.variables.owner_of("media_volume")).is_equal_to("com.t.one")
        assert_that(manager.variables.owner_of("m_a_v")).is_equal_to("com.t.one")
        assert_that(manager.load_failures()).is_empty()
    finally:
        manager.destroy()


def test_second_plugin_with_same_name_fails_to_load_and_first_keeps_working(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    try:
        manager.add_plugin(_plugin(tmp_path, "com.t.one", [{"name": "media_volume"}]))
        manager.add_plugin(_plugin(tmp_path, "com.t.two", [{"name": "other_one"}, {"name": "media_volume"}]))

        assert_that(manager.variables.owner_of("media_volume")).is_equal_to("com.t.one")
        assert_that(manager.variables.owner_of("other_one")).is_none()
        failures = manager.load_failures()
        assert_that([f.plugin_uuid for f in failures]).is_equal_to(["com.t.two"])
        assert_that(failures[0].error).contains("media_volume")
        assert_that(manager._supervisor._entries).contains_key("com.t.one").does_not_contain_key("com.t.two")
    finally:
        manager.destroy()


def test_removing_plugin_frees_its_names(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    try:
        manager.add_plugin(_plugin(tmp_path, "com.t.one", [{"name": "media_volume"}]))
        manager.remove_plugin("com.t.one")

        assert_that(manager.variables.owner_of("media_volume")).is_none()
        manager.add_plugin(_plugin(tmp_path, "com.t.two", [{"name": "media_volume"}]))
        assert_that(manager.variables.owner_of("media_volume")).is_equal_to("com.t.two")
    finally:
        manager.destroy()
