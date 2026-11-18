import io
import random
import time
import warnings

import pytest
from assertpy import assert_that
from PIL import Image, ImageFile
from PIL.GifImagePlugin import GifImageFile

from decker.animation import gif
from decker.animation.gif import GifError, decode_gif, is_animated_gif, is_gif
from tests.animation.grown_gif import (
    comment_flood_gif,
    desynced_gif,
    grown_gif,
    netscape_aligned_gif,
    netscape_hidden_gif,
)


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


def _spy_on_pillow_work(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every frame seek (Image.open and n_frames included) and every pixel load or load preparation."""
    calls: list[str] = []
    original_seek = GifImageFile._seek  # pylint: disable=protected-access
    original_prepare = GifImageFile.load_prepare
    original_load = ImageFile.ImageFile.load

    def seek(self: GifImageFile, frame: int, update_image: bool = True) -> None:
        calls.append(f"seek {frame}")
        original_seek(self, frame, update_image)

    def load_prepare(self: GifImageFile) -> None:
        calls.append("load_prepare")
        original_prepare(self)

    def load(self: ImageFile.ImageFile) -> object:
        calls.append("load")
        return original_load(self)

    monkeypatch.setattr(GifImageFile, "_seek", seek)
    monkeypatch.setattr(GifImageFile, "load_prepare", load_prepare)
    monkeypatch.setattr(ImageFile.ImageFile, "load", load)
    return calls


# 2x2 logical screen and a 2x2 first frame, then frames that make Pillow grow the canvas while iterating.
_GROWN_SHAPES = {
    "3x8000": [(2, 2)] + [(8000, 8000)] * 3,
    "20x4096": [(2, 2)] + [(4096, 4096)] * 19,
    "frame-over-raster-cap": [(2, 2), (4097, 4097)],
}


@pytest.mark.parametrize("sizes", _GROWN_SHAPES.values(), ids=_GROWN_SHAPES.keys())
@pytest.mark.parametrize("junk", [b"", b"\x00", b"\x7f\x00\xff"], ids=["clean", "zero-byte", "junk-bytes"])
def test_frames_that_outgrow_the_logical_screen_are_rejected_before_pillow_touches_them(
    sizes: list[tuple[int, int]], junk: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = grown_gif((2, 2), sizes, junk=junk)
    assert_that(len(data)).is_less_than(300 * 1024)
    seeks = _spy_on_pillow_work(monkeypatch)

    assert_that(is_animated_gif(data)).is_false()
    with pytest.raises(GifError, match="too large|too many pixels"):
        decode_gif(data)

    assert_that(seeks).is_empty()


@pytest.mark.parametrize("junk", [b"", b"\x00"], ids=["clean", "zero-byte"])
def test_a_huge_frame_with_a_disposal_fill_is_rejected_before_pillow_allocates_it(
    junk: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = grown_gif((2, 2), [(2, 2), (12000, 12000), (2, 2)], junk=junk, disposal=2)
    calls = _spy_on_pillow_work(monkeypatch)

    assert_that(is_animated_gif(data)).is_false()
    with pytest.raises(GifError, match="too large"):
        decode_gif(data)

    assert_that(calls).is_empty()


def test_padding_bytes_between_blocks_do_not_stop_a_gif_from_playing() -> None:
    data = grown_gif((16, 16), [(16, 16)] * 3, junk=b"\x00\x00")

    assert_that(is_animated_gif(data)).is_true()
    assert_that(decode_gif(data)).is_length(3)


def test_a_block_walk_that_disagrees_with_the_decoder_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    data = grown_gif((8, 8), [(8, 8)] * 3)
    monkeypatch.setattr(gif, "_check_descriptors", lambda data: gif._Walk([10, 20], (8, 8)))

    assert_that(is_animated_gif(data)).is_false()
    with pytest.raises(GifError, match="block walk"):
        decode_gif(data)


def _canvas_costs(data: bytes) -> list[int]:
    """The canvas pixels Pillow itself pays for each frame; an unreadable GIF costs nothing."""
    costs: list[int] = []
    try:
        with Image.open(io.BytesIO(data)) as image:
            for index in range(getattr(image, "n_frames", 1)):
                image.seek(index)
                costs.append(image.width * image.height)
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    return costs


def _mutants(count: int) -> list[bytes]:
    rng = random.Random(20260518)
    bases = [
        grown_gif((4, 4), [(4, 4), (9, 7), (5, 5)]),
        grown_gif((4, 4), [(4, 4), (60, 60)], junk=b"\x00", disposal=2),
        _make_gif([_solid((255, 0, 0), 6), _solid((0, 255, 0), 6), _solid((0, 0, 255), 6)], duration=50),
    ]
    mutants = []
    for _ in range(count):
        data = bytearray(rng.choice(bases))
        for _ in range(rng.randint(1, 3)):
            kind = rng.randrange(3)
            at = rng.randrange(len(data))
            if kind == 0:
                data[at] = rng.randrange(256)
            elif kind == 1:
                data.insert(at, rng.choice([0x00, 0x21, 0x2C, 0x3B, rng.randrange(256)]))
            else:
                del data[at:]
                break
        mutants.append(bytes(data))
    return mutants


def test_mutated_gifs_never_cost_pillow_more_than_the_budget_the_walk_enforces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gif, "MAX_RASTER_PIXELS", 2_000)
    monkeypatch.setattr(gif, "MAX_GIF_PIXELS", 6_000)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 40_000)  # Pillow itself cannot allocate a big canvas here
    started = time.perf_counter()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for data in _mutants(400):
            try:
                gif._check_descriptors(data)  # pylint: disable=protected-access
            except GifError:
                continue
            costs = _canvas_costs(data)
            assert_that(max(costs, default=0)).is_less_than_or_equal_to(gif.MAX_RASTER_PIXELS)
            assert_that(sum(costs)).is_less_than_or_equal_to(gif.MAX_GIF_PIXELS)
            try:
                decode_gif(data)
            except GifError:
                pass

    assert_that(time.perf_counter() - started).is_less_than(20)


def test_the_running_canvas_total_is_checked_as_frames_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    # Budget for the first frames only: the third frame's growth tips the running total, not the header.
    data = grown_gif((2, 2), [(2, 2), (30, 30), (30, 30), (30, 30)])
    monkeypatch.setattr(gif, "MAX_GIF_PIXELS", 3 * 900 - 1)

    assert_that(is_animated_gif(data)).is_false()
    with pytest.raises(GifError, match="too many pixels"):
        decode_gif(data)


def test_decode_rechecks_each_frame_when_the_descriptor_walk_is_bypassed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gif, "_check_descriptors", lambda data: gif._Walk([], None))
    monkeypatch.setattr(gif, "_check_budget", lambda image, offsets: None)
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


_DESYNCED = {
    "no-trailer-12000-disposal-2": desynced_gif((12000, 12000), balanced=False, disposal=2),
    "balanced-12000-disposal-2": desynced_gif((12000, 12000), balanced=True, disposal=2),
    "balanced-19x4096": desynced_gif((4096, 4096), balanced=True, hidden=19),
}


@pytest.mark.parametrize("data", _DESYNCED.values(), ids=_DESYNCED.keys())
def test_empty_extension_blocks_cannot_show_the_walk_other_frames_than_pillow_reads(
    data: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _spy_on_pillow_work(monkeypatch)

    assert_that(is_animated_gif(data)).is_false()
    with pytest.raises(GifError):
        decode_gif(data)

    assert_that(calls).is_empty()


def _one_chain_walk(data: bytes, check_pixels: bool = True) -> gif._Walk:  # pylint: disable=protected-access
    """The naive walk (a single sub-block chain per extension, no budget): what the layout check must see through."""
    offsets, canvas, pos = [], None, 13 + (3 << ((data[10] & 7) + 1))
    width, height = int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    while pos < len(data) and data[pos] != 0x3B:
        if data[pos] == 0x21:
            pos = gif._skip_sub_blocks(data, pos + 2)  # pylint: disable=protected-access
        elif data[pos] == 0x2C:
            left, top, frame_width, frame_height = (
                int.from_bytes(data[pos + i : pos + i + 2], "little") for i in (1, 3, 5, 7)
            )
            width, height = max(width, left + frame_width), max(height, top + frame_height)
            canvas = canvas or (width, height)
            offsets.append(pos + 11)
            pos = gif._skip_sub_blocks(data, pos + 11)  # pylint: disable=protected-access
        else:
            pos += 1
    return gif._Walk(offsets, canvas)  # pylint: disable=protected-access


@pytest.mark.parametrize("data", _DESYNCED.values(), ids=_DESYNCED.keys())
def test_the_layout_check_alone_catches_a_walk_that_was_fooled(data: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gif, "_check_descriptors", _one_chain_walk)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)  # Pillow itself could not allocate a big canvas anyway

    assert_that(is_animated_gif(data)).is_false()
    with pytest.raises(GifError):
        decode_gif(data)


def test_the_layout_check_rejects_ordinary_gifs_when_pillow_hides_its_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    data = grown_gif((8, 8), [(8, 8)] * 3)
    assert_that(is_animated_gif(data)).is_true()

    def hidden(image: Image.Image) -> int:
        raise AttributeError("renamed in a newer Pillow")

    monkeypatch.setattr(gif, "_frame_offset", hidden)

    assert_that(is_animated_gif(data)).is_false()  # fails closed: upgrade Pillow, notice the failing tests
    with pytest.raises(GifError, match="cannot verify"):
        decode_gif(data)


def test_the_walk_stays_linear_on_padding_runs() -> None:
    chunk = b"\x00\x21\x01\x01\x41\x00"
    data = b"GIF89a\x02\x00\x02\x00\x00\x00\x00" + chunk * (1024 * 1024 // len(chunk))
    started = time.perf_counter()

    assert_that(is_animated_gif(data)).is_false()
    with pytest.raises(GifError):
        decode_gif(data)

    assert_that(time.perf_counter() - started).is_less_than(1.0)


def test_a_comment_flood_is_rejected_by_the_walk_in_well_under_a_second() -> None:
    data = comment_flood_gif(350_000)  # about 1 MiB of empty comment blocks
    started = time.perf_counter()

    assert_that(is_animated_gif(data)).is_false()
    with pytest.raises(GifError, match="comment|extension"):
        decode_gif(data)
    with pytest.raises(GifError):
        gif.check_gif_bounds(data)

    assert_that(time.perf_counter() - started).is_less_than(1.0)


def test_a_comment_cut_into_one_byte_sub_blocks_is_rejected_quickly() -> None:
    data = comment_flood_gif(gif.MAX_COMMENT_SUB_BLOCKS + 1, b"x")
    started = time.perf_counter()

    assert_that(is_animated_gif(data)).is_false()
    with pytest.raises(GifError, match="comment"):
        decode_gif(data)

    assert_that(time.perf_counter() - started).is_less_than(1.0)


@pytest.mark.parametrize("big", [(13000, 13000), (40, 40)], ids=["13000", "40"])
def test_a_loop_extension_without_its_count_is_rejected_before_pillow_reads_it(
    big: tuple[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    data = netscape_hidden_gif(big, disposal=2)
    calls = _spy_on_pillow_work(monkeypatch)

    assert_that(is_animated_gif(data)).is_false()
    with pytest.raises(GifError, match="loop"):
        decode_gif(data)

    assert_that(calls).is_empty()


def test_the_aligned_frame_zero_shape_is_rejected_before_pillow_reads_it(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _spy_on_pillow_work(monkeypatch)

    assert_that(is_animated_gif(netscape_aligned_gif())).is_false()

    assert_that(calls).is_empty()


def test_the_frame_zero_canvas_check_alone_catches_the_aligned_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    data = netscape_aligned_gif()
    monkeypatch.setattr(gif, "_check_descriptors", _one_chain_walk)
    monkeypatch.setattr(gif, "_verify_offsets", lambda image, offsets: None)  # offsets agree here anyway
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", None)

    assert_that(is_animated_gif(data)).is_false()
    with pytest.raises(GifError, match="first frame"):
        decode_gif(data)


def test_a_gif_with_a_comment_and_a_loop_count_still_animates() -> None:
    frames = [_solid((255, 0, 0)), _solid((0, 255, 0)), _solid((0, 0, 255))]
    data = _make_gif(frames, duration=100, loop=3, comment=b"made by a test")

    assert_that(is_animated_gif(data)).is_true()
    assert_that(decode_gif(data)).is_length(3)
