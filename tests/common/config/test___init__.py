import datetime
import os
from typing import Any, Literal

import pytest
from assertpy import assert_that

from decker.common.config import (
    USER_CONFIG_FILE,
    Config,
    ConfigurationKeyExists,
    InvalidConfigurationValue,
    decode_value,
    find,
    get_as,
    get_as_or_default,
    get_config_path,
    items,
)
from decker.common.config import set as set_config
from decker.common.config import (
    to_type,
    unset,
    value_type_to_bool,
    value_type_to_bytes,
    value_type_to_complex,
    value_type_to_datetime,
    value_type_to_float,
    value_type_to_int,
    value_type_to_list,
    value_type_to_string,
)
from decker.common.config.backend import BackendManager


class DummyBackend(BackendManager):
    """A dummy backend for testing purposes.

    This class simulates loading from and saving to a backend storage.
    """

    def __init__(self, data: dict[str, Any] | None = None):  # pylint: disable=super-init-not-called
        self.data = data or {}

    def load(self) -> dict[str, Any]:
        return self.data

    def save(self, settings: dict[str, Any]) -> None:
        self.data = settings


class TestConfigLoadSave:

    def test_load(self):
        # Arrange
        backend = DummyBackend({"FOO": "bar", "nested": {"key": "value"}})
        sut = Config(backend)

        # Act
        sut.load()

        # Assert
        expected_flat = {"FOO": "bar", "nested.key": "value"}
        assert_that(sut._data).is_equal_to(expected_flat)  # pyright: ignore[reportPrivateUsage]

    def test_save(self):
        # Arrange
        backend = DummyBackend()
        sut = Config(backend)

        # Act
        sut.set("FOO", "bar")
        sut.set("nested.key", "value")
        sut.save()

        # Assert
        expected_unflattened = {"FOO": "bar", "nested": {"key": "value"}}
        assert_that(backend.data).is_equal_to(expected_unflattened)


class TestConfigHas:
    def test_has_with_existing_key(self):
        # Arrange
        sut = Config(DummyBackend({"foo": "bar"}))
        sut.load()

        # Act & Arrange
        assert_that(sut.has("foo")).is_true()

    @pytest.mark.parametrize("key", ["Foo", "baz"])
    def test_has_with_non_existing_key(self, key: str):
        # Arrange
        sut = Config(DummyBackend({"foo": "bar"}))
        sut.load()

        # Act & Arrange
        assert_that(sut.has(key)).is_false()


class TestConfigGet:
    def test_get_with_existing_key(self):
        # Arrange
        sut = Config(DummyBackend({"foo": "bar"}))
        sut.load()

        # Act & Assert
        assert_that(sut.get("foo")).is_equal_to("bar")

    def test_get_with_nonexistent_key_raises_key_error(self):
        # Arrange
        sut = Config(DummyBackend())

        # Act
        assert_that(sut.get).raises(KeyError).when_called_with("nonexistent.key")

    def test_get_with_accessor(self):
        # Arrange
        sut = Config(DummyBackend({"foo": "bar"}))
        sut.load()

        # Act & Assert
        assert_that(sut["foo"]).is_equal_to("bar")


class TestConfigSet:
    def test_set_valid_value(self):
        # Arrange
        sut = Config(DummyBackend())

        # Act
        sut.set("Test.Key", "value")

        # Assert
        assert_that(sut.get("Test.Key")).is_equal_to("value")

    def test_set_using_accessor(self):
        # Arrange
        sut = Config(DummyBackend())

        # Act
        sut["Test.Key"] = "value"

        # Assert
        assert_that(sut.get("Test.Key")).is_equal_to("value")

    def test_set_calls_backend_save(self):
        # Arrange
        backend = DummyBackend()
        sut = Config(backend)

        # Act
        sut.set("Test.Key", "value")

        # Assert
        assert_that(backend.data).is_equal_to({"Test": {"Key": "value"}})

    def test_set_invalid_value_raises_exception(self):
        # Arrange
        sut = Config(DummyBackend())

        # Act & Assert
        assert_that(sut.set).raises(InvalidConfigurationValue).when_called_with("Test.Key", {"not": "allowed"})

    def test_set_beyond_end_node_raises_exception(self):
        # Arrange
        sut = Config(DummyBackend())
        sut.set("test", "parent_value")

        # Act & Assert
        assert_that(sut.set).raises(ConfigurationKeyExists).when_called_with("test.key", "value")


