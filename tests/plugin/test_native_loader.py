import json

import pytest
from assertpy import assert_that

from decker.plugin.native_loader import NativePluginLoadError, load_native_plugin

_MANIFEST = {
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
    def on_key_down(self, ctx):
        pass
"""


def _write_plugin(tmp_path, manifest=None, plugin_py=_PLUGIN_PY):
    plugin_dir = tmp_path / "com.decker.test"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest if manifest is not None else _MANIFEST))
    if plugin_py is not None:
        (plugin_dir / "plugin.py").write_text(plugin_py)
    return plugin_dir


class TestLoadNativePlugin:
    def test_loads_valid_plugin(self, tmp_path):
        plugin_dir = _write_plugin(tmp_path)
        loaded = load_native_plugin(plugin_dir)
        assert_that(loaded.manifest.uuid).is_equal_to("com.decker.test")
        assert_that(loaded.action_classes).contains_key("com.decker.test.show")
        assert_that(loaded.plugin_dir).is_equal_to(plugin_dir)

    def test_invalid_manifest_raises(self, tmp_path):
        plugin_dir = _write_plugin(tmp_path, manifest={"Name": "Missing fields"})
        with pytest.raises(NativePluginLoadError):
            load_native_plugin(plugin_dir)

    def test_missing_plugin_py_raises(self, tmp_path):
        plugin_dir = _write_plugin(tmp_path, plugin_py=None)
        with pytest.raises(NativePluginLoadError):
            load_native_plugin(plugin_dir)

    def test_plugin_py_import_error_raises(self, tmp_path):
        plugin_dir = _write_plugin(tmp_path, plugin_py="raise ImportError('boom')\n")
        with pytest.raises(NativePluginLoadError):
            load_native_plugin(plugin_dir)

    def test_missing_action_class_raises(self, tmp_path):
        plugin_dir = _write_plugin(tmp_path, plugin_py="from decker.plugin import DeckerPlugin\n")
        with pytest.raises(NativePluginLoadError):
            load_native_plugin(plugin_dir)
