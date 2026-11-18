"""Raster resize for user icon import."""

import io

import pytest
from assertpy import assert_that
from PIL import Image

from decker.asset.iconresize import (
    ICON_SIZE,
    ImageImportError,
    ImportOptions,
    convert_raster,
    preview_png,
    resize_image,
)


def _solid(size: tuple[int, int], color: tuple[int, int, int, int] = (255, 0, 0, 255)) -> Image.Image:
    return Image.new("RGBA", size, color)


def _blocked(x: int) -> Image.Image:
    image = Image.new("RGBA", (30, 20), (0, 0, 0, 0))
    image.paste((255, 0, 0, 255), (x, 8, x + 6, 14))
    return image


def _checker() -> Image.Image:
    image = Image.new("RGBA", (2, 2))
    colors = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255)]
    for index, color in enumerate(colors):
        image.putpixel((index % 2, index // 2), color)
    return image


def _px(image: Image.Image, x: int, y: int) -> tuple[int, ...]:
    pixel = image.getpixel((x, y))
    assert isinstance(pixel, tuple)
    return pixel


def _colors(image: Image.Image) -> set[tuple[int, ...]]:
    return {color for _, color in image.getcolors(maxcolors=ICON_SIZE * ICON_SIZE) or [] if isinstance(color, tuple)}


def _png(image: Image.Image, fmt: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB" if fmt == "JPEG" else "RGBA").save(buffer, format=fmt)
    return buffer.getvalue()


def _gif(frames: list[Image.Image], durations: list[int], loop: int = 0) -> bytes:
    buffer = io.BytesIO()
    frames[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=loop,
        disposal=2,
    )
    return buffer.getvalue()


def test_center_fit_scales_by_one_factor_and_pads_transparent() -> None:
    out = resize_image(_solid((200, 100)), ImportOptions())
    assert_that(out.size).is_equal_to((144, 144))
    assert_that(_px(out, 72, 72)).is_equal_to((255, 0, 0, 255))
    assert_that(_px(out, 72, 5)[3]).is_equal_to(0)
    band = [y for y in range(144) if _px(out, 72, y)[3] == 255]
    assert_that(len(band)).is_equal_to(72)


def test_stretch_fills_the_square() -> None:
    out = resize_image(_solid((200, 100)), ImportOptions(fit="stretch"))
    assert_that(_px(out, 0, 0)[3]).is_equal_to(255)
    assert_that(_px(out, 143, 143)[3]).is_equal_to(255)


def test_nearest_keeps_hard_pixel_edges() -> None:
    colors = _colors(resize_image(_checker(), ImportOptions()))
    assert_that(colors).is_length(4)


def test_lanczos_blends_edges() -> None:
    colors = _colors(resize_image(_checker(), ImportOptions(interpolation="lanczos")))
    assert_that(len(colors)).is_greater_than(5)


def test_options_from_json_defaults_and_rejects_unknown_values() -> None:
    assert_that(ImportOptions.from_json("")).is_equal_to(ImportOptions())
    parsed = ImportOptions.from_json('{"fit": "stretch", "interpolation": "bilinear"}')
    assert_that(parsed).is_equal_to(ImportOptions("stretch", "bilinear"))
    with pytest.raises(ValueError):
        ImportOptions.from_json('{"fit": "zoom"}')
    with pytest.raises(ValueError):
        ImportOptions.from_json('{"interpolation": "cubic"}')


def test_jpeg_becomes_png() -> None:
    data, ext = convert_raster(_png(_solid((50, 30)), "JPEG"), ImportOptions())
    assert_that(ext).is_equal_to("png")
    assert_that(Image.open(io.BytesIO(data)).size).is_equal_to((144, 144))


def test_single_frame_gif_becomes_png() -> None:
    data, ext = convert_raster(_gif([_solid((20, 20))], [100]), ImportOptions())
    assert_that(ext).is_equal_to("png")
    assert_that(Image.open(io.BytesIO(data)).format).is_equal_to("PNG")


def test_animated_gif_keeps_frame_count_durations_loop_and_transparency() -> None:
    frames = [_blocked(x) for x in (4, 12, 20)]
    data, ext = convert_raster(_gif(frames, [50, 120, 80], loop=3), ImportOptions())
    assert_that(ext).is_equal_to("gif")
    with Image.open(io.BytesIO(data)) as out:
        assert_that(getattr(out, "n_frames", 0)).is_equal_to(3)
        assert_that(out.info["loop"]).is_equal_to(3)
        assert_that(out.size).is_equal_to((144, 144))
        durations = []
        for index in range(3):
            out.seek(index)
            durations.append(out.info["duration"])
        assert_that(durations).is_equal_to([50, 120, 80])
        out.seek(0)
        assert_that(_px(out.convert("RGBA"), 0, 0)[3]).is_equal_to(0)


@pytest.mark.parametrize("size", [(1, 300), (500, 7)])
def test_odd_canvas_gifs_stay_144(size: tuple[int, int]) -> None:
    frames = [_solid(size), _solid(size, (0, 255, 0, 255))]
    data, _ = convert_raster(_gif(frames, [50, 50]), ImportOptions())
    with Image.open(io.BytesIO(data)) as out:
        assert_that(out.size).is_equal_to((144, 144))


def test_format_is_detected_from_content_not_name() -> None:
    frames = [_solid((10, 10)), _solid((10, 10), (0, 255, 0, 255))]
    _, ext = convert_raster(_gif(frames, [50, 50]), ImportOptions())
    assert_that(ext).is_equal_to("gif")
    _, ext = convert_raster(_png(_solid((10, 10))), ImportOptions())
    assert_that(ext).is_equal_to("png")


def test_non_image_bytes_raise_image_import_error() -> None:
    with pytest.raises(ImageImportError):
        convert_raster(b"definitely not an image", ImportOptions())


def test_corrupt_gif_raises_image_import_error() -> None:
    data = _gif([_solid((10, 10)), _solid((10, 10))], [50, 50])
    with pytest.raises(ImageImportError):
        convert_raster(data[: len(data) // 2], ImportOptions())


def test_oversized_data_raises_image_import_error() -> None:
    with pytest.raises(ImageImportError):
        convert_raster(b"\x89PNG" + b"0" * (5 * 1024 * 1024), ImportOptions())


def test_preview_png_returns_a_144_png() -> None:
    data = preview_png(_png(_solid((50, 30))), ImportOptions())
    with Image.open(io.BytesIO(data)) as out:
        assert_that(out.format).is_equal_to("PNG")
        assert_that(out.size).is_equal_to((144, 144))
