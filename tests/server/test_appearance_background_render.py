import io
import logging
from typing import Any

import pytest
from assertpy import assert_that
from PIL import Image

from decker.server import appearance as appearance_module
from decker.server.appearance import (
    compose_key_face,
    compose_key_image,
    cover_fit,
    resolve_appearance,
)

SIZE = 72
RED = (255, 0, 0)
BLUE = (0, 0, 255)


def _appearance(kind: str, color: str = "#112233", title: bool = False) -> dict:
    return resolve_appearance(
        {}, {"background": {"type": kind, "color": color, "image": {"ref": ""}}, "title": {"visible": title}}
    )


def _png(image: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    return buf.getvalue()


def _render(appearance: dict, **kwargs) -> Image.Image:
    return Image.open(
        io.BytesIO(compose_key_image(appearance, kwargs.pop("icon", None), "", size=SIZE, **kwargs))
    ).convert("RGB")


def _wide() -> bytes:
    """200x100: left half red, right half blue."""
    img = Image.new("RGB", (200, 100), RED)
    img.paste(Image.new("RGB", (100, 100), BLUE), (100, 0))
    return _png(img)


def _gif(colors: list[tuple[int, int, int]]) -> bytes:
    frames = [Image.new("RGB", (16, 16), c) for c in colors]
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return buf.getvalue()


def test_none_mode_is_black() -> None:
    got = _render(_appearance("none"), background_image=_wide())
    assert_that(got.getpixel((0, 0))).is_equal_to((0, 0, 0))
    assert_that(got.getpixel((SIZE - 1, SIZE - 1))).is_equal_to((0, 0, 0))


def test_color_mode_matches_legacy_output_byte_for_byte() -> None:
    got = _render(_appearance("color", "#11223380"), background_image=_wide())
    expected = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 255))
    expected.alpha_composite(Image.new("RGBA", (SIZE, SIZE), "#11223380"))
    assert_that(got.tobytes()).is_equal_to(expected.convert("RGB").tobytes())


def test_image_mode_png_covers_and_crops() -> None:
    got = _render(_appearance("image"), background_image=_wide())
    assert_that(got.size).is_equal_to((SIZE, SIZE))
    # the centre crop of a 2:1 source keeps the middle half: red left, blue right, no black anywhere
    assert_that(got.getpixel((1, 1))).is_equal_to(RED)
    assert_that(got.getpixel((1, SIZE - 2))).is_equal_to(RED)
    assert_that(got.getpixel((SIZE - 2, 1))).is_equal_to(BLUE)
    assert_that(got.getpixel((SIZE - 2, SIZE - 2))).is_equal_to(BLUE)


def test_cover_fit_is_square_and_centred() -> None:
    tall = Image.new("RGB", (50, 200), RED)
    tall.paste(Image.new("RGB", (50, 100), BLUE), (0, 100))
    fitted = cover_fit(tall, 40)
    assert_that(fitted.size).is_equal_to((40, 40))
    assert_that(fitted.getpixel((20, 5))).is_equal_to(RED + (255,))
    assert_that(fitted.getpixel((20, 35))).is_equal_to(BLUE + (255,))


