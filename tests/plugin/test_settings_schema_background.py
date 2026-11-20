from assertpy import assert_that

from decker.plugin.settings_schema import apply_schema, parse_settings_schema

_FIELD = {"key": "bg", "type": "background", "label": "Bg"}


def test_manifest_schema_accepts_background_field_and_string_default() -> None:
    schema = parse_settings_schema([{**_FIELD, "default": "#112233"}], "t")
    assert_that(apply_schema(schema, {})["bg"]).is_equal_to({"type": "color", "color": "#112233", "image": {"ref": ""}})
    plain = parse_settings_schema([_FIELD], "t")
    assert_that(apply_schema(plain, {})["bg"]).is_equal_to({"type": "color", "color": "#000000", "image": {"ref": ""}})
    assert_that(apply_schema(plain, {"bg": "#445566"})["bg"]["color"]).is_equal_to("#445566")
