import io

from assertpy import assert_that
from PIL import Image

from decker.common.appearance_schema import APPEARANCE_SCHEMA
from decker.server.appearance import compose_key_image, resolve_appearance


def _color(value: str) -> dict:
    return {"type": "color", "color": value, "image": {"ref": ""}}


def test_schema_entry() -> None:
    entry = next(e for e in APPEARANCE_SCHEMA if e["key"] == "background")
    assert_that(entry).is_equal_to({"key": "background", "type": "background", "label": "Background"})


def test_resolve_appearance_folds_legacy_stored_and_manifest_defaults() -> None:
    assert_that(resolve_appearance({}, {})["background"]).is_equal_to(_color("#000000"))
    assert_that(resolve_appearance({"background": "#112233"}, {})["background"]).is_equal_to(_color("#112233"))
    assert_that(resolve_appearance({"background": "#112233"}, {"background": "#445566"})["background"]).is_equal_to(
        _color("#445566")
    )
    merged = resolve_appearance({"background": "#112233"}, {"background": {"type": "none"}})["background"]
    assert_that(merged).is_equal_to({**_color("#112233"), "type": "none"})


def test_legacy_stored_backgrounds_render_as_before() -> None:
    for legacy in ("#112233", "#11223380"):
        appearance = resolve_appearance({}, {"background": legacy, "title": {"visible": False}})
        got = Image.open(io.BytesIO(compose_key_image(appearance, None, "", size=72))).convert("RGB")
        expected = Image.new("RGBA", (72, 72), (0, 0, 0, 255))
        expected.alpha_composite(Image.new("RGBA", (72, 72), legacy))
        assert_that(got.tobytes()).is_equal_to(expected.convert("RGB").tobytes())
