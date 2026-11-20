import hashlib
import io
import json
from typing import Any

from assertpy import assert_that
from PIL import Image

from decker.animation import factory as factory_module
from decker.animation.gif import MAX_FRAME_SIZE
from decker.animation.model import AnimationSpec
from decker.server.appearance import (
    compose_key_face,
    compose_key_frames,
    resolve_appearance,
)

SIZE = 72
RED = (255, 0, 0)
BLUE = (0, 0, 255)


def _appearance(kind: str = "image", title: bool = False) -> dict:
    return resolve_appearance(
        {}, {"background": {"type": kind, "color": "#112233"}, "title": {"visible": title, "text": "Hi", "size": 20}}
    )


def _png_bytes(color: tuple[int, int, int, int]) -> bytes:

    buf = io.BytesIO()
    Image.new("RGBA", (10, 10), color).save(buf, format="PNG")
    return buf.getvalue()


def test_animation_id_changes_with_background_overlay_color_and_mode() -> None:
    def spec(**kw) -> AnimationSpec:
        base = {"gif": b"GIF89a-x", "appearance": _appearance(), "title": "", "scale": 1.0}
        return AnimationSpec(**{**base, **kw})

    foreground = spec()
    background = spec(layer="background")
    ids = {
        foreground.animation_id,
        background.animation_id,
        spec(layer="background", overlay=b"a").animation_id,
        spec(layer="background", overlay=b"b").animation_id,
        spec(layer="background", overlay=b"a", overlay_color="#ff0000").animation_id,
        spec(layer="background", overlay=b"a", overlay_color="#00ff00").animation_id,
        spec(gif=b"GIF89a-y", layer="background").animation_id,
    }
    assert_that(ids).is_length(7)


def test_foreground_spec_id_is_unchanged_by_the_new_fields() -> None:
    gif = b"GIF89a-x"
    appearance = _appearance()
    spec = AnimationSpec(gif, appearance, "t", 0.5)
    look = json.dumps([dict(appearance), "t", repr(0.5)], sort_keys=True, default=str)
    expected = hashlib.sha256(f"{hashlib.sha256(gif).hexdigest()}:{look}".encode()).hexdigest()
    assert_that(spec.animation_id).is_equal_to(expected)


