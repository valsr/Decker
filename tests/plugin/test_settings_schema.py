from typing import Any

import pytest
from assertpy import assert_that

from decker.plugin.settings_schema import (
    FIELD_TYPES,
    SettingField,
    SettingSection,
    apply_schema,
    parse_settings_schema,
    schema_to_json,
)

COUNTER: list[dict[str, Any]] = [
    {"section": "Counting"},
    {"key": "step", "type": "int", "label": "Step", "default": 1, "min": 1, "max": 9999},
    {
        "key": "double_step",
        "type": "int",
        "label": "Double press step",
        "optional": True,
        "placeholder": "None (presses register immediately)",
    },
    {"key": "max", "type": "int", "label": "Max count", "default": 0, "min": 0, "special_value": "∞ (no limit)"},
]
COLOR: list[dict[str, Any]] = [{"key": "background", "type": "color", "label": "Background", "default": "#1f618d"}]
CHOICE: list[dict[str, Any]] = [
    {
        "key": "mode",
        "type": "choice",
        "label": "Mode",
        "default": "a",
        "options": [{"label": "A", "value": "a"}, {"label": "B", "value": "b"}],
    }
]


@pytest.fixture(name="counter_schema")
def fixture_counter_schema() -> tuple[Any, ...]:
    return parse_settings_schema(COUNTER, "counter")


def test_parses_sections_and_fields_in_order(counter_schema: tuple[Any, ...]) -> None:
    assert_that(counter_schema).is_length(4)
    assert_that(counter_schema[0]).is_equal_to(SettingSection("Counting"))
    step = counter_schema[1]
    assert_that(step).is_instance_of(SettingField)
    assert_that([e.key for e in counter_schema[1:]]).is_equal_to(["step", "double_step", "max"])
    assert_that(step.default).is_equal_to(1)
    assert_that(step.extra["min"]).is_equal_to(1)
    assert_that(counter_schema[2].optional).is_true()
    assert_that(counter_schema[2].default).is_none()
    assert_that(counter_schema[3].extra["special_value"]).is_equal_to("∞ (no limit)")
    assert_that(FIELD_TYPES).contains("int", "icon", "font")


def test_unknown_type_rejected() -> None:
    with pytest.raises(ValueError, match="here.*unknown field type"):
        parse_settings_schema([{"key": "a", "type": "slider"}], "here")


def test_duplicate_key_rejected() -> None:
    data = [{"key": "a", "type": "bool"}, {"key": "a", "type": "text"}]
    with pytest.raises(ValueError, match="here.*duplicate"):
        parse_settings_schema(data, "here")


def test_choice_requires_options() -> None:
    with pytest.raises(ValueError, match="options"):
        parse_settings_schema([{"key": "a", "type": "choice"}], "here")


def test_default_must_match_type() -> None:
    with pytest.raises(ValueError, match="here"):
        parse_settings_schema([{"key": "a", "type": "int", "default": "x"}], "here")


def test_default_must_be_valid_for_choice_and_color() -> None:
    with pytest.raises(ValueError, match="default"):
        parse_settings_schema([{**CHOICE[0], "default": "zzz"}], "here")
    with pytest.raises(ValueError, match="default"):
        parse_settings_schema([{**COLOR[0], "default": "blue"}], "here")


def test_non_list_and_bad_entries_rejected() -> None:
    bad_inputs: list[Any] = [{}, [1], [{"section": ""}], [{"type": "int"}], [{"key": "a", "type": "int", "min": "x"}]]
    for bad in bad_inputs:
        with pytest.raises(ValueError, match="here"):
            parse_settings_schema(bad, "here")


def test_missing_default_uses_zero_value() -> None:
    data = [{"key": k, "type": t} for k, t in (("i", "int"), ("f", "float"), ("t", "text"), ("b", "bool"))]
    schema = parse_settings_schema(data + CHOICE, "x")
    assert_that(apply_schema(schema, {})).is_equal_to({"i": 0, "f": 0.0, "t": "", "b": False, "mode": "a"})


