"""Discovery and indexing of the system's freedesktop icon theme."""

import os
from pathlib import Path

import pytest
from assertpy import assert_that

from decker.asset.systemicons import (
    CATEGORIES,
    PACK_PREFIX,
    SYSTEM_PLUGIN_ID,
    SYSTEM_PLUGIN_NAME,
    build_index,
    category_of,
    detect_theme,
    icon_search_dirs,
)


def make_theme(
    root: Path,
    name: str,
    directories: dict[str, dict[str, str]],
    inherits: str = "",
    files: tuple[str, ...] = (),
) -> Path:
    """Write ``<root>/<name>/index.theme`` for the directories and create the (tiny) icon files."""
    theme = root / name
    theme.mkdir(parents=True, exist_ok=True)
    lines = ["[Icon Theme]", f"Name={name}", f"Inherits={inherits}", f"Directories={','.join(directories)}"]
    for directory, keys in directories.items():
        lines += ["", f"[{directory}]", *[f"{k}={v}" for k, v in keys.items()]]
    (theme / "index.theme").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for relative in files:
        path = theme / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"<svg/>" if relative.lower().endswith(".svg") else b"png")
    return theme


class TestConstants:
    def test_categories_in_order(self) -> None:
        assert_that([key for key, _label in CATEGORIES]).is_equal_to(
            [
                "actions",
                "applications",
                "categories",
                "devices",
                "emblems",
                "emotes",
                "mimetypes",
                "places",
                "status",
                "other",
            ]
        )
        assert_that(dict(CATEGORIES)["mimetypes"]).is_equal_to("Mimetypes")
        assert_that(PACK_PREFIX).is_equal_to("decker.system.")
        assert_that((SYSTEM_PLUGIN_ID, SYSTEM_PLUGIN_NAME)).is_equal_to(("decker.system", "System Icons"))

    @pytest.mark.parametrize(
        ("context", "key"),
        [
            ("Actions", "actions"),
            ("actions", "actions"),
            ("Applications", "applications"),
            ("Categories", "categories"),
            ("Devices", "devices"),
            ("Emblems", "emblems"),
            ("Emotes", "emotes"),
            ("MimeTypes", "mimetypes"),
            ("mimetypes", "mimetypes"),
            ("Places", "places"),
            ("Status", "status"),
            ("Animations", "other"),
            ("Panel", "other"),
            ("Stock", "other"),
            ("Whatever", "other"),
            ("", "other"),
            (None, "other"),
        ],
    )
    def test_category_of_maps_contexts_case_insensitively(self, context: str | None, key: str) -> None:
        assert_that(category_of(context)).is_equal_to(key)


class TestSearchDirs:
    def test_defaults_follow_xdg(self, tmp_path: Path) -> None:
        dirs = icon_search_dirs({}, tmp_path)

        assert_that(dirs).is_equal_to(
            [
                tmp_path / ".local/share/icons",
                tmp_path / ".icons",
                Path("/usr/local/share/icons"),
                Path("/usr/share/icons"),
            ]
        )

    def test_environment_overrides(self, tmp_path: Path) -> None:
        env = {"XDG_DATA_HOME": str(tmp_path / "data"), "XDG_DATA_DIRS": f"{tmp_path}/a:{tmp_path}/b"}

        assert_that(icon_search_dirs(env, tmp_path)).is_equal_to(
            [tmp_path / "data/icons", tmp_path / ".icons", tmp_path / "a/icons", tmp_path / "b/icons"]
        )

    def test_blank_entries_are_ignored(self, tmp_path: Path) -> None:
        env = {"XDG_DATA_HOME": "", "XDG_DATA_DIRS": f"::{tmp_path}/a:"}

        dirs = icon_search_dirs(env, tmp_path)

        assert_that(dirs).contains(tmp_path / ".local/share/icons", tmp_path / "a/icons")
        assert_that(dirs).does_not_contain(Path("icons"))


