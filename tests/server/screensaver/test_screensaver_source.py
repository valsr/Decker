from pathlib import Path

import pytest
from assertpy import assert_that
from PIL import Image

from decker.server.screensaver import source
from decker.server.screensaver.compose import canvas_layout, preview_image
from decker.server.screensaver.source import (
    GalleryCursor,
    ScreensaverImageError,
    load_image,
)

_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="red"/></svg>'


def test_load_image_reads_png_and_svg(tmp_path: Path) -> None:
    Image.new("RGB", (20, 10), "green").save(tmp_path / "a.png")
    (tmp_path / "b.svg").write_text(_SVG)
    assert_that(load_image(str(tmp_path / "a.png"), 100, 100).size).is_equal_to((20, 10))
    assert_that(load_image(str(tmp_path / "b.svg"), 40, 30).size).is_equal_to((40, 40))  # own aspect, covering


def test_load_image_rejects_missing_and_corrupt(tmp_path: Path) -> None:
    (tmp_path / "bad.png").write_bytes(b"not an image")
    (tmp_path / "bad.svg").write_text("<svg")
    for name in ("missing.png", "bad.png", "bad.svg"):
        with pytest.raises(ScreensaverImageError):
            load_image(str(tmp_path / name), 10, 10)


def test_load_image_rejects_oversize_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Image.new("RGB", (50, 50)).save(tmp_path / "a.png")
    monkeypatch.setattr(source, "MAX_FILE_BYTES", 10)
    with pytest.raises(ScreensaverImageError, match="20 MiB"):
        load_image(str(tmp_path / "a.png"), 10, 10)


def test_load_image_rejects_too_many_pixels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Image.new("RGB", (50, 50)).save(tmp_path / "a.png")
    monkeypatch.setattr(source, "MAX_PIXELS", 2000)
    with pytest.raises(ScreensaverImageError, match="megapixels"):
        load_image(str(tmp_path / "a.png"), 10, 10)


def test_load_image_maps_decompression_bomb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Image.new("RGB", (50, 50)).save(tmp_path / "a.png")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(ScreensaverImageError):
        load_image(str(tmp_path / "a.png"), 10, 10)


