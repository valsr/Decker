"""User icon ids and the user-icon store."""

from pathlib import Path

from assertpy import assert_that

from decker.asset.usericons import UserIcons, normalize_id


def test_normalize_id_lowercases_and_replaces_runs_of_other_characters() -> None:
    assert_that(normalize_id("Ünïcode Cat!")).is_equal_to("n-code-cat")
    assert_that(normalize_id("My  Icon")).is_equal_to("my-icon")


def test_normalize_id_strips_path_traversal() -> None:
    assert_that(normalize_id("../../etc/x")).is_equal_to("etc-x")


def test_normalize_id_returns_empty_for_blank_or_symbols_only() -> None:
    assert_that(normalize_id("   ")).is_equal_to("")
    assert_that(normalize_id("!!!")).is_equal_to("")


def test_normalize_id_truncates_to_64() -> None:
    assert_that(normalize_id("a" * 100)).is_equal_to("a" * 64)
    assert_that(normalize_id("a" * 63 + "!b")).is_equal_to("a" * 63)


def test_exists_is_true_across_extensions(tmp_path: Path) -> None:
    (tmp_path / "cat.gif").write_bytes(b"x")
    icons = UserIcons(tmp_path)
    assert_that(icons.exists("cat")).is_true()
    assert_that(icons.exists("dog")).is_false()


def test_suggest_id_appends_the_first_free_number(tmp_path: Path) -> None:
    (tmp_path / "cat.png").write_bytes(b"x")
    (tmp_path / "cat-2.png").write_bytes(b"x")
    icons = UserIcons(tmp_path)
    assert_that(icons.suggest_id("Cat")).is_equal_to("cat-3")
    assert_that(icons.suggest_id("Dog")).is_equal_to("dog")
    assert_that(icons.suggest_id("!!!")).is_equal_to("icon")


def test_list_icons_ignores_other_files_and_sorts(tmp_path: Path) -> None:
    for name in ("b.png", "a.svg", "c.gif", "d.txt", "e.jpg"):
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "sub.png").mkdir()
    assert_that(UserIcons(tmp_path).list_icons()).is_equal_to(["a.svg", "b.png", "c.gif"])


def test_list_icons_is_empty_when_directory_is_missing(tmp_path: Path) -> None:
    assert_that(UserIcons(tmp_path / "none").list_icons()).is_empty()


def test_read_icon_refuses_names_outside_the_listing(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(b"data")
    (tmp_path.parent / "x.png").write_bytes(b"secret")
    icons = UserIcons(tmp_path)
    assert_that(icons.read_icon("a.png")).is_equal_to(b"data")
    assert_that(icons.read_icon("../x.png")).is_none()
    assert_that(icons.read_icon("nope.png")).is_none()


def test_pack_info_counts_icons_and_lists_when_empty(tmp_path: Path) -> None:
    icons = UserIcons(tmp_path)
    info = icons.pack_info()
    assert_that(info).contains_entry({"id": "decker.user"}, {"name": "User"}, {"icon_count": 0})
    (tmp_path / "a.png").write_bytes(b"x")
    assert_that(icons.pack_info()["icon_count"]).is_equal_to(1)
    assert_that(info).contains_key("description", "plugin_id", "plugin_name", "plugin_version")


def test_default_directory_follows_the_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("decker.asset.usericons.user_icons", lambda: tmp_path)
    (tmp_path / "a.png").write_bytes(b"x")
    assert_that(UserIcons().list_icons()).is_equal_to(["a.png"])