class TestDetectTheme:
    @pytest.fixture(name="env")
    def env_fixture(self, tmp_path: Path):
        home = tmp_path / "home"
        icons = tmp_path / "icons"
        for name in ("Adwaita", "hicolor", "Papirus", "breeze", "Mine"):
            make_theme(icons, name, {})
        return home, [icons]

    @staticmethod
    def _gtk(home: Path, text: str) -> None:
        path = home / ".config/gtk-3.0/settings.ini"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    @staticmethod
    def _kde(home: Path, text: str) -> None:
        path = home / ".config/kdeglobals"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_the_configured_theme_wins(self, env) -> None:
        home, dirs = env
        self._gtk(home, "[Settings]\ngtk-icon-theme-name=Papirus\n")

        assert_that(detect_theme("Mine", home, dirs)).is_equal_to("Mine")

    def test_gtk_then_kde_then_adwaita_then_hicolor(self, env, tmp_path: Path) -> None:
        home, dirs = env
        self._kde(home, "[Icons]\nTheme=breeze\n")
        assert_that(detect_theme("", home, dirs)).is_equal_to("breeze")

        self._gtk(home, "[Settings]\ngtk-icon-theme-name=Papirus\n")
        assert_that(detect_theme("", home, dirs)).is_equal_to("Papirus")

        bare = tmp_path / "bare"
        assert_that(detect_theme("", home / "nope", dirs)).is_equal_to("Adwaita")
        make_theme(bare, "hicolor", {})
        assert_that(detect_theme("", home / "nope", [bare])).is_equal_to("hicolor")

    def test_a_theme_that_is_not_installed_falls_through_to_the_next_source(self, env) -> None:
        home, dirs = env
        self._gtk(home, "[Settings]\ngtk-icon-theme-name=NotInstalled\n")
        self._kde(home, "[Icons]\nTheme=breeze\n")

        assert_that(detect_theme("AlsoMissing", home, dirs)).is_equal_to("breeze")

    def test_values_are_stripped_of_whitespace_and_quotes(self, env) -> None:
        home, dirs = env
        self._gtk(home, "[Settings]\ngtk-icon-theme-name = 'Papirus'\n")

        assert_that(detect_theme("", home, dirs)).is_equal_to("Papirus")

    def test_garbage_settings_files_are_ignored(self, env) -> None:
        home, dirs = env
        self._gtk(home, "this is not an ini file")

        assert_that(detect_theme("", home, dirs)).is_equal_to("Adwaita")

    def test_nothing_installed_still_names_hicolor(self, tmp_path: Path) -> None:
        assert_that(detect_theme("", tmp_path, [tmp_path / "empty"])).is_equal_to("hicolor")


