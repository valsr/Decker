from pathlib import Path

import pytest
from assertpy import assert_that
from PIL import Image

from decker.server.screensaver import source
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
    assert_that(load_image(str(tmp_path / "b.svg"), 40, 30).size).is_equal_to((40, 30))


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
