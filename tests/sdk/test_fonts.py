import itertools
import subprocess
import sys
from pathlib import Path

import pytest
from assertpy import assert_that

from decker_plugin_sdk.fonts import font_path

BUNDLED = Path(__file__).resolve().parents[2] / "src" / "decker" / "assets" / "fonts"
FAMILIES = ["DejaVu Sans", "DejaVu Sans Condensed", "DejaVu Sans Mono", "DejaVu Serif", "DejaVu Serif Condensed"]
PREFIX = {
    "DejaVu Sans": "DejaVuSans",
    "DejaVu Sans Condensed": "DejaVuSansCondensed",
    "DejaVu Sans Mono": "DejaVuSansMono",
    "DejaVu Serif": "DejaVuSerif",
    "DejaVu Serif Condensed": "DejaVuSerifCondensed",
}
COMBOS = list(itertools.product(FAMILIES, [False, True], [False, True]))


def _name(family: str, bold: bool, italic: bool) -> str:
    slant = "Italic" if "Serif" in family else "Oblique"
    suffix = "-" + ("Bold" if bold else "") + (slant if italic else "")
    return PREFIX[family] + (suffix if suffix != "-" else "") + ".ttf"


@pytest.mark.parametrize("family,bold,italic", COMBOS)
def test_font_path_maps_to_expected_file(
    family: str, bold: bool, italic: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / _name(family, bold, italic)).write_bytes(b"")
    monkeypatch.setenv("DECKER_FONT_DIR", str(tmp_path))
    result = font_path(family, bold, italic)
    assert_that(result).is_equal_to(str(tmp_path / _name(family, bold, italic)))


@pytest.mark.parametrize("family,bold,italic", COMBOS)
def test_every_combination_exists_in_bundled_folder(
    family: str, bold: bool, italic: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DECKER_FONT_DIR", str(BUNDLED))
    result = font_path(family, bold, italic)
    assert_that(result).is_not_none()
    assert_that(Path(str(result)).is_file()).is_true()


def test_default_is_regular_dejavu_sans(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECKER_FONT_DIR", str(BUNDLED))
    assert_that(font_path()).is_equal_to(str(BUNDLED / "DejaVuSans.ttf"))


def test_unset_variable_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DECKER_FONT_DIR", raising=False)
    assert_that(font_path()).is_none()


def test_empty_variable_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECKER_FONT_DIR", "")
    assert_that(font_path()).is_none()


def test_unknown_family_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECKER_FONT_DIR", str(BUNDLED))
    assert_that(font_path("Comic Sans")).is_none()


def test_missing_file_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECKER_FONT_DIR", str(tmp_path))
    assert_that(font_path()).is_none()


def test_family_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECKER_FONT_DIR", str(BUNDLED))
    assert_that(font_path("dejavu SERIF")).is_equal_to(str(BUNDLED / "DejaVuSerif.ttf"))


@pytest.mark.parametrize("value", ["C:\\nope\\fonts", "relative/dir"])
def test_odd_directories_never_raise(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECKER_FONT_DIR", value)
    assert_that(font_path()).is_none()


def test_relative_directory_containing_the_font_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "DejaVuSans.ttf").write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DECKER_FONT_DIR", ".")
    assert_that(font_path()).is_none()


def test_module_imports_with_only_stdlib() -> None:
    src = Path(__file__).resolve().parents[2] / "src" / "decker_plugin_sdk"
    code = (
        "import sys, importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('decker_plugin_sdk_fonts', {str(src / 'fonts.py')!r})\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "assert not [m for m in sys.modules if m == 'decker' or m.startswith('decker.')], 'imports decker'\n"
        "assert 'PIL' not in sys.modules\n"
    )
    result = subprocess.run([sys.executable, "-I", "-S", "-c", code], capture_output=True, text=True, check=False)
    assert_that(result.returncode).described_as(result.stderr).is_equal_to(0)
