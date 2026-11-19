import os
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
    fonts.clear_font_cache()
    yield
    fonts.clear_font_cache()


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
    monkeypatch.setenv("XDG_DATA_DIRS", os.pathsep.join([str(tmp_path / "d1"), str(tmp_path / "d2")]))

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


def _fake_names(monkeypatch: pytest.MonkeyPatch, names: dict[str, list[tuple[str, str]]]) -> None:
    def face_name(path: Path, face: int) -> tuple[str, str]:
        faces = names[path.name]
        if face >= len(faces):
            raise OSError("no such face")
        return faces[face]

    monkeypatch.setattr(fonts, "_face_name", face_name)


def _touch(directory: Path, *file_names: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in file_names:
        (directory / name).write_bytes(b"x")


def test_only_the_regular_style_takes_the_regular_slot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _touch(tmp_path, "a-light.ttf", "b-semibold.ttf", "c-book.ttf", "d-regular.ttf", "e-black.ttf")
    _fake_names(
        monkeypatch,
        {
            "a-light.ttf": [("Fam", "Light")],
            "b-semibold.ttf": [("Fam", "Semibold")],
            "c-book.ttf": [("Fam", "Book")],
            "d-regular.ttf": [("Fam", "Regular")],
            "e-black.ttf": [("Fam", "Black")],
        },
    )

    index = fonts.build_font_index([tmp_path])

    assert_that(index).is_equal_to({("fam", "regular"): str(tmp_path / "d-regular.ttf")})


def test_a_weight_only_family_has_no_regular_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _touch(tmp_path, "a.ttf")
    _fake_names(monkeypatch, {"a.ttf": [("Thin Fam", "Light Italic")]})

    assert_that(fonts.build_font_index([tmp_path])).is_empty()


@pytest.mark.posix_only(
    reason="key rendering and fonts (docs/platform-support.md): chmod 000 makes a font subfolder unreadable"
)
def test_an_unreadable_subfolder_does_not_lose_the_other_fonts(tmp_path: Path) -> None:
    if getattr(os, "geteuid", lambda: 1)() == 0:
        pytest.skip("root can read everything")
    _copy_bundled(tmp_path / "ok")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        index = fonts.build_font_index([tmp_path])
    finally:
        locked.chmod(0o755)

    assert_that(index).contains_key(("dejavu sans", "regular"))


def test_a_walk_error_is_skipped_and_scanning_continues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    good = _copy_bundled(tmp_path / "good")
    real_walk = os.walk

    def walk(top: Path, **kwargs: object) -> Iterator[tuple[str, list[str], list[str]]]:
        onerror = kwargs["onerror"]
        onerror(OSError("denied"))  # type: ignore[operator]
        yield from real_walk(top, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "walk", walk)

    assert_that(fonts.build_font_index([tmp_path])).contains_key(("dejavu sans", "bold"))
    assert_that(good.is_dir()).is_true()


@pytest.mark.posix_only(reason="key rendering and fonts (docs/platform-support.md): directory symlinks need POSIX")
def test_a_directory_symlink_loop_does_not_hang(tmp_path: Path) -> None:
    _copy_bundled(tmp_path / "fonts")
    (tmp_path / "fonts" / "loop").symlink_to(tmp_path, target_is_directory=True)

    index = fonts.build_font_index([tmp_path / "fonts"])

    assert_that(index).contains_key(("dejavu sans", "regular"))


def test_every_face_of_a_collection_is_indexed_with_its_face_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _touch(tmp_path, "pack.ttc")
    _fake_names(monkeypatch, {"pack.ttc": [("Alpha", "Regular"), ("Alpha", "Bold"), ("Beta", "Regular")]})

    index = fonts.build_font_index([tmp_path])
    faces = fonts.build_face_index([tmp_path])

    pack = str(tmp_path / "pack.ttc")
    assert_that(index).is_equal_to({("alpha", "regular"): pack, ("alpha", "bold"): pack, ("beta", "regular"): pack})
    assert_that(faces[("alpha", "bold")]).is_equal_to((pack, 1))
    assert_that(faces[("beta", "regular")]).is_equal_to((pack, 2))


def test_font_face_returns_the_face_of_the_resolved_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _touch(tmp_path, "pack.ttc")
    _fake_names(monkeypatch, {"pack.ttc": [("Alpha", "Regular"), ("Beta", "Regular")]})
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    monkeypatch.setattr(fonts, "font_directories", lambda: [tmp_path])

    path, _ = fonts.font_file("Beta")

    assert_that(fonts.font_face(path or "", "Beta")).is_equal_to(1)
    assert_that(fonts.font_face(str(fonts.BUNDLED_REGULAR), "Beta")).is_equal_to(0)
