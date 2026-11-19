import pytest
from assertpy import assert_that

from tests.conftest import marker_reason

_DEFAULT = "default reason"


def _marker(*args: object, **kwargs: object) -> pytest.Mark:
    return pytest.Mark("posix_only", args, kwargs, _ispytest=True)


def test_reason_given_positionally() -> None:
    assert_that(marker_reason(_marker("positional"), _DEFAULT)).is_equal_to("positional")


def test_reason_given_as_keyword() -> None:
    assert_that(marker_reason(_marker(reason="keyword"), _DEFAULT)).is_equal_to("keyword")


def test_default_reason_without_a_marker_or_reason() -> None:
    assert_that(marker_reason(None, _DEFAULT)).is_equal_to(_DEFAULT)
    assert_that(marker_reason(_marker(), _DEFAULT)).is_equal_to(_DEFAULT)