def test_frames_composite_overlay_and_title_over_each_frame() -> None:
    frames = [Image.new("RGBA", (30, 30), RED + (255,)), Image.new("RGBA", (30, 30), BLUE + (255,))]
    overlay = _png_bytes((255, 255, 255, 255))
    out = compose_key_frames(
        _appearance(title=True), frames, "", SIZE, 0.5, layer="background", overlay=overlay, overlay_color=None
    )
    plain = compose_key_frames(
        _appearance(), frames, "", SIZE, 0.5, layer="background", overlay=overlay, overlay_color=None
    )
    assert_that(out).is_length(2)
    for with_title, without in zip(out, plain):
        assert_that(with_title.tobytes()).is_not_equal_to(without.tobytes())  # the title is drawn over the frame
    for frame, color in zip(out, (RED, BLUE)):
        assert_that(frame.size).is_equal_to((SIZE, SIZE))
        assert_that(frame.getpixel((1, SIZE // 2))).is_equal_to(color)  # background covers the whole key
        assert_that(frame.getpixel((SIZE // 2, SIZE // 2))).is_equal_to((255, 255, 255))  # overlay, centred


def test_background_frames_are_cover_fit_not_squashed() -> None:
    wide = Image.new("RGBA", (60, 30), RED + (255,))
    wide.paste(Image.new("RGBA", (15, 30), BLUE + (255,)), (45, 0))  # right quarter blue, cropped away
    out = compose_key_frames(_appearance(), [wide], "", SIZE, 1.0, layer="background")
    assert_that(out[0].getpixel((SIZE - 2, SIZE // 2))).is_equal_to(RED)


def test_compose_key_frames_foreground_layer_unchanged() -> None:
    frames = [Image.new("RGBA", (20, 20), RED + (255,))]
    appearance = _appearance("color")
    default = compose_key_frames(appearance, frames, "", SIZE, 0.5)
    explicit = compose_key_frames(appearance, frames, "", SIZE, 0.5, layer="foreground", overlay=b"ignored")
    assert_that(explicit[0].tobytes()).is_equal_to(default[0].tobytes())
    assert_that(default[0].getpixel((SIZE // 2, SIZE // 2))).is_equal_to(RED)
    assert_that(default[0].getpixel((2, 2))).is_equal_to((0x11, 0x22, 0x33))


def _striped_gif() -> bytes:
    """Two 288x144 frames with 1 px black/white vertical stripes in the centre square."""
    frames = []
    for shade in (255, 200):
        img = Image.new("RGB", (288, 144), (0, 0, 0))
        for x in range(0, 288, 2):
            img.paste((shade, shade, shade), (x, 0, x + 1, 144))
        frames.append(img)
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return buf.getvalue()


def test_background_layer_frames_are_square_and_sharp() -> None:
    spec = AnimationSpec(_striped_gif(), _appearance(), "", 1.0, layer="background")
    frames = factory_module._decode(spec)  # pylint: disable=protected-access
    assert_that(frames[0].image.size).is_equal_to((MAX_FRAME_SIZE, MAX_FRAME_SIZE))
    pixels = frames[0].image.load()
    assert pixels is not None
    row = [pixels[x, 70][0] for x in range(40, 100)]  # type: ignore[index]
    assert_that(max(row) - min(row)).is_greater_than(200)  # stripes survive instead of blurring to grey
    foreground = factory_module._decode(  # pylint: disable=protected-access
        AnimationSpec(spec.gif, _appearance(), "", 1.0)
    )
    assert_that(foreground[0].image.size).is_equal_to((MAX_FRAME_SIZE, 72))


def _gif(colors: list[tuple[int, int, int]], side: int = 16) -> bytes:
    frames = [Image.new("RGB", (side, side), c) for c in colors]
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return buf.getvalue()


def _red_png() -> bytes:
    return _png_bytes(RED + (255,))


def _face_frames(background: bytes) -> tuple[Any, list[Any], AnimationSpec]:
    foreground = _gif([(0, 255, 0), (255, 255, 0)])
    face = compose_key_face(_appearance(), foreground, "", image_scale=0.5, background_image=background)
    spec = face.animation
    assert spec is not None and spec.layer == "foreground"
    poster = Image.open(io.BytesIO(face.png)).convert("RGB").getpixel((1, 1))
    frames = factory_module._compose(spec, factory_module._decode(spec), SIZE)  # pylint: disable=protected-access
    return poster, [frame.getpixel((1, 1)) for frame in frames], spec


def test_animated_foreground_frames_show_a_static_background_like_the_poster() -> None:
    poster, corners, _spec = _face_frames(_red_png())
    assert_that(poster).is_equal_to(RED)
    assert_that(corners).is_length(2)
    assert_that(set(corners)).is_equal_to({RED})


def test_animated_foreground_frames_show_the_first_frame_of_an_animated_background() -> None:
    poster, corners, _spec = _face_frames(_gif([RED, BLUE]))
    assert_that(poster).is_equal_to(RED)
    assert_that(set(corners)).is_equal_to({RED})


def test_animated_foreground_full_build_frames_match_the_poster_background() -> None:
    _poster, _corners, spec = _face_frames(_red_png())
    frames = compose_key_frames(
        spec.appearance, [Image.new("RGBA", (8, 8), (0, 0, 0, 0))], "", SIZE, 0.5, background_image=spec.background
    )
    assert_that(frames[0].getpixel((SIZE // 2, SIZE // 2))).is_equal_to(RED)  # transparent icon shows it too


def test_replacing_the_background_image_changes_the_foreground_animation_id() -> None:
    _p, _c, red = _face_frames(_red_png())
    _p, _c, blue = _face_frames(_png_bytes(BLUE + (255,)))
    _p, _c, red_again = _face_frames(_red_png())
    assert_that(red.animation_id).is_not_equal_to(blue.animation_id)
    assert_that(red.animation_id).is_equal_to(red_again.animation_id)


def test_foreground_spec_without_a_background_image_keeps_its_id() -> None:
    foreground = _gif([(0, 255, 0), (255, 255, 0)])
    for appearance, background in ((_appearance("color"), _red_png()), (_appearance("image"), None)):
        spec = compose_key_face(appearance, foreground, "t", image_scale=0.5, background_image=background).animation
        assert spec is not None
        assert_that(spec.background).is_none()
        look = json.dumps([dict(appearance), "t", repr(0.5)], sort_keys=True, default=str)
        expected = hashlib.sha256(f"{hashlib.sha256(foreground).hexdigest()}:{look}".encode()).hexdigest()
        assert_that(spec.animation_id).is_equal_to(expected)
