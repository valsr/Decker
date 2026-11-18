import io

import pytest
from assertpy import assert_that
from PIL import Image

from decker.animation import gif
from decker.animation.gif import GifError, decode_gif, is_animated_gif, is_gif


def _make_gif(frames: list[Image.Image], **kwargs: object) -> bytes:
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], **kwargs)
    return buffer.getvalue()


def _alpha(image: Image.Image, xy: tuple[int, int]) -> int:
    pixel = image.getpixel(xy)
    assert isinstance(pixel, tuple)
    return int(pixel[3])


def _solid(color: tuple[int, int, int], size: int = 8) -> Image.Image:
    return Image.new("RGB", (size, size), color)


def test_delays_below_20ms_become_100ms() -> None:
    data = _make_gif([_solid((255, 0, 0)), _solid((0, 255, 0)), _solid((0, 0, 255))], duration=[0, 10, 50])

    frames = decode_gif(data)

    assert_that([f.delay_ms for f in frames]).is_equal_to([100, 100, 50])


def test_disposal_restore_to_background_clears_previous_frame() -> None:
    first = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
    second = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    second.putpixel((1, 1), (0, 255, 0, 255))
    data = _make_gif([first, second], duration=100, disposal=2, transparency=0)

    frames = decode_gif(data)

    assert_that(frames).is_length(2)
    image = frames[1].image
    assert_that(image.mode).is_equal_to("RGBA")
    assert_that(image.getpixel((1, 1))).is_equal_to((0, 255, 0, 255))
    assert_that(_alpha(image, (5, 5))).is_equal_to(0)


def test_transparent_pixels_stay_transparent_in_rgba() -> None:
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    image.putpixel((2, 2), (255, 0, 0, 255))
    other = image.copy()
    other.putpixel((3, 3), (0, 0, 255, 255))

    frames = decode_gif(_make_gif([image, other], duration=100, disposal=2))

    assert_that(_alpha(frames[0].image, (0, 0))).is_equal_to(0)
    assert_that(_alpha(frames[0].image, (2, 2))).is_equal_to(255)


def test_single_frame_gif_is_not_animated() -> None:
    data = _make_gif([_solid((1, 2, 3))])

    assert_that(is_gif(data)).is_true()
    assert_that(is_animated_gif(data)).is_false()
    assert_that(decode_gif(data)).is_length(1)


def test_animated_gif_is_animated() -> None:
    data = _make_gif([_solid((255, 0, 0)), _solid((0, 255, 0))], duration=100)

    assert_that(is_animated_gif(data)).is_true()


def test_more_than_300_frames_raises_gif_error() -> None:
    frames = [Image.new("L", (2, 2), i % 256) for i in range(gif.MAX_GIF_FRAMES + 1)]
    data = _make_gif(frames, duration=20)

    with pytest.raises(GifError):
        decode_gif(data)


@pytest.mark.parametrize("count, animated", [(gif.MAX_GIF_FRAMES, True), (gif.MAX_GIF_FRAMES + 1, False)])
def test_only_gifs_within_the_frame_cap_count_as_animated(count: int, animated: bool) -> None:
    data = _make_gif([Image.new("L", (2, 2), i % 256) for i in range(count)], duration=20)

    assert_that(is_animated_gif(data)).is_equal_to(animated)


def test_frame_above_pixel_budget_raises_gif_error(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _make_gif([_solid((1, 2, 3), 8)])
    monkeypatch.setattr(gif, "MAX_RASTER_PIXELS", 10)

    with pytest.raises(GifError):
        decode_gif(data)


def test_corrupt_bytes_raise_gif_error() -> None:
    with pytest.raises(GifError):
        decode_gif(b"GIF89a" + b"\x00" * 10)


def test_non_gif_bytes_are_not_gifs() -> None:
    assert_that(is_gif(b"\x89PNG\r\n")).is_false()
    assert_that(is_animated_gif(b"\x89PNG\r\n")).is_false()
    assert_that(is_animated_gif(b"GIF89a-garbage")).is_false()


def test_total_duration_is_never_zero() -> None:
    data = _make_gif([_solid((255, 0, 0)), _solid((0, 255, 0))], duration=0)

    frames = decode_gif(data)

    assert_that(sum(f.delay_ms for f in frames)).is_greater_than(0)
