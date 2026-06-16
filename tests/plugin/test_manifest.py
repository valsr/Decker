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

    def test_code_path_defaults_to_none(self):
        manifest = PluginManifest.from_dict(_VALID)
        assert_that(manifest.code_path).is_none()

    def test_code_path_parsed_when_present(self):
        manifest = PluginManifest.from_dict({**_VALID, "CodePath": "app.js"})
        assert_that(manifest.code_path).is_equal_to("app.js")

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