class TestConfigUnset:
    def test_unset_existing_keys(self):
        # Arrange
        backend = DummyBackend()
        sut = Config(backend)
        sut["test.key"] = "value"
        sut["test.other"] = "value2"
        sut["another"] = "val"

        # Act
        sut.unset("test")

        # Assert
        remaining_keys = list(
            sut._data.keys()
        )  # pyright: ignore[reportPrivateUsage] # pylint: disable=protected-access
        assert_that(remaining_keys).contains_only("another")
        assert_that(backend.data).is_equal_to({"another": "val"})

    def test_unset_nonexistent_key(self):
        # Arrange
        backend = DummyBackend()
        sut = Config(backend)
        sut["key"] = "value"

        # Act
        sut.unset("nonexistent")

        # Assert
        assert_that(sut._data).is_equal_to(
            {"key": "value"}
        )  # pyright: ignore[reportPrivateUsage] # pylint: disable=protected-access
        assert_that(backend.data).is_equal_to({"key": "value"})


class TestConfigList:

    def test_list_all_entries(self):
        # Arrange
        sut = Config(DummyBackend())
        sut["a"] = 1
        sut["b.c"] = 2
        sut["d"] = 3

        # Act
        result = sut.list()

        # Assert
        assert_that(result).is_equal_to([("a", 1), ("b.c", 2), ("d", 3)])

    def test_list_filtered_entries(self):
        # Arrange
        sut = Config(DummyBackend())
        sut["a.b.c"] = 2
        sut["a.b.d"] = 3
        sut["e"] = 4

        # Act
        result = sut.list("a.b")

        # Assert
        assert_that(result).is_equal_to([("a.b.c", 2), ("a.b.d", 3)])


class TesConfigFind:
    def test_find_with_callback(self):
        # Arrange
        sut = Config(DummyBackend())
        sut["alpha"] = 1
        sut["beta"] = 2
        sut["gamma"] = 3

        # Act
        result = list(sut.find(lambda _, v: isinstance(v, int) and v % 2 == 0))

        # Assert
        assert_that(result).is_equal_to([("beta", 2)])

    def test_find_with_non_callable_raises_exception(self):
        # Arrange
        sut = Config(DummyBackend())

        # Act & Assert
        assert_that(sut.find).raises(TypeError).when_called_with("not a callable")


class TestDecodeValue:
    def test_decode_bytes(self):
        # Arrange
        value = b"hello world"

        # Act
        result = decode_value(value)

        # Assert
        assert_that(result).is_equal_to("hello world")

    def test_decode_non_bytes_numeric(self):
        # Arrange
        value = 123

        # Act
        result = decode_value(value)

        # Assert
        assert_that(result).is_equal_to("123")

    def test_decode_non_bytes_string(self):
        # Arrange
        value = "already_string"

        # Act
        result = decode_value(value)

        # Assert
        assert_that(result).is_equal_to("already_string")


class TestGetAs:

    def test_get_as_string(self):
        # Arrange
        set_config("test.string", 123)

        # Act
        result = get_as("test.string", str)

        # Assert
        assert_that(result).is_instance_of(str)
        assert_that(result).is_equal_to("123")

    def test_get_as_int(self):
        # Arrange
        set_config("test.int", "42")

        # Act
        result = get_as("test.int", int)

        # Assert
        assert_that(result).is_instance_of(int)
        assert_that(result).is_equal_to(42)

    def test_get_as_float(self):
        # Arrange
        set_config("test.float", "3.14")

        # Act
        result = get_as("test.float", float)

        # Assert
        assert_that(result).is_instance_of(float)
        assert_that(result).is_equal_to(3.14)

    def test_get_as_bool(self):
        # Arrange
        set_config("test.bool", "true")

        # Act
        result = get_as("test.bool", bool)

        # Assert
        assert_that(result).is_instance_of(bool)
        assert_that(result).is_true()

    def test_get_as_list(self):
        # Arrange
        set_config("test.list", "a,b,c")

        # Act
        result: list[str] = get_as("test.list", list[str])

        # Assert
        assert_that(result).is_instance_of(list)
        assert_that(result).is_equal_to(["a", "b", "c"])

    def test_get_as_nonexistent_key_raises_key_error(self):
        # Arrange
        unset("nonexistent.key")

        # Act & Assert
        assert_that(get_as).raises(KeyError).when_called_with("nonexistent.key", int)

    def test_get_as_incompatible_type_raises_error(self):
        # Arrange
        set_config("test.incompatible", "not-a-number")

        # Act & Assert
        assert_that(get_as).raises(ValueError).when_called_with("test.incompatible", int)