def test_apply_fills_defaults(counter_schema: tuple[Any, ...]) -> None:
    assert_that(apply_schema(counter_schema, {})).is_equal_to({"step": 1, "double_step": None, "max": 0})


def test_apply_drops_unknown_keys(counter_schema: tuple[Any, ...]) -> None:
    assert_that(apply_schema(counter_schema, {"bogus": 1, "step": 2})).does_not_contain_key("bogus")


def test_apply_replaces_invalid_values_with_default(counter_schema: tuple[Any, ...]) -> None:
    assert_that(apply_schema(counter_schema, {"step": "abc"})["step"]).is_equal_to(1)
    assert_that(apply_schema(counter_schema, {"step": 0})["step"]).is_equal_to(1)
    assert_that(apply_schema(counter_schema, {"step": True})["step"]).is_equal_to(1)
    color = parse_settings_schema(COLOR, "c")
    assert_that(apply_schema(color, {"background": "blue"})["background"]).is_equal_to("#1f618d")
    assert_that(apply_schema(color, {"background": "#00ff00"})["background"]).is_equal_to("#00ff00")


def test_apply_optional_empty_becomes_none(counter_schema: tuple[Any, ...]) -> None:
    assert_that(apply_schema(counter_schema, {"double_step": ""})["double_step"]).is_none()
    assert_that(apply_schema(counter_schema, {"double_step": None})["double_step"]).is_none()
    assert_that(apply_schema(counter_schema, {"double_step": 3})["double_step"]).is_equal_to(3)


def test_apply_coerces_int_strings(counter_schema: tuple[Any, ...]) -> None:
    assert_that(apply_schema(counter_schema, {"step": "5"})["step"]).is_equal_to(5)


def test_apply_choice_outside_options_uses_default() -> None:
    schema = parse_settings_schema(CHOICE, "c")
    assert_that(apply_schema(schema, {"mode": "zzz"})["mode"]).is_equal_to("a")
    assert_that(apply_schema(schema, {"mode": "b"})["mode"]).is_equal_to("b")


def test_apply_float_bool_text() -> None:
    data = [
        {"key": "f", "type": "float", "default": 1.5, "max": 2},
        {"key": "b", "type": "bool", "default": True},
        {"key": "t", "type": "text", "default": "x"},
    ]
    schema = parse_settings_schema(data, "x")
    assert_that(apply_schema(schema, {"f": "1.25", "b": "no", "t": 5})).is_equal_to({"f": 1.25, "b": True, "t": "x"})
    assert_that(apply_schema(schema, {"f": 3, "t": "hi"})).is_equal_to({"f": 1.5, "b": True, "t": "hi"})
    assert_that(apply_schema(schema, {"f": "nan"})["f"]).is_equal_to(1.5)


def test_schema_to_json_round_trips(counter_schema: tuple[Any, ...]) -> None:
    for data in (COUNTER, COLOR, CHOICE):
        schema = parse_settings_schema(data, "x")
        dumped = schema_to_json(schema)
        assert_that(parse_settings_schema(dumped, "x")).is_equal_to(schema)
    assert_that(schema_to_json(counter_schema)[1]).is_equal_to(COUNTER[1])
    assert_that(schema_to_json(counter_schema)[0]).is_equal_to({"section": "Counting"})


def test_huge_int_for_float_falls_back_to_default() -> None:
    schema = parse_settings_schema([{"key": "f", "type": "float", "default": 1.5}], "x")
    assert_that(apply_schema(schema, {"f": 10**400})["f"]).is_equal_to(1.5)


def test_huge_int_float_default_rejected() -> None:
    with pytest.raises(ValueError, match="here"):
        parse_settings_schema([{"key": "f", "type": "float", "default": 10**400}], "here")
