from typing import Any

import pytest
from assertpy import assert_that

from decker.common.background import BACKGROUND_DEFAULT, normalize_background

_DEFAULT = {"type": "color", "color": "#000000", "image": {"ref": ""}}


def test_default_shape() -> None:
    assert_that(dict(BACKGROUND_DEFAULT)).is_equal_to(_DEFAULT)
    assert_that(normalize_background(None)).is_equal_to(_DEFAULT)


def test_legacy_color_string_folds() -> None:
    assert_that(normalize_background("#112233")).is_equal_to({**_DEFAULT, "color": "#112233"})


def test_legacy_rgba_string_folds() -> None:
    assert_that(normalize_background("#11223380")).is_equal_to({**_DEFAULT, "color": "#11223380"})


def test_partial_dict_fills_defaults() -> None:
    defaults = {"type": "none", "color": "#abcdef", "image": {"ref": ""}}
    assert_that(normalize_background({"type": "image"}, defaults)).is_equal_to({**defaults, "type": "image"})
    assert_that(normalize_background({"color": "#010203"})).is_equal_to({**_DEFAULT, "color": "#010203"})


@pytest.mark.parametrize("value", [None, 5, [], "red", {"type": "video"}, {"color": 5}, {"image": 7}])
def test_junk_values_yield_defaults(value: Any) -> None:
    assert_that(normalize_background(value)).is_equal_to(_DEFAULT)


def test_image_ref_validated() -> None:
    assert_that(normalize_background({"image": {"ref": "nonsense"}})["image"]).is_equal_to({"ref": ""})
    result = normalize_background({"type": "image", "image": {"ref": "pack:a.b/x.png", "color": "#ff0000"}})
    assert_that(result["image"]).is_equal_to({"ref": "pack:a.b/x.png", "color": "#ff0000"})


def test_image_fill_colour_is_kept_only_when_valid():
    from decker.common.background import (
        normalize_background,  # pylint: disable=import-outside-toplevel
    )

    kept = normalize_background({"type": "image", "image": {"ref": "pack:p/a.svg", "color": "#112233"}})
    dropped = normalize_background({"type": "image", "image": {"ref": "pack:p/a.svg", "color": "nope"}})

    assert kept["image"] == {"ref": "pack:p/a.svg", "color": "#112233"}
    assert dropped["image"] == {"ref": "pack:p/a.svg"}
