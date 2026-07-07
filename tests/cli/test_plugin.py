import json

import pytest
from assertpy import assert_that

from decker.cli import plugin as plugin_cli

_NATIVE_MANIFEST = {
    "UUID": "com.decker.test",
    "Name": "Test",
    "Version": "1.0.0",
    "Author": "Decker",
    "Actions": [{"UUID": "com.decker.test.show", "Name": "Show"}],
}

_ELGATO_MANIFEST = {**_NATIVE_MANIFEST, "UUID": "com.elgato.cpu-monitor", "CodePath": "app.js"}


def _make_source_plugin(tmp_path, manifest=_NATIVE_MANIFEST, name="source"):
    source_dir = tmp_path / name
    source_dir.mkdir()
    (source_dir / "manifest.json").write_text(json.dumps(manifest))
    return source_dir


@pytest.fixture(autouse=True)
def _isolated_plugins_dir(tmp_path, monkeypatch):
    plugins_dir = tmp_path / "installed-plugins"
    monkeypatch.setattr("decker.common.paths.plugins", lambda: plugins_dir)
    return plugins_dir


class TestInstall:
    def test_installs_native_plugin_by_uuid(self, tmp_path, _isolated_plugins_dir):
        source = _make_source_plugin(tmp_path)
        dest = plugin_cli.install(source)
        assert_that(dest).is_equal_to(_isolated_plugins_dir / "com.decker.test")
        assert_that((dest / "manifest.json").exists()).is_true()

    def test_installs_elgato_plugin_with_sdplugin_suffix(self, tmp_path, _isolated_plugins_dir):
        source = _make_source_plugin(tmp_path, manifest=_ELGATO_MANIFEST, name="elgato-source")
        dest = plugin_cli.install(source)
        assert_that(dest).is_equal_to(_isolated_plugins_dir / "com.elgato.cpu-monitor.sdPlugin")

    def test_missing_manifest_raises(self, tmp_path):
        source = tmp_path / "no-manifest"
        source.mkdir()
        with pytest.raises(plugin_cli.PluginCliError):
            plugin_cli.install(source)

    def test_invalid_manifest_raises(self, tmp_path):
        source = tmp_path / "bad"
        source.mkdir()
        (source / "manifest.json").write_text(json.dumps({"Name": "Missing fields"}))
        with pytest.raises(plugin_cli.PluginCliError):
            plugin_cli.install(source)

    def test_duplicate_install_raises(self, tmp_path):
        source = _make_source_plugin(tmp_path)
        plugin_cli.install(source)
        with pytest.raises(plugin_cli.PluginCliError, match="already installed"):
            plugin_cli.install(source)


class TestListInstalled:
    def test_empty_when_no_plugins_dir(self):
        assert_that(plugin_cli.list_installed()).is_equal_to([])

    def test_lists_installed_native_plugin(self, tmp_path):
        plugin_cli.install(_make_source_plugin(tmp_path))
        result = plugin_cli.list_installed()
        assert_that(result).is_equal_to([{"uuid": "com.decker.test", "type": "native", "status": "ok"}])

    def test_lists_invalid_plugin_with_status(self, tmp_path, _isolated_plugins_dir):
        broken_dir = _isolated_plugins_dir / "broken"
        broken_dir.mkdir(parents=True)
        (broken_dir / "manifest.json").write_text("{not valid json")
        result = plugin_cli.list_installed()
        assert_that(result).is_length(1)
        assert_that(result[0]["uuid"]).is_equal_to("broken")
        assert_that(result[0]["status"]).starts_with("invalid")


class TestRemove:
    def test_removes_native_plugin(self, tmp_path, _isolated_plugins_dir):
        dest = plugin_cli.install(_make_source_plugin(tmp_path))
        plugin_cli.remove("com.decker.test")
        assert_that(dest.exists()).is_false()

    def test_removes_elgato_plugin(self, tmp_path, _isolated_plugins_dir):
        source = _make_source_plugin(tmp_path, manifest=_ELGATO_MANIFEST, name="elgato-source")
        dest = plugin_cli.install(source)
        plugin_cli.remove("com.elgato.cpu-monitor")
        assert_that(dest.exists()).is_false()

    def test_remove_unknown_uuid_raises(self):
        with pytest.raises(plugin_cli.PluginCliError):
            plugin_cli.remove("com.decker.does-not-exist")
