"""Unit tests for decker.common.coerce."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

from assertpy import assert_that

from decker.common.coerce import from_dict

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class Color(StrEnum):
    RED = "red"
    BLUE = "blue"


@dataclass
class Inner:
    x: int
    label: str | None = None


@dataclass
class Outer:
    name: str
    count: int
    color: Color
    inner: Inner
    tags: list[str]


@dataclass
class WithOptional:
    value: str | None
    code: Optional[int]


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


class TestPrimitives:
    def test_none_returns_none(self):
        assert_that(from_dict(str, None)).is_none()

    def test_str_passthrough(self):
        assert_that(from_dict(str, "hello")).is_equal_to("hello")

    def test_int_passthrough(self):
        assert_that(from_dict(int, 42)).is_equal_to(42)

    def test_int_coerced_from_string(self):
        assert_that(from_dict(int, "7")).is_equal_to(7)

    def test_float_coerced_from_int(self):
        assert_that(from_dict(float, 3)).is_equal_to(3.0)

    def test_bool_passthrough(self):
        assert_that(from_dict(bool, True)).is_true()


# ---------------------------------------------------------------------------
# StrEnum
# ---------------------------------------------------------------------------


class TestStrEnum:
    def test_enum_from_string(self):
        assert_that(from_dict(Color, "red")).is_equal_to(Color.RED)

    def test_enum_passthrough_when_already_correct(self):
        assert_that(from_dict(Color, Color.BLUE)).is_equal_to(Color.BLUE)

    def test_enum_is_singleton(self):
        result = from_dict(Color, "blue")
        assert_that(result).is_same_as(Color.BLUE)


# ---------------------------------------------------------------------------
# Optional / Union
# ---------------------------------------------------------------------------


class TestUnion:
    def test_optional_str_with_value(self):
        assert_that(from_dict(str | None, "hello")).is_equal_to("hello")

    def test_optional_str_with_none(self):
        assert_that(from_dict(str | None, None)).is_none()

    def test_optional_int_with_value(self):
        assert_that(from_dict(Optional[int], 5)).is_equal_to(5)

    def test_optional_int_coerced_from_str(self):
        assert_that(from_dict(Optional[int], "9")).is_equal_to(9)

    def test_optional_enum_from_string(self):
        result = from_dict(Color | None, "red")
        assert_that(result).is_equal_to(Color.RED)

    def test_optional_enum_with_none(self):
        assert_that(from_dict(Color | None, None)).is_none()


# ---------------------------------------------------------------------------
# list[T]
# ---------------------------------------------------------------------------


class TestList:
    def test_list_of_str(self):
        assert_that(from_dict(list[str], ["a", "b"])).is_equal_to(["a", "b"])

    def test_list_of_int_coerced(self):
        assert_that(from_dict(list[int], ["1", "2", "3"])).is_equal_to([1, 2, 3])

    def test_list_no_type_arg(self):
        assert_that(from_dict(list, [1, 2])).is_equal_to([1, 2])

    def test_empty_list(self):
        assert_that(from_dict(list[str], [])).is_empty()

    def test_list_of_enum(self):
        result = from_dict(list[Color], ["red", "blue"])
        assert_that(result).is_equal_to([Color.RED, Color.BLUE])


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


class TestDataclass:
    def test_from_dict(self):
        result = from_dict(Inner, {"x": 3, "label": "hi"})
        assert_that(result).is_instance_of(Inner)
        assert_that(result.x).is_equal_to(3)
        assert_that(result.label).is_equal_to("hi")

    def test_passthrough_when_already_correct_type(self):
        obj = Inner(x=1)
        assert_that(from_dict(Inner, obj)).is_same_as(obj)

    def test_ignores_extra_keys(self):
        result = from_dict(Inner, {"x": 1, "label": "ok", "extra": "ignored"})
        assert_that(result.x).is_equal_to(1)

    def test_nested_dataclass(self):
        data = {
            "name": "test",
            "count": 2,
            "color": "red",
            "inner": {"x": 9, "label": None},
            "tags": ["a", "b"],
        }
        result = from_dict(Outer, data)
        assert_that(result.name).is_equal_to("test")
        assert_that(result.color).is_equal_to(Color.RED)
        assert_that(result.inner).is_instance_of(Inner)
        assert_that(result.inner.x).is_equal_to(9)
        assert_that(result.tags).is_equal_to(["a", "b"])

    def test_optional_field_with_none(self):
        result = from_dict(Inner, {"x": 5, "label": None})
        assert_that(result.label).is_none()

    def test_from_same_type_passthrough(self):
        src = Inner(x=7, label="src")
        result = from_dict(Inner, src)
        assert_that(result).is_same_as(src)

    def test_optional_fields_on_dataclass(self):
        result = from_dict(WithOptional, {"value": "hello", "code": None})
        assert_that(result.value).is_equal_to("hello")
        assert_that(result.code).is_none()

    def test_optional_field_coerced_from_string(self):
        result = from_dict(WithOptional, {"value": None, "code": "42"})
        assert_that(result.code).is_equal_to(42)
