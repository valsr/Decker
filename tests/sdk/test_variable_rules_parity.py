from typing import Any

import pytest
from assertpy import assert_that

from decker.common.variables import match_pattern, value_text
from decker_plugin_sdk import _variables


def _outcome(fn: Any, *args: Any) -> Any:
    try:
        return ("ok", fn(*args))
    except ValueError:
        return ("error", None)


@pytest.mark.parametrize(
    "value",
    [None, True, False, 0, -3, 1.5, float("nan"), "", "x", "a" * 1024, "a" * 1025, [], {}],
    ids=repr,
)
def test_value_text_matches_the_server(value: Any) -> None:
    expected = _outcome(value_text, value)
    actual = _outcome(_variables.value_text, value)

    assert_that(repr(actual)).is_equal_to(repr(expected))


@pytest.mark.parametrize(
    ("pattern", "name"),
    [
        ("m_{a}_{b}_v", "m_x_y_v"),
        ("m_{a}_{b}_v", "m_x_v"),
        ("{a}_v", "x_v"),
        ("m_{a}", "m_x"),
        ("m_{a}", "n_x"),
        ("m_{a}_v", "m_1abc_v"),
        ("m_{a}_v", "m__v"),
        ("m_{a}_v", "m_X_v"),
    ],
)
def test_pattern_matching_matches_the_server(pattern: str, name: str) -> None:
    assert_that(_variables._match_pattern(pattern, name)).is_equal_to(  # pylint: disable=protected-access
        match_pattern(pattern, name)
    )