class TestGetAsOrDefault:

    def test_get_as_or_default_existing_key(self):
        # Arrange
        set_config("test.convertible", "42")

        # Act
        result = get_as_or_default("test.convertible", int, 0)

        # Assert
        assert_that(result).is_instance_of(int)
        assert_that(result).is_equal_to(42)

    def test_get_as_or_default_nonexistent_key(self):
        # Arrange
        unset("nonexistent.key")

        # Act
        result = get_as_or_default("nonexistent.key", int, 99)

        # Assert
        assert_that(result).is_instance_of(int)
        assert_that(result).is_equal_to(99)

    def test_get_as_or_default_incompatible_type(self):
        # Arrange
        set_config("test.incompatible", "not-a-number")

        # Act
        result = get_as_or_default("test.incompatible", int, 88)

        # Assert
        assert_that(result).is_instance_of(int)
        assert_that(result).is_equal_to(88)


class TestValueTypeToString:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, ""),
            (b"hello world", "hello world"),
            (123, "123"),
            (3.14, "3.14"),
            (True, "True"),
            (False, "False"),
            ("test string", "test string"),
        ],
    )
    def test_values_converted_to_string(self, value: Any, expected: str):
        # Act
        result = value_type_to_string(value)

        # Assert
        assert_that(result).is_instance_of(str)
        assert_that(result).is_equal_to(expected)

    @pytest.mark.parametrize("value", [[1, 2, 3], {1, 2, 3}, frozenset([1, 2, 3])])
    def test_iterables_raise_type_error(self, value: list[int] | set[int] | frozenset[int]):
        # Act & Assert
        assert_that(value_type_to_string).raises(TypeError).when_called_with(value)


class TestValueTypeToBytes:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, b""),
            (b"hello world", b"hello world"),
            (123, b"123"),
            (3.14, b"3.14"),
            (True, b"True"),
            (False, b"False"),
            ("test string", b"test string"),
            ([104, 101, 108, 108, 111], b"hello"),
            ({65, 66, 67}, b"ABC"),
            (frozenset([97, 98, 99]), b"abc"),
        ],
    )
    def test_values_converted_to_bytes(self, value: Any, expected: bytes):
        result = value_type_to_bytes(value)

        # Assert
        assert_that(result).is_instance_of(bytes)
        assert_that(result).is_equal_to(expected)

    @pytest.mark.parametrize("value", [[256], [-1], {"not an int"}, frozenset([1, "boo", 3])])
    def test_invalid_iterables_raise_type_error(self, value: list[int] | set[int] | frozenset[int]):
        # Act & Assert
        assert_that(value_type_to_bytes).raises(TypeError).when_called_with(value)