def test_gallery_sorted_wraps_and_rescans(tmp_path: Path) -> None:
    for name in ("b.png", "a.JPG", "c.svg", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    cursor = GalleryCursor()
    names = [Path(cursor.next_path(str(tmp_path)) or "").name for _ in range(4)]
    assert_that(names).is_equal_to(["a.JPG", "b.png", "c.svg", "a.JPG"])
    (tmp_path / "ab.png").write_bytes(b"x")
    assert_that(Path(cursor.next_path(str(tmp_path)) or "").name).is_equal_to("ab.png")


def test_gallery_empty_or_missing_folder(tmp_path: Path) -> None:
    assert_that(GalleryCursor().next_path(str(tmp_path))).is_none()
    assert_that(GalleryCursor().next_path(str(tmp_path / "nope"))).is_none()


def _spy_sizes(monkeypatch: pytest.MonkeyPatch, *methods: str) -> list[tuple[int, int]]:
    """Record the size of every image the given Image methods run on."""
    seen: list[tuple[int, int]] = []
    for name in methods:
        original = getattr(Image.Image, name)

        def spy(self: Image.Image, *args: object, _original: object = original, **kwargs: object) -> object:
            seen.append(self.size)
            return _original(self, *args, **kwargs)  # type: ignore[operator]

        monkeypatch.setattr(Image.Image, name, spy)
    return seen


@pytest.mark.parametrize("name", ["big.png", "big.jpg"])
def test_large_image_is_shrunk_before_any_conversion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    Image.new("RGB", (4000, 3000), "red").save(tmp_path / name)
    seen = _spy_sizes(monkeypatch, "convert", "resize", "copy")

    image = load_image(str(tmp_path / name), 120, 48)

    assert_that(image.mode).is_equal_to("RGBA")
    assert_that(image.width).is_greater_than_or_equal_to(240)  # still twice what covering the canvas needs
    assert_that(image.height).is_greater_than_or_equal_to(180)
    assert_that(seen).is_not_empty()
    assert_that(max(w * h for w, h in seen)).is_less_than_or_equal_to(500 * 375)


def test_pixel_cap_is_24_megapixels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert_that(source.MAX_PIXELS).is_equal_to(24_000_000)
    Image.new("RGB", (50, 50)).save(tmp_path / "a.png")
    monkeypatch.setattr(source, "MAX_PIXELS", 2000)
    with pytest.raises(ScreensaverImageError, match="24 megapixels"):
        load_image(str(tmp_path / "a.png"), 10, 10)


def test_only_png_and_jpeg_matching_the_extension_are_decoded(tmp_path: Path) -> None:
    Image.new("RGB", (8, 8)).save(tmp_path / "jpeg.png", format="JPEG")
    Image.new("RGB", (8, 8)).save(tmp_path / "gif.png", format="GIF")
    Image.new("RGB", (8, 8)).save(tmp_path / "png.jpg", format="PNG")
    for name in ("jpeg.png", "gif.png", "png.jpg"):
        with pytest.raises(ScreensaverImageError, match="cannot be decoded"):
            load_image(str(tmp_path / name), 10, 10)


def test_unreadable_file_error_names_only_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Image.new("RGB", (8, 8)).save(tmp_path / "a.png")

    def denied(self: Path, *args: object, **kwargs: object) -> object:
        raise PermissionError(f"Permission denied: '{self}'")

    monkeypatch.setattr(Path, "stat", denied)
    with pytest.raises(ScreensaverImageError) as caught:
        load_image(str(tmp_path / "a.png"), 10, 10)
    assert_that(str(caught.value)).contains("a.png").does_not_contain(str(tmp_path))


_SQUARE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    '<rect width="10" height="10" fill="#ff0000"/></svg>'
)
_WIDE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 10">'
    '<rect width="20" height="10" fill="#ff0000"/><rect x="20" width="20" height="10" fill="#0000ff"/></svg>'
)


@pytest.mark.parametrize("scaling", ["center", "stretch"])
def test_svg_fills_a_non_square_canvas_without_bars(tmp_path: Path, scaling: str) -> None:
    (tmp_path / "s.svg").write_text(_SQUARE_SVG)
    layout = canvas_layout(1, 4, 100, False, 16.0, 4.0)  # 400 x 100

    canvas = preview_image(load_image(str(tmp_path / "s.svg"), layout.width, layout.height), layout, scaling)

    for x, y in ((1, 1), (398, 1), (1, 98), (398, 98), (200, 50)):
        assert_that(canvas.getpixel((x, y))).is_equal_to((255, 0, 0, 255))


def test_svg_stretch_distorts_and_center_crops(tmp_path: Path) -> None:
    (tmp_path / "w.svg").write_text(_WIDE_SVG)  # left half red, right half blue
    layout = canvas_layout(1, 1, 100, False, 16.0, 4.0)
    image = load_image(str(tmp_path / "w.svg"), layout.width, layout.height)

    assert_that(image.size).is_equal_to((400, 100))
    stretched = preview_image(image, layout, "stretch")
    centered = preview_image(image, layout, "center")
    assert_that(stretched.getpixel((10, 50))).is_equal_to((255, 0, 0, 255))
    assert_that(stretched.getpixel((90, 50))).is_equal_to((0, 0, 255, 255))
    assert_that(centered.getpixel((10, 50))).is_equal_to((255, 0, 0, 255))  # the middle 100 px of 400
    assert_that(centered.getpixel((90, 50))).is_equal_to((0, 0, 255, 255))


def test_candidates_scan_once_and_wrap(tmp_path: Path) -> None:
    for name in ("a.png", "b.png", "c.png"):
        (tmp_path / name).write_bytes(b"x")
    cursor = GalleryCursor()
    cursor.mark_shown(str(tmp_path / "b.png"))

    assert_that([Path(p).name for p in cursor.candidates(str(tmp_path))]).is_equal_to(["c.png", "a.png", "b.png"])