def test_transparent_png_shows_black() -> None:
    got = _render(_appearance("image"), background_image=_png(Image.new("RGBA", (30, 30), (255, 0, 0, 0))))
    assert_that(got.getpixel((SIZE // 2, SIZE // 2))).is_equal_to((0, 0, 0))


def test_svg_background_renders() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="#00ff00"/></svg>'
    got = _render(_appearance("image"), background_image=svg)
    assert_that(got.getpixel((3, 3))).is_equal_to((0, 255, 0))
    assert_that(got.getpixel((SIZE - 4, SIZE - 4))).is_equal_to((0, 255, 0))


def test_missing_or_corrupt_image_falls_back_to_black_with_icon_and_title_drawn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    icon = _png(Image.new("RGBA", (10, 10), (255, 255, 255, 255)))
    appearance = resolve_appearance({}, {"background": {"type": "image"}, "title": {"visible": True, "text": "Hi"}})
    with caplog.at_level(logging.DEBUG):
        for bad in (None, b"not an image"):
            got = Image.open(
                io.BytesIO(
                    compose_key_image(appearance, icon, "", size=SIZE, plugin_image_scale=0.5, background_image=bad)
                )
            )
            got = got.convert("RGB")  # type: ignore[assignment]
            assert_that(got.getpixel((0, 0))).is_equal_to((0, 0, 0))
            assert_that(got.getpixel((SIZE // 2, SIZE // 2))).is_equal_to((255, 255, 255))
            assert_that(got.getpixel((SIZE - 1, SIZE - 1))).is_equal_to((0, 0, 0))
        compose_key_image(appearance, icon, "", size=SIZE, background_image=b"not an image")
    assert_that([r for r in caplog.records if "background image" in r.getMessage()]).is_length(1)


def test_gif_background_first_frame_is_the_poster() -> None:
    face = compose_key_face(_appearance("image"), None, "", background_image=_gif([RED, BLUE]), poster=True)
    poster = Image.open(io.BytesIO(face.png)).convert("RGB")
    assert_that(poster.getpixel((5, 5))).is_equal_to(RED)


def test_static_foreground_over_animated_background_yields_background_animation() -> None:
    icon = _png(Image.new("RGBA", (10, 10), (255, 255, 255, 255)))
    gif = _gif([RED, BLUE])
    face = compose_key_face(_appearance("image"), icon, "T", "#ffffff", 0.7, background_image=gif)
    assert_that(face.animation).is_not_none()
    spec = face.animation
    assert spec is not None
    assert_that(spec.layer).is_equal_to("background")
    assert_that(spec.gif).is_equal_to(gif)
    assert_that(spec.overlay).is_equal_to(icon)
    assert_that(spec.overlay_color).is_equal_to("#ffffff")
    assert_that(spec.scale).is_equal_to(0.7)


def test_non_image_mode_or_static_background_yields_no_animation() -> None:
    assert_that(
        compose_key_face(_appearance("color"), None, "", background_image=_gif([RED, BLUE])).animation
    ).is_none()
    assert_that(compose_key_face(_appearance("image"), None, "", background_image=_wide()).animation).is_none()


def test_animated_foreground_wins_over_animated_background() -> None:
    fg = _gif([(0, 255, 0), (255, 255, 0)])
    face = compose_key_face(_appearance("image"), fg, "", image_scale=0.5, background_image=_gif([RED, BLUE]))
    assert face.animation is not None
    assert_that(face.animation.layer).is_equal_to("foreground")
    assert_that(face.animation.gif).is_equal_to(fg)
    poster = Image.open(io.BytesIO(face.png)).convert("RGB")
    assert_that(poster.getpixel((0, 0))).is_equal_to(RED)


@pytest.fixture(autouse=True)
def _clear_reported() -> None:
    appearance_module._REPORTED_BAD_BACKGROUNDS.clear()  # pylint: disable=protected-access


@pytest.fixture(autouse=True)
def _clear_layer_cache() -> None:
    appearance_module._LAYER_CACHE.clear()  # pylint: disable=protected-access


def _gif_bytes(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), RED).save(buf, format="GIF")
    return buf.getvalue()


@pytest.mark.parametrize(
    "data,source",
    [
        (lambda: _png(Image.new("RGB", (20000, 1), RED)), (20000, 1)),
        (lambda: _png(Image.new("RGB", (1, 20000), RED)), (1, 20000)),
        (lambda: _gif_bytes(65535, 1), (65535, 1)),
    ],
)
def test_extreme_aspect_ratio_images_are_cropped_before_any_resize(
    monkeypatch: pytest.MonkeyPatch, data, source: tuple[int, int]
) -> None:
    calls: list[tuple[tuple[int, int], tuple[int, int]]] = []
    original = Image.Image.resize

    def spy(self: Image.Image, size: tuple[int, int], *args, **kwargs) -> Image.Image:
        calls.append((self.size, (int(size[0]), int(size[1]))))
        return original(self, size, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "resize", spy)
    got = _render(_appearance("image"), background_image=data())
    side = min(source)
    assert_that(calls).is_not_empty()
    for input_size, output_size in calls:
        assert_that(input_size[0] * input_size[1]).is_less_than_or_equal_to(side * side)
        assert_that(output_size).is_equal_to((SIZE, SIZE))
    assert_that(got.getpixel((5, 5))).is_equal_to(RED)


def test_unparseable_svg_logs_once_and_falls_back_to_black(caplog: pytest.LogCaptureFixture) -> None:
    bad = b"<svg xmlns='http://www.w3.org/2000/svg'><unclosed"
    with caplog.at_level(logging.DEBUG):
        for _ in range(3):
            got = _render(_appearance("image"), background_image=bad)
    assert_that(got.getpixel((3, 3))).is_equal_to((0, 0, 0))
    assert_that([r for r in caplog.records if "background image" in r.getMessage()]).is_length(1)


def test_reported_backgrounds_are_bounded() -> None:
    for index in range(300):
        appearance_module._report_bad_background(str(index).encode(), "x")  # pylint: disable=protected-access
    assert_that(len(appearance_module._REPORTED_BAD_BACKGROUNDS)).is_equal_to(256)  # pylint: disable=protected-access


def _jpeg(image: Image.Image, orientation: int | None = None) -> bytes:
    buf = io.BytesIO()
    if orientation is None:
        image.save(buf, format="JPEG", quality=95)
    else:
        exif = Image.Exif()
        exif[0x0112] = orientation
        image.save(buf, format="JPEG", quality=95, exif=exif.tobytes())
    return buf.getvalue()


def _dominant(pixel: Any) -> str:
    return "red" if pixel[0] > 200 and pixel[2] < 60 else "blue" if pixel[2] > 200 and pixel[0] < 60 else "other"


def _left_red_right_blue(width: int = 40, height: int = 20) -> Image.Image:
    img = Image.new("RGB", (width, height), RED)
    img.paste(Image.new("RGB", (width // 2, height), BLUE), (width // 2, 0))
    return img


def test_jpeg_background_covers_and_crops() -> None:
    got = _render(_appearance("image"), background_image=_jpeg(_left_red_right_blue()))
    assert_that(_dominant(got.getpixel((5, SIZE // 2)))).is_equal_to("red")
    assert_that(_dominant(got.getpixel((SIZE - 6, SIZE // 2)))).is_equal_to("blue")


@pytest.mark.parametrize(
    "orientation,top,bottom,left,right",
    [
        (6, "red", "blue", None, None),  # stored sideways; shown turned 90 degrees clockwise
        (8, "blue", "red", None, None),  # turned 90 degrees counter-clockwise
        (3, None, None, "blue", "red"),  # upside down
        (2, None, None, "blue", "red"),  # mirrored
    ],
)
def test_exif_orientation_is_applied_to_jpeg_backgrounds(  # pylint: disable=too-many-arguments
    orientation: int, top: str | None, bottom: str | None, left: str | None, right: str | None
) -> None:
    got = _render(_appearance("image"), background_image=_jpeg(_left_red_right_blue(), orientation))
    middle = SIZE // 2
    if top is not None:
        assert_that(_dominant(got.getpixel((middle, 5)))).is_equal_to(top)
        assert_that(_dominant(got.getpixel((middle, SIZE - 6)))).is_equal_to(bottom)
    else:
        assert_that(_dominant(got.getpixel((5, middle)))).is_equal_to(left)
        assert_that(_dominant(got.getpixel((SIZE - 6, middle)))).is_equal_to(right)


def test_exif_orientation_is_applied_to_png_backgrounds() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    _left_red_right_blue().save(buf, format="PNG", exif=exif.tobytes())
    got = _render(_appearance("image"), background_image=buf.getvalue())
    assert_that(got.getpixel((SIZE // 2, 5))).is_equal_to(RED)
    assert_that(got.getpixel((SIZE // 2, SIZE - 6))).is_equal_to(BLUE)


def test_layer_cache_is_warmed_by_a_render() -> None:
    _render(_appearance("image"), background_image=_wide())
    assert_that(appearance_module._LAYER_CACHE).is_not_empty()  # pylint: disable=protected-access


def test_layer_cache_starts_empty_in_every_test() -> None:
    # Runs after the test above: a warm cache would skip the resize the spy test counts, so a rerun would fail.
    assert_that(appearance_module._LAYER_CACHE).is_empty()  # pylint: disable=protected-access
