import pytest
from assertpy import assert_that

from decker.plugin.manifest import ManifestValidationError, PluginManifest

_VALID = {
    "UUID": "com.decker.clock",
    "Name": "Clock",
    "Version": "1.0.0",
    "Author": "Decker",
    "Actions": [{"UUID": "com.decker.clock.show", "Name": "Show clock"}],
}


class TestFromDict:
    def test_valid_manifest_parses(self):
        manifest = PluginManifest.from_dict(_VALID)
        assert_that(manifest.uuid).is_equal_to("com.decker.clock")
        assert_that(manifest.actions).is_length(1)
        assert_that(manifest.actions[0].uuid).is_equal_to("com.decker.clock.show")

    @pytest.mark.parametrize("field", ["UUID", "Name", "Version", "Author", "Actions"])
    def test_missing_required_field_raises(self, field):
        data = dict(_VALID)
        del data[field]
        with pytest.raises(ManifestValidationError):
            PluginManifest.from_dict(data)

    def test_invalid_uuid_format_raises(self):
        with pytest.raises(ManifestValidationError):
            PluginManifest.from_dict({**_VALID, "UUID": "NotAValidUUID"})

    def test_empty_actions_raises(self):
        with pytest.raises(ManifestValidationError):
            PluginManifest.from_dict({**_VALID, "Actions": []})

    def test_actions_not_a_list_raises(self):
        with pytest.raises(ManifestValidationError):
            PluginManifest.from_dict({**_VALID, "Actions": "not-a-list"})

    def test_action_missing_uuid_raises(self):
        with pytest.raises(ManifestValidationError):
            PluginManifest.from_dict({**_VALID, "Actions": [{"Name": "No UUID"}]})

    def test_action_invalid_uuid_format_raises(self):
        with pytest.raises(ManifestValidationError):
            PluginManifest.from_dict({**_VALID, "Actions": [{"UUID": "Bad UUID", "Name": "x"}]})


class TestLoad:
    def test_loads_valid_manifest_file(self, tmp_path):
        path = tmp_path / "manifest.json"
        path.write_text(
            '{"UUID": "com.decker.clock", "Name": "Clock", "Version": "1.0.0", '
            '"Author": "Decker", "Actions": [{"UUID": "com.decker.clock.show", "Name": "Show"}]}'
        )
        manifest = PluginManifest.load(path)
        assert_that(manifest.uuid).is_equal_to("com.decker.clock")

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ManifestValidationError):
            PluginManifest.load(tmp_path / "missing.json")

    def test_malformed_json_raises(self, tmp_path):
        path = tmp_path / "manifest.json"
        path.write_text("{not valid json")
        with pytest.raises(ManifestValidationError):
            PluginManifest.load(path)

    def test_non_object_json_raises(self, tmp_path):
        path = tmp_path / "manifest.json"
        path.write_text("[1, 2, 3]")
        with pytest.raises(ManifestValidationError):
            PluginManifest.load(path)


class TestIcons:
    def _manifest(self, **overrides):
        data = {
            "UUID": "com.decker.x",
            "Name": "X",
            "Version": "1",
            "Author": "A",
            "Actions": [{"UUID": "com.decker.x.a", "Name": "A"}],
        }
        data.update(overrides)
        return PluginManifest.from_dict(data)

    def test_action_icon_defaults_to_none(self):
        assert_that(self._manifest().actions[0].icon).is_none()

    def test_action_icon_is_parsed(self):
        manifest = self._manifest(Actions=[{"UUID": "com.decker.x.a", "Name": "A", "Icon": "imgs/a"}])

        assert_that(manifest.actions[0].icon).is_equal_to("imgs/a")

    def test_plugin_icon_is_the_fallback_for_actions_without_one(self):
        manifest = self._manifest(
            Icon="imgs/plugin",
            Actions=[
                {"UUID": "com.decker.x.a", "Name": "A"},
                {"UUID": "com.decker.x.b", "Name": "B", "Icon": "imgs/b"},
            ],
        )

        assert_that([a.icon for a in manifest.actions]).is_equal_to(["imgs/plugin", "imgs/b"])

    def test_non_string_or_blank_icons_are_ignored(self):
        manifest = self._manifest(Icon=7, Actions=[{"UUID": "com.decker.x.a", "Name": "A", "Icon": "  "}])

        assert_that(manifest.actions[0].icon).is_none()
