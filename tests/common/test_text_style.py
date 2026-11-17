from typing import Any

from assertpy import assert_that

from decker.common.text_style import TEXT_STYLE_DEFAULTS, fold_legacy_title, normalize_text_style


def test_normalize_fills_defaults() -> None:
    assert_that(normalize_text_style({})).is_equal_to(dict(TEXT_STYLE_DEFAULTS))


def test_normalize_invalid_fields_fall_back_individually() -> None:
    value = {"size": "abc", "position": "left", "color": "red", "bold": "yes", "text": "Hi"}
    assert_that(normalize_text_style(value)).is_equal_to({**TEXT_STYLE_DEFAULTS, "text": "Hi"})


def test_normalize_non_dict_gives_defaults() -> None:
    assert_that(normalize_text_style("nope")).is_equal_to(dict(TEXT_STYLE_DEFAULTS))
    assert_that(normalize_text_style(None)).is_equal_to(dict(TEXT_STYLE_DEFAULTS))


def test_normalize_drops_unknown_keys() -> None:
    assert_that(normalize_text_style({"bogus": 1, "bold": True})).does_not_contain_key("bogus")


def test_normalize_empty_outline_is_none() -> None:
    assert_that(normalize_text_style({"outline": ""})["outline"]).is_none()
    assert_that(normalize_text_style({"outline": "#112233"})["outline"]).is_equal_to("#112233")


def test_normalize_out_of_range_falls_back() -> None:
    assert_that(normalize_text_style({"size": 99})["size"]).is_equal_to(12)
    assert_that(normalize_text_style({"outline_width": 0})["outline_width"]).is_equal_to(1)


def test_normalize_rejects_bool_as_number() -> None:
    assert_that(normalize_text_style({"size": True})["size"]).is_equal_to(12)


def test_normalize_uses_given_defaults() -> None:
    defaults = {**TEXT_STYLE_DEFAULTS, "position": "top"}
    assert_that(normalize_text_style({"position": "left"}, defaults)["position"]).is_equal_to("top")


def test_normalize_returns_fresh_dict() -> None:
    before = dict(TEXT_STYLE_DEFAULTS)
    result = normalize_text_style({})
    result["text"] = "changed"
    assert_that(dict(TEXT_STYLE_DEFAULTS)).is_equal_to(before)


def test_fold_maps_every_legacy_key() -> None:
    legacy: dict[str, Any] = {
        "title": "Hi",
        "show_title": False,
        "title_position": "top",
        "title_font": "Serif",
        "title_size": 20,
        "title_color": "#112233",
        "title_outline": "#445566",
        "title_outline_width": 3,
    }
    assert_that(fold_legacy_title(legacy)).is_equal_to(
        {
            "title": {
                "text": "Hi",
                "visible": False,
                "position": "top",
                "font": "Serif",
                "size": 20,
                "color": "#112233",
                "outline": "#445566",
                "outline_width": 3,
            }
        }
    )


def test_fold_nested_wins_over_legacy() -> None:
    assert_that(fold_legacy_title({"title": {"size": 20}, "title_size": 9})["title"]).is_equal_to({"size": 20})


def test_fold_without_title_data_adds_no_title() -> None:
    assert_that(fold_legacy_title({"background": "#000000"})).is_equal_to({"background": "#000000"})


def test_fold_keeps_unrelated_keys() -> None:
    result = fold_legacy_title({"background": "#ff0000", "title_size": 9})
    assert_that(result).is_equal_to({"background": "#ff0000", "title": {"size": 9}})