class TestValueTypeToBool:
    def test_none_returns_false(self):
        result = value_type_to_bool(None)
        assert_that(result).is_false()

    def test_boolean_values_unchanged(self):
        assert_that(value_type_to_bool(True)).is_true()
        assert_that(value_type_to_bool(False)).is_false()

    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "yes", "Yes", "YES", "y", "Y", "1"])
    def test_truthy_strings_return_true(self, value: str):
        assert_that(value_type_to_bool(value)).is_true()

    @pytest.mark.parametrize("value", ["false", "False", "FALSE", "no", "No", "NO", "n", "N", "0"])
    def test_falsy_strings_return_false(self, value: str):
        assert_that(value_type_to_bool(value)).is_false()

    @pytest.mark.parametrize(
        "value", ["", " ", "  ", "  \t", " \n", " \t\n", " \t\n\r", "maybe", "not a boolean", "2", "-1"]
    )
    def test_invalid_strings_raise_value_error(self, value: str):
        assert_that(value_type_to_bool).raises(ValueError).when_called_with(value)

    @pytest.mark.parametrize("value,is_true", [(0, False), (42, True), (0.0, False), (3.14, True)])
    def test_numeric_values_follow_python_bool_rules(self, value: Any, is_true: bool):
        result = value_type_to_bool(value)
        if is_true:
            assert_that(result).is_true()
        else:
            assert_that(result).is_false()


class TestValueTypeToDatetime:
    def test_none_raises_value_error(self):
        assert_that(value_type_to_datetime).raises(ValueError).when_called_with(None).described_as("Value is None")

    def test_datetime_returned_unchanged(self):
        original_dt = datetime.datetime(2023, 5, 15, 10, 30, 45)
        result = value_type_to_datetime(original_dt)
        assert_that(result).is_equal_to(original_dt)

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2023-05-15T10:30:45", datetime.datetime(2023, 5, 15, 10, 30, 45)),
            ("2023-05-15 10:30:45", datetime.datetime(2023, 5, 15, 10, 30, 45)),
            ("2023-05-15", datetime.datetime(2023, 5, 15)),
        ],
    )
    def test_valid_iso_string_converts_to_datetime(self, value: str, expected: datetime.datetime):
        assert_that(value_type_to_datetime(value)).is_equal_to(expected)

    @pytest.mark.parametrize("value", ["2023/05/15", "05-15-2023", "10:30:45", "not a date"])
    def test_invalid_date_string_values_raises_value_error(self, value: str):
        assert_that(value_type_to_datetime).raises(ValueError).when_called_with(value)

    @pytest.mark.parametrize(
        "value",
        [42, 3.14, True, [2023, 5, 15], {"year": 2023, "month": 5, "day": 15}, (2023, 5, 15)],
    )
    def test_invalid_data_values_raises_type_error(
        self,
        value: float | list[int] | dict[str, int] | Literal[42] | Literal[True] | Literal[2023],
    ):
        assert_that(value_type_to_datetime).raises(TypeError).when_called_with(value)


class TestValueTypeToInt:
    def test_none_raises_value_error(self):
        assert_that(value_type_to_int).raises(ValueError).when_called_with(None).described_as("Value is None")

    def test_int_returned_unchanged(self):
        result = value_type_to_int(42)
        assert_that(result).is_instance_of(int)
        assert_that(result).is_equal_to(42)

    @pytest.mark.parametrize("value, expected", [(3.14, 3), (42.0, 42), (-1.5, -1)])
    def test_float_converted_to_int(self, value: float, expected: Literal[3] | Literal[42] | Literal[-1]):
        assert_that(value_type_to_int(value)).is_equal_to(expected)

    @pytest.mark.parametrize("value, expected", [("42", 42), ("10", 10), ("0", 0), ("+7", 7)])
    def test_valid_string_converted_to_int(
        self,
        value: Literal["42"] | Literal["10"] | Literal["0"] | Literal["+7"],
        expected: Literal[42] | Literal[10] | Literal[0] | Literal[7],
    ):
        assert_that(value_type_to_int(value)).is_equal_to(expected)

    @pytest.mark.parametrize("value", ["not a number", "42.5", "", "3.14"])
    def test_invalid_string_raises_value_error(
        self, value: Literal["not a number"] | Literal["42.5"] | Literal[""] | Literal["3.14"]
    ):
        assert_that(value_type_to_int).raises(ValueError).when_called_with(value)

    @pytest.mark.parametrize("value, expected", [(True, 1), (False, 0)])
    def test_boolean_converted_to_int(self, value: bool, expected: Literal[1] | Literal[0]):
        result = value_type_to_int(value)
        assert_that(result).is_instance_of(int)
        assert_that(result).is_equal_to(expected)

    @pytest.mark.parametrize(
        "value",
        [
            [1, 2, 3],
            {1, 2, 3},
            frozenset([1, 2, 3]),
            b"42",
            bytearray(b"42"),
            datetime.datetime.now(),
            (1, 2),
        ],
    )
    def test_other_types_raise_type_error(
        self,
        value: list[int] | set[int] | frozenset[int] | bytearray | datetime.datetime | Literal[b"42"] | Literal[1],
    ):
        assert_that(value_type_to_int).raises(TypeError).when_called_with(value).described_as(
            f"Cannot convert {type(value)} to int"
        )


