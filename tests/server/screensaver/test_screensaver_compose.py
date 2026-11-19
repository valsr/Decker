from assertpy import assert_that
from PIL import Image

from decker.server.screensaver.compose import canvas_layout, compose, preview_image


def _px(image: Image.Image, xy: tuple[int, int]) -> tuple[int, ...]:
    value = image.getpixel(xy)
    assert isinstance(value, tuple)
    return value


def _columns_image(width: int, height: int = 4) -> Image.Image:
    image = Image.new("RGB", (width, height))
    for x in range(width):
        for y in range(height):
            image.putpixel((x, y), (x % 256, x // 256, 7))
    return image


def test_layout_no_bezel_is_contiguous() -> None:
    layout = canvas_layout(2, 3, 72, False, 16, 4)
    assert_that((layout.width, layout.height)).is_equal_to((216, 144))
    assert_that(layout.boxes[0]).is_equal_to((0, 0, 72, 72))
    assert_that(layout.boxes[1]).is_equal_to((72, 0, 144, 72))
    assert_that(layout.boxes[3]).is_equal_to((0, 72, 72, 144))


def test_layout_bezel_16_4_on_72px() -> None:
    layout = canvas_layout(3, 5, 72, True, 16, 4)
    assert_that(layout.width).is_equal_to(5 * 72 + 4 * 18)
    assert_that(layout.height).is_equal_to(3 * 72 + 2 * 18)
    assert_that(layout.boxes[1]).is_equal_to((90, 0, 162, 72))
    assert_that(layout.boxes[5]).is_equal_to((0, 90, 72, 162))
    assert_that(layout.boxes[14]).is_equal_to((360, 180, 432, 252))


def test_compose_slices_have_key_size() -> None:
    layout = canvas_layout(2, 3, 72, True, 16, 4)
    slices = compose(Image.new("RGB", (500, 300), "red"), layout, "center")
    assert_that(slices).is_length(6)
    assert_that({s.size for s in slices}).is_equal_to({(72, 72)})


def test_bezel_slices_skip_gap_pixels() -> None:
    layout = canvas_layout(1, 3, 10, True, 16, 8)  # gap 5px, canvas 40px wide
    slices = compose(_columns_image(layout.width), layout, "stretch")
    seen = [{_px(s, (x, 0))[0] for x in range(10)} for s in slices]
    assert_that(seen[0]).is_equal_to(set(range(0, 10)))
    assert_that(seen[1]).is_equal_to(set(range(15, 25)))
    assert_that(seen[2]).is_equal_to(set(range(30, 40)))
    gap_values = set(range(10, 15)) | set(range(25, 30))
    assert_that(set().union(*seen) & gap_values).is_empty()


def test_center_crops_wide_image_symmetrically() -> None:
    layout = canvas_layout(1, 1, 10, False, 16, 4)
    image = Image.new("RGB", (30, 10), "blue")
    for x in range(10):
        image.putpixel((x, 5), (255, 0, 0))
        image.putpixel((29 - x, 5), (0, 255, 0))
    (face,) = compose(image, layout, "center")
    assert_that(_px(face, (0, 5))[:3]).is_equal_to((0, 0, 255))
    assert_that(_px(face, (9, 5))[:3]).is_equal_to((0, 0, 255))
    assert_that(_px(face, (0, 0))[:3]).is_equal_to((0, 0, 255))
    # cropped 10 px each side: the edge markers are cut off entirely
    assert_that(face.size).is_equal_to((10, 10))


def test_center_crop_keeps_middle_markers() -> None:
    layout = canvas_layout(1, 1, 10, False, 16, 4)
    image = Image.new("RGB", (30, 10), "blue")
    image.putpixel((10, 5), (255, 0, 0))
    image.putpixel((19, 5), (0, 255, 0))
    (face,) = compose(image, layout, "center")
    assert_that(_px(face, (0, 5))[:3]).is_equal_to((255, 0, 0))
    assert_that(_px(face, (9, 5))[:3]).is_equal_to((0, 255, 0))


def test_stretch_distorts_to_fill() -> None:
    layout = canvas_layout(1, 1, 10, False, 16, 4)
    image = Image.new("RGB", (30, 10), "blue")
    for x in range(15):
        for y in range(10):
            image.putpixel((x, y), (255, 0, 0))
    (face,) = compose(image, layout, "stretch")
    assert_that(_px(face, (1, 5))[0]).is_greater_than(240)
    assert_that(_px(face, (8, 5))[2]).is_greater_than(240)


def test_preview_gaps_are_dark() -> None:
    layout = canvas_layout(1, 2, 10, True, 16, 8)
    preview = preview_image(Image.new("RGB", (100, 50), (200, 200, 200)), layout, "stretch")
    assert_that(preview.size).is_equal_to((layout.width, layout.height))
    assert_that(_px(preview, (12, 5))[:3]).is_equal_to((16, 16, 16))
    assert_that(_px(preview, (5, 5))[:3]).is_equal_to((200, 200, 200))
    assert_that(_px(preview, (20, 5))[:3]).is_equal_to((200, 200, 200))
