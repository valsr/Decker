import pytest
from assertpy import assert_that

from decker.common.template import TEMPLATE_VARIABLES
from decker.common.variables import (
    CORE_VARIABLE_NAMES,
    MAX_DECLARATIONS,
    MAX_NAME_LENGTH,
    MAX_VALUE_LENGTH,
    is_valid_name,
    is_valid_pattern,
    match_pattern,
    pattern_shape,
    value_text,
)


def test_limits_and_core_names() -> None:
    assert_that((MAX_NAME_LENGTH, MAX_VALUE_LENGTH, MAX_DECLARATIONS)).is_equal_to((64, 1024, 256))
    assert_that(CORE_VARIABLE_NAMES).is_equal_to(frozenset(TEMPLATE_VARIABLES))


def test_valid_names() -> None:
    assert_that(is_valid_name("media_volume")).is_true()
    assert_that(is_valid_name("a1")).is_true()
    for bad in ("Media", "1a", "", "a" * 65):
        assert_that(is_valid_name(bad)).is_false()
    assert_that(is_valid_name("a" * 64)).is_true()


def test_pattern_validity() -> None:
    assert_that(is_valid_pattern("media_{device}_volume")).is_true()
    for bad in ("media_volume", "{a}{b}", "{a}_{a}", "media_{Device}"):
        assert_that(is_valid_pattern(bad)).is_false()


def test_match_pattern() -> None:
    pattern = "media_{device}_volume"
    assert_that(match_pattern(pattern, "media_speakers_volume")).is_equal_to({"device": "speakers"})
    assert_that(match_pattern(pattern, "media_volume")).is_none()
    assert_that(match_pattern(pattern, "other_speakers_volume")).is_none()


def test_pattern_shape_ignores_placeholder_names() -> None:
    assert_that(pattern_shape("a_{x}")).is_equal_to(pattern_shape("a_{y}"))
    assert_that(pattern_shape("a_{x}_b")).is_equal_to("a_{}_b")


def test_value_text() -> None:
    assert_that(value_text(True)).is_equal_to("true")
    assert_that(value_text(False)).is_equal_to("false")
    assert_that(value_text(3)).is_equal_to("3")
    assert_that(value_text(0.5)).is_equal_to("0.5")
    assert_that(value_text(None)).is_none()
    assert_that(value_text("hi")).is_equal_to("hi")
    assert_that(value_text("x" * 1024)).is_equal_to("x" * 1024)
    with pytest.raises(ValueError):
        value_text([1])
    with pytest.raises(ValueError):
        value_text("x" * 1025)