class TestValueTypeToFloat:
    def test_none_raises_value_error(self):
        assert_that(value_type_to_float).raises(ValueError).when_called_with(None).described_as("Value is None")

    def test_float_returned_unchanged(self):
        result = value_type_to_float(3.14)
        assert_that(result).is_instance_of(float)
        assert_that(result).is_equal_to(3.14)

    @pytest.mark.parametrize("value, expected", [(42, 42.0), (-10, -10.0), (0, 0.0)])
    def test_int_converted_to_float(self, value: Literal[42] | Literal[-10] | Literal[0], expected: float):
        assert_that(value_type_to_float(value)).is_equal_to(expected)

    @pytest.mark.parametrize(
        "value, expected",
        [("42.5", 42.5), ("-10.5", -10.5), ("0.0", 0.0), ("+7.0", 7.0), ("3.14", 3.14), (".5", 0.5), ("5.", 5.0)],
    )
    def test_valid_string_converted_to_float(
        self,
        value: (
            Literal["42.5"]
            | Literal["-10.5"]
            | Literal["0.0"]
            | Literal["+7.0"]
            | Literal["3.14"]
            | Literal[".5"]
            | Literal["5."]
        ),
        expected: float,
    ):
        assert_that(value_type_to_float(value)).is_equal_to(expected)

    @pytest.mark.parametrize("value", ["not a number", "42.5.0", "", "3.14.15"])
    def test_invalid_string_raises_value_error(
        self,
        value: Literal["not a number"] | Literal["42.5.0"] | Literal[""] | Literal["3.14.15"],
    ):
        assert_that(value_type_to_float).raises(ValueError).when_called_with(value)

    @pytest.mark.parametrize(
        "value",
        [[1, 2, 3], {1, 2, 3}, frozenset([1, 2, 3]), b"3.14", bytearray(b"3.14"), datetime.datetime.now(), (1, 2)],
    )
    def test_other_types_raise_type_error(
        self,
        value: list[int] | set[int] | frozenset[int] | bytearray | datetime.datetime | Literal[b"3.14"] | Literal[1],
    ):
        assert_that(value_type_to_float).raises(TypeError).when_called_with(value).described_as(
            f"Cannot convert {type(value)} to float"
        )


class TestValueTypeToComplex:
    def test_none_raises_value_error(self):
        assert_that(value_type_to_complex).raises(ValueError).when_called_with(None).described_as("Value is None")

    def test_complex_returned_unchanged(self):
        result = value_type_to_complex(3 + 4j)
        assert_that(result).is_instance_of(complex)
        assert_that(result).is_equal_to(3 + 4j)

    @pytest.mark.parametrize("value, expected", [(42, complex(42, 0)), (-10, complex(-10, 0)), (0, complex(0, 0))])
    def test_int_converted_to_complex(self, value: Literal[42] | Literal[-10] | Literal[0], expected: complex):
        assert_that(value_type_to_complex(value)).is_equal_to(expected)

    @pytest.mark.parametrize(
        "value, expected", [(3.14, complex(3.14, 0)), (-10.5, complex(-10.5, 0)), (0.0, complex(0.0, 0))]
    )
    def test_float_converted_to_complex(self, value: float, expected: complex):
        assert_that(value_type_to_complex(value)).is_equal_to(expected)

    @pytest.mark.parametrize(
        "value, expected", [("3+4j", complex(3, 4)), ("-1-2j", complex(-1, -2)), ("5j", complex(0, 5))]
    )
    def test_valid_string_converted_to_complex(
        self, value: Literal["3+4j"] | Literal["-1-2j"] | Literal["5j"], expected: complex
    ):
        assert_that(value_type_to_complex(value)).is_equal_to(expected)

    def test_invalid_string_raise_type_error(self):
        assert_that(value_type_to_complex).raises(ValueError).when_called_with("not a number")

    @pytest.mark.parametrize(
        "value",
        [[1, 2, 3], {1, 2, 3}, frozenset([1, 2, 3]), b"3+4j", bytearray(b"3+4j"), datetime.datetime.now(), (1, 2)],
    )
    def test_other_types_raise_type_error(
        self,
        value: list[int] | set[int] | frozenset[int] | bytearray | datetime.datetime | Literal[b"3+4j"] | Literal[1],
    ):
        assert_that(value_type_to_complex).raises(TypeError).when_called_with(value).described_as(
            f"Cannot convert {type(value)} to complex"
        )


