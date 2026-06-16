import json

import pytest
from assertpy import assert_that

from decker.asset.manifest import (
    IconPackManifest,
    IconPackValidationError,
    validate_icons_json,
)

_VALID = {"Name": "My Pack", "Version": "1.0.0", "Author": "Someone"}


class TestIconPackManifest:
    def test_loads_valid_manifest(self, tmp_path):
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(_VALID))
        manifest = IconPackManifest.load(path)
        assert_that(manifest.name).is_equal_to("My Pack")
        assert_that(manifest.version).is_equal_to("1.0.0")
        assert_that(manifest.author).is_equal_to("Someone")

    @pytest.mark.parametrize("field", ["Name", "Version", "Author"])
    def test_missing_required_field_raises(self, tmp_path, field):
        data = dict(_VALID)
        del data[field]
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(data))
        with pytest.raises(IconPackValidationError):
            IconPackManifest.load(path)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(IconPackValidationError):
            IconPackManifest.load(tmp_path / "missing.json")

    def test_malformed_json_raises(self, tmp_path):
        path = tmp_path / "manifest.json"
        path.write_text("{not valid")
        with pytest.raises(IconPackValidationError):
            IconPackManifest.load(path)

    def test_non_object_json_raises(self, tmp_path):
        path = tmp_path / "manifest.json"
        path.write_text("[1, 2]")
        with pytest.raises(IconPackValidationError):
            IconPackManifest.load(path)


class TestValidateIconsJson:
    def test_valid_object_passes(self, tmp_path):
        path = tmp_path / "icons.json"
        path.write_text(json.dumps({"icon1": "icon1.svg"}))
        validate_icons_json(path)  # should not raise

    def test_valid_array_passes(self, tmp_path):
        path = tmp_path / "icons.json"
        path.write_text(json.dumps(["icon1.svg"]))
        validate_icons_json(path)  # should not raise

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(IconPackValidationError):
            validate_icons_json(tmp_path / "missing.json")

    def test_malformed_json_raises(self, tmp_path):
        path = tmp_path / "icons.json"
        path.write_text("{not valid")
        with pytest.raises(IconPackValidationError):
            validate_icons_json(path)

    def test_scalar_json_raises(self, tmp_path):
        path = tmp_path / "icons.json"
        path.write_text("42")
        with pytest.raises(IconPackValidationError):
            validate_icons_json(path)
