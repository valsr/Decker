import json

from assertpy import assert_that

from decker.plugin.loader import PluginLoader

_NATIVE_MANIFEST = {
    "UUID": "com.decker.test",
    "Name": "Test",
    "Version": "1.0.0",
    "Author": "Decker",
    "Actions": [{"UUID": "com.decker.test.show", "Name": "Show"}],
}

_PLUGIN_PY = """
from decker.plugin import DeckerPlugin, action


@action("com.decker.test.show")
class ShowAction(DeckerPlugin):
    pass
"""


def _make_native(plugins_dir):
    plugin_dir = plugins_dir / "com.decker.test"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(json.dumps(_NATIVE_MANIFEST))
    (plugin_dir / "plugin.py").write_text(_PLUGIN_PY)


def _make_broken_native(plugins_dir):
    plugin_dir = plugins_dir / "com.decker.broken"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text("{not valid json")


class TestPluginLoader:
    def test_empty_directory_returns_empty_result(self, tmp_path):
        result = PluginLoader(tmp_path / "plugins").scan()
        assert_that(result.native).is_empty()
        assert_that(result.failures).is_empty()

    def test_missing_directory_returns_empty_result(self, tmp_path):
        result = PluginLoader(tmp_path / "does-not-exist").scan()
        assert_that(result.native).is_empty()

    def test_loads_native_plugin(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        _make_native(plugins_dir)
        result = PluginLoader(plugins_dir).scan()
        assert_that(result.native).is_length(1)
        assert_that(result.native[0].manifest.uuid).is_equal_to("com.decker.test")

    def test_broken_native_plugin_does_not_block_others(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        _make_native(plugins_dir)
        _make_broken_native(plugins_dir)
        result = PluginLoader(plugins_dir).scan()
        assert_that(result.native).is_length(1)
        assert_that(result.failures).is_length(1)
        assert_that(result.failures[0].plugin_uuid).is_equal_to("com.decker.broken")

    def test_non_directory_entries_are_ignored(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        (plugins_dir / "stray-file.txt").write_text("not a plugin")
        result = PluginLoader(plugins_dir).scan()
        assert_that(result.native).is_empty()
        assert_that(result.failures).is_empty()