class TestValueTypeToList:
    def test_none_returns_empty_list(self):
        result = value_type_to_list(None)
        assert_that(result).is_instance_of(list)
        assert_that(result).is_equal_to([])

    @pytest.mark.parametrize("value", [[1, 2, 3], {1, 2, 3}, frozenset([1, 2, 3])])
    def test_list_types_returned_as_list(self, value: list[int] | set[int] | frozenset[int]):
        result = value_type_to_list(value)
        assert_that(result).is_instance_of(list)
        assert_that(result).is_equal_to([1, 2, 3])

    @pytest.mark.parametrize("value", ["a,b,c", "a, b, c", "a,  b,c"])
    def test_string_split_by_commas(self, value: Literal["a,b,c"] | Literal["a, b, c"] | Literal["a,  b,c"]):
        assert_that(value_type_to_list(value)).is_equal_to(["a", "b", "c"])

    @pytest.mark.parametrize("value", [b"1,2,3", bytearray(b"1,2,3")])
    def test_bytes_decoded_and_split(self, value: bytearray | Literal[b"1,2,3"]):
        assert_that(value_type_to_list(value)).is_equal_to(["1", "2", "3"])

    @pytest.mark.parametrize(
        "value, expected", [("1", ["1"]), (42, [42]), (3.14, [3.14]), (True, [True]), (3 + 4j, [3 + 4j])]
    )
    def test_single_items_converte_to_single_list(
        self,
        value: float | complex | Literal["1"] | Literal[42] | Literal[True],
        expected: list[str] | list[int] | list[float] | list[bool] | list[complex],
    ):
        assert_that(value_type_to_list(value)).is_equal_to(expected)