class TestBuildIndex:
    def test_groups_files_by_context_and_names_have_no_extension(self, tmp_path: Path) -> None:
        make_theme(
            tmp_path,
            "T",
            {
                "actions/scalable": {"Context": "Actions", "Size": "48", "Type": "Scalable"},
                "mimetypes/48": {"Context": "MimeTypes", "Size": "48", "Type": "Fixed"},
            },
            files=(
                "actions/scalable/edit-copy.svg",
                "actions/scalable/NOTE.txt",
                "mimetypes/48/org.gnome.Foo.png",
                "mimetypes/48/Upper.SVG",
            ),
        )

        index = build_index("T", [tmp_path])

        assert_that(sorted(index.icons["actions"])).is_equal_to(["edit-copy"])
        assert_that(sorted(index.icons["mimetypes"])).is_equal_to(["Upper", "org.gnome.Foo"])

    def test_scalable_beats_a_larger_raster_and_a_larger_raster_beats_a_smaller_one(self, tmp_path: Path) -> None:
        make_theme(
            tmp_path,
            "T",
            {
                "actions/16": {"Context": "Actions", "Size": "16", "Type": "Fixed"},
                "actions/64": {"Context": "Actions", "Size": "64", "Type": "Fixed"},
                "actions/scalable": {"Context": "Actions", "Size": "16", "Type": "Scalable", "MinSize": "8"},
            },
            files=(
                "actions/16/a.png",
                "actions/64/a.png",
                "actions/scalable/a.svg",
                "actions/16/b.png",
                "actions/64/b.png",
            ),
        )

        icons = build_index("T", [tmp_path]).icons["actions"]

        assert_that(icons["a"].parts[-3:]).is_equal_to(("actions", "scalable", "a.svg"))
        assert_that(icons["b"].parts[-3:]).is_equal_to(("actions", "64", "b.png"))

    def test_primary_beats_inherited_beats_hicolor_and_hicolor_only_names_are_found(self, tmp_path: Path) -> None:
        dirs = {"actions/scalable": {"Context": "Actions", "Size": "48", "Type": "Scalable"}}
        make_theme(tmp_path, "Child", dirs, inherits="Parent", files=("actions/scalable/shared.svg",))
        make_theme(tmp_path, "Parent", dirs, files=("actions/scalable/shared.svg", "actions/scalable/parent-only.svg"))
        make_theme(tmp_path, "hicolor", dirs, files=("actions/scalable/shared.svg", "actions/scalable/hi-only.svg"))

        icons = build_index("Child", [tmp_path]).icons["actions"]

        assert_that(icons["shared"].parts[-4]).is_equal_to("Child")
        assert_that(icons["parent-only"].parts[-4]).is_equal_to("Parent")
        assert_that(icons["hi-only"].parts[-4]).is_equal_to("hicolor")

    def test_missing_and_unknown_contexts_go_to_other(self, tmp_path: Path) -> None:
        make_theme(
            tmp_path,
            "T",
            {
                "misc": {"Size": "48", "Type": "Fixed"},
                "panel": {"Context": "Panel", "Size": "48", "Type": "Fixed"},
            },
            files=("misc/a.png", "panel/b.png"),
        )

        index = build_index("T", [tmp_path])

        assert_that(sorted(index.icons["other"])).is_equal_to(["a", "b"])

    def test_the_same_name_in_two_categories_is_kept_in_both(self, tmp_path: Path) -> None:
        make_theme(
            tmp_path,
            "T",
            {
                "actions/48": {"Context": "Actions", "Size": "48", "Type": "Fixed"},
                "places/48": {"Context": "Places", "Size": "48", "Type": "Fixed"},
            },
            files=("actions/48/folder.png", "places/48/folder.png"),
        )

        index = build_index("T", [tmp_path])

        assert_that(index.icons["actions"]).contains_key("folder")
        assert_that(index.icons["places"]).contains_key("folder")

    def test_a_theme_in_an_earlier_search_dir_wins(self, tmp_path: Path) -> None:
        dirs = {"actions/48": {"Context": "Actions", "Size": "48", "Type": "Fixed"}}
        make_theme(tmp_path / "user", "T", dirs, files=("actions/48/x.png",))
        make_theme(tmp_path / "system", "T", dirs, files=("actions/48/x.png", "actions/48/y.png"))

        icons = build_index("T", [tmp_path / "user", tmp_path / "system"]).icons["actions"]

        assert_that(icons["x"].parts[-5]).is_equal_to("user")
        assert_that(icons).contains_key("y")

    def test_a_missing_theme_gives_an_empty_index_and_a_missing_directory_is_skipped(self, tmp_path: Path) -> None:
        index = build_index("Nope", [tmp_path / "missing", tmp_path])

        assert_that(index.icons).is_empty()
        make_theme(tmp_path, "T", {"actions/48": {"Context": "Actions", "Size": "48"}}, files=())
        assert_that(build_index("T", [tmp_path]).icons.get("actions", {})).is_empty()

    def test_inherits_cycles_do_not_loop(self, tmp_path: Path) -> None:
        dirs = {"actions/48": {"Context": "Actions", "Size": "48", "Type": "Fixed"}}
        make_theme(tmp_path, "A", dirs, inherits="B", files=("actions/48/a.png",))
        make_theme(tmp_path, "B", dirs, inherits="A", files=("actions/48/b.png",))

        icons = build_index("A", [tmp_path]).icons["actions"]

        assert_that(sorted(icons)).is_equal_to(["a", "b"])

    def test_a_directory_listed_but_absent_on_disk_is_skipped(self, tmp_path: Path) -> None:
        make_theme(tmp_path, "T", {"gone/48": {"Context": "Actions", "Size": "48"}})

        assert_that(build_index("T", [tmp_path]).icons.get("actions", {})).is_empty()

    def test_version_has_the_theme_and_eight_hex_and_changes_with_the_index_mtime(self, tmp_path: Path) -> None:
        theme = make_theme(
            tmp_path, "T", {"actions/48": {"Context": "Actions", "Size": "48"}}, files=("actions/48/a.png",)
        )

        first = build_index("T", [tmp_path]).version
        os.utime(theme / "index.theme", ns=(1_000_000_000, 1_000_000_000))
        second = build_index("T", [tmp_path]).version

        assert_that(first).matches(r"^T-[0-9a-f]{8}$")
        assert_that(second).matches(r"^T-[0-9a-f]{8}$").is_not_equal_to(first)
