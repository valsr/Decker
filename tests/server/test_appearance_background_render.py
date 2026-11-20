import io
import logging

import pytest
from assertpy import assert_that
from PIL import Image

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
