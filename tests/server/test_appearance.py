import io
from typing import Any

import cairosvg  # type: ignore[import-untyped]
import pytest
from assertpy import assert_that
from PIL import Image

from decker.plugin.manifest import ManifestValidationError, PluginManifest
from decker.server.appearance import compose_key_image, resolve_appearance


def _png(color: str, size: int = 72) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (size, size), color).save(buf, format="PNG")
    return buf.getvalue()


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def _appearance(**overrides: Any) -> dict[str, Any]:
    return resolve_appearance({}, overrides)


def test_defaults_from_schema() -> None:
    result = resolve_appearance({}, {})
    assert_that(result).is_equal_to(
        {
            "background": "#000000",
            "show_title": True,
            "title": "",
            "title_position": "bottom",
            "title_font": "DejaVu Sans",
            "title_size": 12,
            "title_color": "#ffffff",
            "title_outline": None,
            "title_outline_width": 1,
        }
    )


def test_action_defaults_override_schema_defaults() -> None:
    assert_that(resolve_appearance({"background": "#112233"}, {})["background"]).is_equal_to("#112233")


def test_stored_overrides_action_defaults() -> None:
    result = resolve_appearance({"background": "#112233"}, {"background": "#445566"})
    assert_that(result["background"]).is_equal_to("#445566")


def test_background_fills_key() -> None:
    img = _open(compose_key_image(_appearance(background="#112233"), None, ""))
    assert_that(img.size).is_equal_to((144, 144))
    assert_that(img.getpixel((0, 0))).is_equal_to((0x11, 0x22, 0x33))


def test_plugin_image_drawn_over_background() -> None:
    img = _open(compose_key_image(_appearance(background="#0000ff"), _png("#ff0000"), ""))
    assert_that(img.getpixel((72, 72))).is_equal_to((255, 0, 0))


def test_transparent_plugin_image_shows_background() -> None:
    img = _open(compose_key_image(_appearance(background="#0000ff"), _png("#ff000000"), ""))
    assert_that(img.getpixel((72, 72))).is_equal_to((0, 0, 255))


def _has_title_pixels(img: Image.Image) -> bool:
    return any(img.getpixel((x, y)) != (0, 0, 0) for x in range(144) for y in range(100, 144))


def test_user_title_beats_plugin_title() -> None:
    with_user = compose_key_image(_appearance(title="User"), None, "Plugin")
    user_only = compose_key_image(_appearance(title="User"), None, "")
    assert_that(with_user).is_equal_to(user_only)
    assert_that(_has_title_pixels(_open(with_user))).is_true()


def test_plugin_title_used_when_no_user_title() -> None:
    img = _open(compose_key_image(_appearance(), None, "Plugin"))
    assert_that(_has_title_pixels(img)).is_true()
    assert_that(compose_key_image(_appearance(), None, "Plugin")).is_not_equal_to(
        compose_key_image(_appearance(), None, "")
    )


def test_show_title_false_hides_title() -> None:
    img = _open(compose_key_image(_appearance(show_title=False, title="X"), None, "Plugin"))
    assert_that(_has_title_pixels(img)).is_false()


def test_title_outline_drawn() -> None:
    plain = compose_key_image(_appearance(title="X"), None, "")
    outlined = compose_key_image(_appearance(title="X", title_outline="#ff0000"), None, "")
    assert_that(plain).is_not_equal_to(outlined)


def test_svg_plugin_image_supported() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="72" height="72"><rect width="72" height="72" fill="#00ff00"/></svg>'
    assert_that(cairosvg).is_not_none()
    img = _open(compose_key_image(_appearance(), svg, ""))
    assert_that(img.getpixel((72, 72))).is_equal_to((0, 255, 0))


def test_undecodable_plugin_image_skipped() -> None:
    img = _open(compose_key_image(_appearance(background="#112233"), b"garbage", ""))
    assert_that(img.getpixel((72, 72))).is_equal_to((0x11, 0x22, 0x33))


def test_unknown_appearance_key_in_manifest_rejected() -> None:
    data = {
        "format": 1,
        "id": "com.example.p",
        "name": "P",
        "version": "1.0.0",
        "author": "A",
        "description": "d",
        "decker": ">=0.2",
        "runtime": {"type": "python", "entry": "plugin.py", "python": ">=3.12", "requirements": []},
        "contributes": {"actions": [{"id": "com.example.p.a", "name": "A", "appearance": {"background": "#112233"}}]},
    }
    assert_that(PluginManifest.from_dict(data).actions[0].appearance).is_equal_to({"background": "#112233"})
    data["contributes"]["actions"][0]["appearance"] = {"bogus": 1}  # type: ignore[index]
    with pytest.raises(ManifestValidationError, match="com.example.p.a.*bogus"):
        PluginManifest.from_dict(data)
