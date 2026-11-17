import io
from typing import Any

import cairosvg  # type: ignore[import-untyped]
import pytest
from assertpy import assert_that
from PIL import Image

from decker.common.text_style import TEXT_STYLE_DEFAULTS
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
    assert_that(result).is_equal_to({"background": "#000000", "title": dict(TEXT_STYLE_DEFAULTS)})


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


def test_legacy_show_title_false_hides_title() -> None:
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


def test_truncated_png_plugin_image_skipped() -> None:
    truncated = _png("#ff0000", 256)[:60]
    img = _open(compose_key_image(_appearance(background="#112233"), truncated, ""))
    assert_that(img.getpixel((72, 72))).is_equal_to((0x11, 0x22, 0x33))


def test_renderer_failure_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("cairo failure")

    monkeypatch.setattr("decker.server.appearance._RENDERER.render_bytes", boom)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"/>'
    img = _open(compose_key_image(_appearance(background="#112233"), svg, ""))
    assert_that(img.getpixel((72, 72))).is_equal_to((0x11, 0x22, 0x33))


def test_legacy_flat_keys_fold_into_title() -> None:
    title = resolve_appearance({}, {"title": "Hi", "title_position": "top", "show_title": False})["title"]
    assert_that(title).is_equal_to({**TEXT_STYLE_DEFAULTS, "text": "Hi", "position": "top", "visible": False})


def test_nested_title_wins_over_legacy() -> None:
    stored = {"title": {"size": 20}, "title_size": 9}
    assert_that(resolve_appearance({}, stored)["title"]["size"]).is_equal_to(20)


def test_stored_title_merges_field_wise_over_action_defaults() -> None:
    title = resolve_appearance({"title_position": "top", "title_size": 20}, {"title": {"size": 30}})["title"]
    assert_that(title["position"]).is_equal_to("top")
    assert_that(title["size"]).is_equal_to(30)


def test_legacy_keys_removed_from_resolved_appearance() -> None:
    result = resolve_appearance({}, {"title_size": 9, "show_title": True})
    assert_that(result).contains_only("background", "title")


def test_manifest_default_legacy_keys_still_accepted() -> None:
    data = _manifest_data({"title_position": "top", "show_title": False})
    assert_that(PluginManifest.from_dict(data).actions[0].appearance).is_equal_to(
        {"title_position": "top", "show_title": False}
    )


def test_manifest_default_nested_title_accepted() -> None:
    data = _manifest_data({"title": {"position": "top"}})
    assert_that(PluginManifest.from_dict(data).actions[0].appearance).is_equal_to({"title": {"position": "top"}})


def test_visible_false_hides_plugin_title() -> None:
    img = _open(compose_key_image(_appearance(title={"visible": False}), None, "Plugin"))
    assert_that(_has_title_pixels(img)).is_false()


def test_empty_text_without_plugin_title_draws_nothing() -> None:
    img = _open(compose_key_image(_appearance(), None, ""))
    assert_that(_has_title_pixels(img)).is_false()


def test_long_unicode_text_does_not_crash() -> None:
    data = compose_key_image(_appearance(title={"text": "W" * 200 + "🙂"}), None, "")
    assert_that(_open(data).size).is_equal_to((144, 144))


def test_unavailable_font_falls_back() -> None:
    img = _open(compose_key_image(_appearance(title={"text": "X", "font": "No Such Family 123"}), None, ""))
    assert_that(_has_title_pixels(img)).is_true()


def _manifest_data(appearance: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": 1,
        "id": "com.example.p",
        "name": "P",
        "version": "1.0.0",
        "author": "A",
        "description": "d",
        "decker": ">=0.2",
        "runtime": {"type": "python", "entry": "plugin.py", "python": ">=3.12", "requirements": []},
        "contributes": {"actions": [{"id": "com.example.p.a", "name": "A", "appearance": appearance}]},
    }


def _brightest(img: Image.Image) -> int:
    return max(max(img.getpixel((x, y))) for x in range(144) for y in range(144))


def test_text_color_alpha_blends_with_background() -> None:
    solid = _open(compose_key_image(_appearance(title={"text": "WWWW", "position": "middle", "size": 40}), None, ""))
    half = _open(
        compose_key_image(
            _appearance(title={"text": "WWWW", "position": "middle", "size": 40, "color": "#ffffff80"}), None, ""
        )
    )
    assert_that(_brightest(solid)).is_equal_to(255)
    assert_that(_brightest(half)).is_between(100, 160)


def test_outline_alpha_blends_with_background() -> None:
    style = {"text": "WWWW", "position": "middle", "size": 40, "color": "#00000000", "outline_width": 3}
    solid = _open(compose_key_image(_appearance(title={**style, "outline": "#ff0000"}), None, ""))
    half = _open(compose_key_image(_appearance(title={**style, "outline": "#ff000080"}), None, ""))
    assert_that(_brightest(solid)).is_equal_to(255)
    assert_that(_brightest(half)).is_between(100, 160)