class TestToType:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, ""),
            ("a string", "a string"),
            (b"hello", "hello"),
            (123, "123"),
            (3.14, "3.14"),
            (3 + 4j, "(3+4j)"),
            (True, "True"),
        ],
    )
    def test_to_type_string_conversion(self, value: Any, expected: str):
        assert_that(to_type(value, str)).is_equal_to(expected)

    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, b""),
            ("a string", b"a string"),
            (b"hello", b"hello"),
            (123, b"123"),
            (3.14, b"3.14"),
            (3 + 4j, b"(3+4j)"),
            (True, b"True"),
        ],
    )
    def test_to_type_bytes_conversion(self, value: Any, expected: bytes):
        assert_that(to_type(value, bytes)).is_equal_to(expected)

    @pytest.mark.parametrize(
        "value, expected",
        [(1, 1), (3.14, 3), (True, 1), (False, 0), ("42", 42)],
    )
    def test_to_type_int_conversion(self, value: Any, expected: int):
        assert_that(to_type(value, int)).is_equal_to(expected)

    @pytest.mark.parametrize(
        "value, expected",
        [(1, 1.0), (3.14, 3.14), (True, 1.0), (False, 0.0), ("42", 42.0)],
    )
    def test_to_type_float_conversion(self, value: Any, expected: float):
        assert_that(to_type(value, float)).is_equal_to(expected)

    @pytest.mark.parametrize(
        "value, expected",
        [
            (1, (1 + 0j)),
            (3.14, (3.14 + 0j)),
            (True, (1 + 0j)),
            (False, (0 + 0j)),
            ("42", (42 + 0j)),
            ("42+5j", (42 + 5j)),
            ((3 + 5j), (3 + 5j)),
        ],
    )
    def test_to_type_complex_conversions(self, value: Any, expected: complex):
        assert_that(to_type(value, complex)).is_equal_to(expected)

    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, False),
            ("true", True),
            ("false", False),
            (1, True),
            (0, False),
            (True, True),
            (False, False),
        ],
    )
    def test_to_type_bool_conversion(self, value: Any, expected: bool):
        assert_that(to_type(value, bool)).is_equal_to(expected)

    @pytest.mark.parametrize(
        "value, expected",
        [
            ([1, 2, 3], [1, 2, 3]),
            ({1, 2, 3}, [1, 2, 3]),
            (frozenset([1, 2, 3]), [1, 2, 3]),
            ("1,2,3", [1, 2, 3]),
            (b"1,2,3", [1, 2, 3]),
        ],
    )
    def test_to_type_collection_conversions(self, value: Any, expected: Any):
        assert_that(to_type(value, type(expected))).is_equal_to(expected)

    def test_to_type_datetime_conversion(self):
        iso_str = "2023-05-15T10:30:45"
        result = to_type(iso_str, datetime.datetime)
        assert_that(result.year).is_equal_to(2023)
        assert_that(result.month).is_equal_to(5)
        assert_that(result.day).is_equal_to(15)
        assert_that(result.hour).is_equal_to(10)
        assert_that(result.minute).is_equal_to(30)
        assert_that(result.second).is_equal_to(45)

    def test_to_type_invalid_conversion_raises_value_error(self):
        assert_that(to_type).raises(ValueError).when_called_with(None, datetime.datetime)

    def test_to_type_invalid_type_conversion_raises_type_error(self):
        assert_that(to_type).raises(TypeError).when_called_with(1, "a type")


class TestItems:
    """Tests for validating the items function."""

    def test_items_all_entries(self):
        set_config("test.a", 1)
        set_config("test.b", 2)
        set_config("other", 3)
        result = items()
        assert_that(result).contains(("test.a", 1), ("test.b", 2), ("other", 3))

    def test_items_filtered_by_key(self):
        set_config("filter.a", 1)
        set_config("filter.b", 2)
        set_config("other", 3)
        result = items("filter")
        assert_that(result).contains(("filter.a", 1), ("filter.b", 2))
        assert_that(result).does_not_contain(("other", 3))

    def test_items_exact_key_match(self):
        set_config("exact", "value")
        set_config("exact.sub", "other")
        result = items("exact")
        assert_that(result).contains(("exact", "value"), ("exact.sub", "other"))


class TestFind:
    """Tests for validating the find function."""

    def test_find_by_value_predicate(self):
        set_config("num.even", 2)
        set_config("num.odd", 3)
        set_config("str.val", "test")
        result = list(find(lambda _, v: isinstance(v, int) and v % 2 == 0))
        assert_that(result).is_equal_to([("num.even", 2)])

    def test_find_by_key_pattern(self):
        set_config("user.name", "Alice")
        set_config("user.email", "alice@example.com")
        set_config("app.version", "1.0")
        result = list(find(lambda k, _: k.startswith("user.")))
        assert_that(result).contains(("user.name", "Alice"), ("user.email", "alice@example.com"))
        assert_that(result).does_not_contain(("app.version", "1.0"))

    def test_find_by_combined_predicate(self):
        set_config("setting.enabled", True)
        set_config("setting.disabled", False)
        set_config("other.enabled", True)
        result = list(find(lambda k, v: k.startswith("setting.") and v is True))
        assert_that(result).is_equal_to([("setting.enabled", True)])


class TestGetConfigPath:
    def test_get_config_path_returns_expanded_path(self):
        result = get_config_path()
        assert_that(result).is_equal_to(os.path.expanduser(USER_CONFIG_FILE))
        assert_that(result).ends_with(".decker")
