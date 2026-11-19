import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from assertpy import assert_that
from PIL import ImageFont

from decker.server import appearance, fonts


@pytest.fixture(autouse=True)
def _fresh_font_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(fonts, "_index", None)
    fonts.font_file.cache_clear()
    yield
    fonts.font_file.cache_clear()


def _copy_bundled(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copy(fonts.BUNDLED_REGULAR, directory / "aaa.ttf")
    shutil.copy(fonts.BUNDLED_BOLD, directory / "bbb.ttf")
    return directory


def test_build_font_index_reads_family_and_style_from_the_files(tmp_path: Path) -> None:
    index = fonts.build_font_index([_copy_bundled(tmp_path)])

    assert_that(index).contains_key(("dejavu sans", "regular"), ("dejavu sans", "bold"))
    assert_that(index[("dejavu sans", "bold")]).ends_with("bbb.ttf")


def test_a_corrupt_font_file_is_skipped(tmp_path: Path) -> None:
    _copy_bundled(tmp_path)
    (tmp_path / "x.ttf").write_text("not a font")

    index = fonts.build_font_index([tmp_path, tmp_path / "missing"])

    assert_that(index).contains_key(("dejavu sans", "regular"))


def test_font_lookup_is_case_insensitive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    monkeypatch.setattr(fonts, "font_directories", lambda: [_copy_bundled(tmp_path)])

    path, _ = fonts.font_file("DEJAVU sans")

    assert_that(path).ends_with("aaa.ttf")


def test_font_file_uses_the_index_when_fc_match_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    monkeypatch.setattr(fonts, "font_directories", lambda: [_copy_bundled(tmp_path)])

    assert_that(fonts.font_file("DejaVu Sans")).is_equal_to((str(tmp_path / "aaa.ttf"), False))
    assert_that(fonts.font_file("DejaVu Sans", bold=True)).is_equal_to((str(tmp_path / "bbb.ttf"), True))


def test_font_file_falls_back_to_the_bundled_font_when_nothing_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    monkeypatch.setattr(fonts, "font_directories", lambda: [tmp_path])

    assert_that(fonts.font_file("No Such Family")).is_equal_to((str(fonts.BUNDLED_REGULAR), False))
    assert_that(fonts.font_file("No Such Family", bold=True)).is_equal_to((str(fonts.BUNDLED_BOLD), True))


def test_bundled_fonts_exist() -> None:
    assert_that(fonts.BUNDLED_REGULAR.is_file()).is_true()
    assert_that(fonts.BUNDLED_BOLD.is_file()).is_true()
    assert_that((fonts.BUNDLED_REGULAR.parent / "LICENSE-DejaVu.txt").is_file()).is_true()


def test_font_directories_per_platform(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("WINDIR", str(tmp_path / "win"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_DATA_DIRS", f"{tmp_path / 'd1'}:{tmp_path / 'd2'}")

    monkeypatch.setattr(sys, "platform", "win32")
    assert_that(fonts.font_directories()).contains(
        tmp_path / "win" / "Fonts", tmp_path / "local" / "Microsoft" / "Windows" / "Fonts"
    )
    monkeypatch.setattr(sys, "platform", "darwin")
    assert_that(fonts.font_directories()).contains(
        Path("/System/Library/Fonts"), Path("/Library/Fonts"), tmp_path / "home" / "Library" / "Fonts"
    )
    monkeypatch.setattr(sys, "platform", "linux")
    assert_that(fonts.font_directories()).contains(
        tmp_path / "xdg" / "fonts", Path("/usr/share/fonts"), tmp_path / "d1" / "fonts", tmp_path / "d2" / "fonts"
    )


def test_appearance_font_never_returns_the_pillow_default_font(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    monkeypatch.setattr(fonts, "font_directories", lambda: [tmp_path])

    font, _ = appearance._font("No Such Family", 20)

    assert_that(font).is_instance_of(ImageFont.FreeTypeFont)
