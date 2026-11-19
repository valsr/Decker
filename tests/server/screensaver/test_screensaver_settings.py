import json
from dataclasses import replace

import pytest
from assertpy import assert_that

from decker.common.model import ScreensaverSettings
from decker.server.screensaver.settings import (
    settings_from_json,
    settings_to_json,
    validate,
)


def test_defaults_match_spec():
    s = ScreensaverSettings()

    assert_that((s.brightness, s.timeout_minutes, s.saver_brightness)).is_equal_to((100, 0, 10))
    assert_that((s.content, s.image_path, s.folder_path, s.scaling)).is_equal_to(("none", "", "", "center"))
    assert_that((s.bezel, s.key_mm, s.gap_mm)).is_equal_to((False, 16.0, 4.0))
    assert_that((s.gallery_mode, s.gallery_minutes)).is_equal_to(("activation", 5))


_RANGES = [
    ("brightness", 1, 100),
    ("timeout_minutes", 0, 1440),
    ("saver_brightness", 0, 100),
    ("key_mm", 5, 60),
    ("gap_mm", 0, 30),
    ("gallery_minutes", 1, 1440),
]


@pytest.mark.parametrize("name,low,high", _RANGES)
def test_rejects_out_of_range(name, low, high):
    validate(replace(ScreensaverSettings(), **{name: low}))
    validate(replace(ScreensaverSettings(), **{name: high}))
    for bad in (low - 1, high + 1):
        with pytest.raises(ValueError, match=name):
            settings_from_json(json.dumps({name: bad}))
        with pytest.raises(ValueError, match=name):
            validate(replace(ScreensaverSettings(), **{name: bad}))


def test_rejects_unknown_key_and_wrong_type():
    with pytest.raises(ValueError, match="bogus"):
        settings_from_json('{"bogus": 1}')
    with pytest.raises(ValueError, match="brightness"):
        settings_from_json('{"brightness": true}')
    with pytest.raises(ValueError, match="brightness"):
        settings_from_json('{"brightness": 50.5}')
    with pytest.raises(ValueError, match="content"):
        settings_from_json('{"content": "video"}')
    with pytest.raises(ValueError, match="bezel"):
        settings_from_json('{"bezel": 1}')
    with pytest.raises(ValueError, match="image_path"):
        settings_from_json('{"image_path": "x' + "a" * 1024 + '"}')
    with pytest.raises(ValueError):
        settings_from_json("[1]")
    with pytest.raises(ValueError):
        settings_from_json("{")


def test_ints_accepted_for_float_fields():
    assert_that(settings_from_json('{"key_mm": 20, "gap_mm": 0}').key_mm).is_equal_to(20)


def test_json_round_trip():
    s = ScreensaverSettings(brightness=40, content="gallery", folder_path="/p", bezel=True, key_mm=18.5)

    assert_that(settings_from_json(settings_to_json(s))).is_equal_to(s)
