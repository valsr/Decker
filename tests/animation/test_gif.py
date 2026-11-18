import io

import pytest
from assertpy import assert_that
from PIL import Image
from PIL.GifImagePlugin import GifImageFile

from decker.animation import gif
from decker.animation.gif import GifError, decode_gif, is_animated_gif, is_gif
from tests.animation.grown_gif import grown_gif


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


def _header_only_gif(width: int, height: int, frames: int) -> bytes:
    # Tiny GIF whose logical screen claims a huge canvas: cheap to build, never decoded.
    small = [Image.new("L", (2, 2), index % 256) for index in range(frames)]
    data = bytearray(_make_gif(small, duration=100))
    data[6:10] = width.to_bytes(2, "little") + height.to_bytes(2, "little")
    return bytes(data)


@pytest.mark.parametrize("width, height, frames", [(4096, 4096, 300), (1024, 1024, 100)])
def test_a_gif_over_the_total_pixel_budget_is_rejected_from_its_header(width: int, height: int, frames: int) -> None:
    data = _header_only_gif(width, height, frames)

    assert_that(is_animated_gif(data)).is_false()
    with pytest.raises(GifError, match="too many pixels"):
        decode_gif(data)


def test_300_frames_of_480_square_stay_within_the_budget() -> None:
    assert_that(gif.MAX_GIF_FRAMES * 480 * 480).is_less_than_or_equal_to(gif.MAX_GIF_PIXELS)
    assert_that(is_animated_gif(_header_only_gif(480, 480, gif.MAX_GIF_FRAMES))).is_true()


def test_frames_are_shrunk_to_the_largest_key_size_while_decoding() -> None:
    big = [Image.new("RGB", (600, 300), (index * 40, 0, 0)) for index in range(3)]

    frames = decode_gif(_make_gif(big, duration=100))

    assert_that([frame.image.size for frame in frames]).is_equal_to([(144, 72)] * 3)


def test_a_small_gif_keeps_its_canvas_size() -> None:
    frames = decode_gif(_make_gif([_solid((255, 0, 0), 100), _solid((0, 255, 0), 100)], duration=100))

    assert_that(frames[0].image.size).is_equal_to((100, 100))


def test_gif_bytes_over_the_icon_size_cap_are_not_animated(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _make_gif([_solid((255, 0, 0)), _solid((0, 255, 0))], duration=100)
    monkeypatch.setattr(gif, "MAX_ICON_BYTES", len(data) - 1)

    assert_that(is_animated_gif(data)).is_false()
    with pytest.raises(GifError, match="larger than"):
        decode_gif(data)


def _count_seeks(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    seeks: list[int] = []
    original = GifImageFile.seek

    def seek(self: GifImageFile, frame: int) -> None:
        seeks.append(frame)
        original(self, frame)

    monkeypatch.setattr(GifImageFile, "seek", seek)
    return seeks


# 2x2 logical screen and a 2x2 first frame, then frames that make Pillow grow the canvas while iterating.
_GROWN_SHAPES = {
    "3x8000": [(2, 2)] + [(8000, 8000)] * 3,
    "20x4096": [(2, 2)] + [(4096, 4096)] * 19,
    "frame-over-raster-cap": [(2, 2), (4097, 4097)],
}


@pytest.mark.parametrize("sizes", _GROWN_SHAPES.values(), ids=_GROWN_SHAPES.keys())
def test_frames_that_outgrow_the_logical_screen_are_rejected_before_any_frame_is_decoded(
    sizes: list[tuple[int, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    data = grown_gif((2, 2), sizes)
    assert_that(len(data)).is_less_than(300 * 1024)
    seeks = _count_seeks(monkeypatch)

    assert_that(is_animated_gif(data)).is_false()
    with pytest.raises(GifError, match="too large|too many pixels"):
        decode_gif(data)

    assert_that(seeks).is_empty()


def test_the_running_canvas_total_is_checked_as_frames_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    # Budget for the first frames only: the third frame's growth tips the running total, not the header.
    data = grown_gif((2, 2), [(2, 2), (30, 30), (30, 30), (30, 30)])
    monkeypatch.setattr(gif, "MAX_GIF_PIXELS", 3 * 900 - 1)

    assert_that(is_animated_gif(data)).is_false()
    with pytest.raises(GifError, match="too many pixels"):
        decode_gif(data)


def test_decode_rechecks_each_frame_when_the_descriptor_walk_is_bypassed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gif, "_check_descriptors", lambda data: None)
    monkeypatch.setattr(gif, "MAX_RASTER_PIXELS", 40 * 40)
    big = grown_gif((2, 2), [(2, 2), (41, 41)])
    with pytest.raises(GifError, match="too large"):
        decode_gif(big)

    monkeypatch.setattr(gif, "MAX_RASTER_PIXELS", 10**9)
    monkeypatch.setattr(gif, "MAX_GIF_PIXELS", 41 * 41 + 3)
    with pytest.raises(GifError, match="too many pixels"):
        decode_gif(big)


def test_a_frame_that_grows_slightly_past_the_logical_screen_still_plays() -> None:
    data = grown_gif((16, 16), [(16, 16), (20, 18), (16, 16)])

    frames = decode_gif(data)

    assert_that(is_animated_gif(data)).is_true()
    assert_that([f.image.size for f in frames]).is_equal_to([(16, 16), (20, 18), (20, 18)])
    assert_that([f.delay_ms for f in frames]).is_equal_to([100] * 3)


def test_300_frames_of_480_square_decode_within_the_budget() -> None:
    data = grown_gif((480, 480), [(480, 480)] * gif.MAX_GIF_FRAMES)

    frames = decode_gif(data)

    assert_that(is_animated_gif(data)).is_true()
    assert_that(frames).is_length(gif.MAX_GIF_FRAMES)
    assert_that(frames[0].image.size).is_equal_to((144, 144))


def test_a_truncated_gif_is_left_for_the_decoder_to_report() -> None:
    data = grown_gif((8, 8), [(8, 8)] * 3)

    with pytest.raises(GifError):
        decode_gif(data[: len(data) - 12])
