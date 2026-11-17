import json

from assertpy import assert_that

from decker.plugin.loader import PluginLoader

_MANIFEST = {
    "format": 1,
    "id": "com.decker.test",
    "name": "Test",
    "version": "1.0.0",
    "author": "Decker",
    "runtime": {"type": "python", "entry": "plugin.py"},
    "contributes": {"actions": [{"id": "com.decker.test.show", "name": "Show"}]},
}


def _make_plugin(plugins_dir, manifest=None, name="com.decker.test"):
    plugin_dir = plugins_dir / name
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest or _MANIFEST))
    return plugin_dir


class TestPluginLoader:
    def test_missing_directory_returns_empty_result(self, tmp_path):
        result = PluginLoader(tmp_path / "plugins").scan()

        assert_that(result.plugins).is_empty()
        assert_that(result.failures).is_empty()

    def test_scans_plugin_folders(self, tmp_path):
        plugin_dir = _make_plugin(tmp_path)
        (tmp_path / "stray-file.txt").write_text("ignored")

        result = PluginLoader(tmp_path).scan()

        assert_that(result.plugins).is_length(1)
        assert_that(result.plugins[0].manifest.id).is_equal_to("com.decker.test")
        assert_that(result.plugins[0].plugin_dir).is_equal_to(plugin_dir)
        assert_that(result.failures).is_empty()

    def test_invalid_manifest_reported_as_failure(self, tmp_path):
        broken = tmp_path / "com.decker.broken"
        broken.mkdir()
        (broken / "manifest.json").write_text("{not valid json")
        _make_plugin(tmp_path)

        result = PluginLoader(tmp_path).scan()

        assert_that(result.plugins).extracting("manifest").extracting("id").contains_only("com.decker.test")
        assert_that(result.failures).is_length(1)
        assert_that(result.failures[0].plugin_uuid).is_equal_to("com.decker.broken")
        assert_that(result.failures[0].error).contains("malformed JSON")

    def test_old_format_manifest_is_a_failure(self, tmp_path):
        _make_plugin(tmp_path, {"UUID": "com.decker.old", "Name": "Old"}, name="com.decker.old")

        result = PluginLoader(tmp_path).scan()

        assert_that(result.plugins).is_empty()
        assert_that(result.failures).is_length(1)

    def test_bundled_flag_set(self, tmp_path):
        _make_plugin(tmp_path)

        assert_that(PluginLoader(tmp_path, bundled=True).scan().plugins[0].bundled).is_true()
        assert_that(PluginLoader(tmp_path).scan().plugins[0].bundled).is_false()


def test_recover_drops_staging_and_restores_a_moved_aside_version(tmp_path):
    import json

    from decker.plugin.loader import recover_interrupted_installs

    (tmp_path / ".staging-abc").mkdir()
    (tmp_path / ".staging-abc" / "junk").write_text("x")
    old = tmp_path / ".old-job1"
    old.mkdir()
    (old / "manifest.json").write_text(json.dumps({"id": "com.example.tool"}))
    stale = tmp_path / ".old-job2"
    stale.mkdir()
    (stale / "manifest.json").write_text(json.dumps({"id": "com.example.kept"}))
    (tmp_path / "com.example.kept").mkdir()

    recover_interrupted_installs(tmp_path)

    assert (tmp_path / "com.example.tool" / "manifest.json").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["com.example.kept", "com.example.tool"]
