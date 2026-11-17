import sqlite3
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that

from decker.common.model import ProfileInfo
from decker.server.pages import PageStore, initial_page_id


@pytest.fixture()
def store(tmp_path):
    s = PageStore(db_path=tmp_path / "test.db")
    s.create(MagicMock())
    yield s
    s.destroy()


def _ids(store, device="d"):
    return [p.profile_id for p in store.list_profiles(device)]


class TestProfiles:
    def test_first_profile_is_default_zero(self, store):
        assert_that(store.list_profiles("d")).is_equal_to([ProfileInfo(0, "Default", "")])
        assert_that([p.name for p in store.list_pages("d")]).is_equal_to(["Page 1"])
        assert_that(store.active_profile_id("d")).is_equal_to(0)

    def test_ids_are_lowest_unused_and_reused(self, store):
        first, second = store.add_profile("d"), store.add_profile("d")
        assert_that([first.profile_id, second.profile_id]).is_equal_to([1, 2])
        assert_that([first.name, second.name]).is_equal_to(["Profile 1", "Profile 2"])

        store.delete_profile("d", 1)
        reused = store.add_profile("d")

        assert_that(reused).is_equal_to(ProfileInfo(1, "Profile 1", ""))
        assert_that(_ids(store)).is_equal_to([0, 2, 1])

    def test_ids_are_per_device(self, store):
        store.add_profile("a")
        assert_that(store.add_profile("b").profile_id).is_equal_to(1)

    def test_new_profile_has_one_page_and_its_own_default(self, store):
        profile = store.add_profile("d", "Media")
        pages = store.list_pages("d", profile.profile_id)

        assert_that(profile.name).is_equal_to("Media")
        assert_that([p.name for p in pages]).is_equal_to(["Page 1"])
        assert_that(store.default_page_id("d", profile.profile_id)).is_equal_to(pages[0].page_id)

    def test_pages_are_scoped_to_profile(self, store):
        profile = store.add_profile("d")
        extra = store.add_page("d", "Extra", profile_id=profile.profile_id)

        assert_that([p.name for p in store.list_pages("d", 0)]).is_equal_to(["Page 1"])
        assert_that(store.list_pages("d", profile.profile_id)).contains(extra)
        assert_that(store.list_pages("d")).does_not_contain(extra)

        store.set_active_profile("d", profile.profile_id)

        assert_that(store.list_pages("d")).contains(extra)

    def test_get_finds_page_in_any_profile(self, store):
        profile = store.add_profile("d")
        page = store.list_pages("d", profile.profile_id)[0]

        assert_that(store.get("d", page.page_id)).is_equal_to(page)
        assert_that(store.get("other", page.page_id)).is_none()

    def test_profile_of_page(self, store):
        profile = store.add_profile("d")
        page = store.list_pages("d", profile.profile_id)[0]

        assert_that(store.profile_of_page("d", page.page_id)).is_equal_to(profile.profile_id)
        assert_that(store.profile_of_page("d", initial_page_id("d"))).is_equal_to(0)
        assert_that(store.profile_of_page("d", "nope")).is_none()

    def test_set_default_page_applies_to_the_pages_profile(self, store):
        profile = store.add_profile("d")
        extra = store.add_page("d", "Extra", profile_id=profile.profile_id)

        assert_that(store.set_default_page("d", extra.page_id)).is_true()

        assert_that(store.default_page_id("d", profile.profile_id)).is_equal_to(extra.page_id)
        assert_that(store.default_page_id("d", 0)).is_equal_to(initial_page_id("d"))

    def test_last_page_of_a_profile_cannot_be_deleted_but_other_profiles_pages_can(self, store):
        profile = store.add_profile("d")
        only = store.list_pages("d", profile.profile_id)[0]
        assert_that(store.delete_page("d", only.page_id)).is_false()

        extra = store.add_page("d", profile_id=profile.profile_id)
        assert_that(store.delete_page("d", only.page_id)).is_true()
        assert_that(store.default_page_id("d", profile.profile_id)).is_equal_to(extra.page_id)

    def test_rename_profile_rejects_blank_and_unknown(self, store):
        assert_that(store.rename_profile("d", 0, "Work")).is_true()
        assert_that(store.get_profile("d", 0).name).is_equal_to("Work")
        assert_that(store.rename_profile("d", 0, "  ")).is_false()
        assert_that(store.rename_profile("d", 9, "X")).is_false()

    def test_set_icon(self, store):
        store.list_profiles("d")
        assert_that(store.set_profile_icon("d", 0, "pack:a/b.svg")).is_true()
        assert_that(store.get_profile("d", 0).icon).is_equal_to("pack:a/b.svg")
        assert_that(store.set_profile_icon("d", 5, "")).is_false()

    def test_cannot_delete_last_profile(self, store):
        store.list_profiles("d")
        assert_that(store.delete_profile("d", 0)).is_empty()
        assert_that(_ids(store)).is_equal_to([0])

    def test_delete_unknown_profile(self, store):
        store.add_profile("d")
        assert_that(store.delete_profile("d", 9)).is_empty()

    def test_delete_profile_removes_pages_and_default_and_returns_page_ids(self, store):
        profile = store.add_profile("d")
        extra = store.add_page("d", "Extra", profile_id=profile.profile_id)
        store.set_default_page("d", extra.page_id)
        page_ids = {p.page_id for p in store.list_pages("d", profile.profile_id)}

        deleted = store.delete_profile("d", profile.profile_id)

        assert_that(set(deleted)).is_equal_to(page_ids)
        assert_that(store.get("d", extra.page_id)).is_none()
        assert_that(_ids(store)).is_equal_to([0])

    def test_delete_active_profile_falls_back_to_first(self, store):
        profile = store.add_profile("d")
        store.set_active_profile("d", profile.profile_id)

        store.delete_profile("d", profile.profile_id)

        assert_that(store.active_profile_id("d")).is_equal_to(0)

    def test_set_active_profile_rejects_unknown(self, store):
        store.list_profiles("d")
        assert_that(store.set_active_profile("d", 4)).is_false()
        assert_that(store.active_profile_id("d")).is_equal_to(0)

    def test_active_profile_persists_across_reopen(self, tmp_path):
        first = PageStore(db_path=tmp_path / "test.db")
        first.create(MagicMock())
        profile = first.add_profile("d")
        first.set_active_profile("d", profile.profile_id)
        first.destroy()

        second = PageStore(db_path=tmp_path / "test.db")
        second.create(MagicMock())

        assert_that(second.active_profile_id("d")).is_equal_to(profile.profile_id)
        second.destroy()


class TestCloneProfile:
    def test_clone_copies_pages_default_icon_and_returns_mapping(self, store):
        store.list_profiles("d")
        store.set_profile_icon("d", 0, "pack:a/b.svg")
        second = store.add_page("d", "Second")
        store.set_default_page("d", second.page_id)
        original = store.list_pages("d", 0)

        clone, mapping = store.clone_profile("d", 0)

        assert_that(clone).is_equal_to(ProfileInfo(1, "Default copy", "pack:a/b.svg"))
        cloned = store.list_pages("d", 1)
        assert_that([p.name for p in cloned]).is_equal_to(["Page 1", "Second"])
        assert_that(set(mapping)).is_equal_to({p.page_id for p in original})
        assert_that({p.page_id for p in cloned} & {p.page_id for p in original}).is_empty()
        assert_that(store.default_page_id("d", 1)).is_equal_to(mapping[second.page_id])
        assert_that(_ids(store)).is_equal_to([0, 1])

    def test_clone_names_are_uniquified(self, store):
        store.list_profiles("d")
        first, _ = store.clone_profile("d", 0)
        second, _ = store.clone_profile("d", 0)

        assert_that([first.name, second.name]).is_equal_to(["Default copy", "Default copy 2"])

    def test_clone_unknown_profile(self, store):
        assert_that(store.clone_profile("d", 7)).is_none()


class TestMigration:
    @staticmethod
    def _legacy_db(path):
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE pages (page_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, name TEXT NOT NULL, position INTEGER NOT NULL)"
        )
        conn.execute("CREATE TABLE page_defaults (device_id TEXT PRIMARY KEY, page_id TEXT NOT NULL)")
        conn.executemany(
            "INSERT INTO pages VALUES (?, ?, ?, ?)",
            [("p1", "d", "One", 0), ("p2", "d", "Two", 1), ("q1", "e", "Solo", 0)],
        )
        conn.execute("INSERT INTO page_defaults VALUES ('d', 'p2')")
        conn.commit()
        conn.close()

    def test_migration_from_pre_profile_database(self, tmp_path):
        self._legacy_db(tmp_path / "t.db")
        store = PageStore(db_path=tmp_path / "t.db")
        store.create(MagicMock())

        assert_that(store.list_profiles("d")).is_equal_to([ProfileInfo(0, "Default", "")])
        assert_that([p.page_id for p in store.list_pages("d")]).is_equal_to(["p1", "p2"])
        assert_that(store.default_page_id("d")).is_equal_to("p2")
        assert_that(store.active_profile_id("d")).is_equal_to(0)
        assert_that([p.page_id for p in store.list_pages("e")]).is_equal_to(["q1"])
        store.destroy()

    def test_migration_is_idempotent(self, tmp_path):
        self._legacy_db(tmp_path / "t.db")
        for _ in range(2):
            store = PageStore(db_path=tmp_path / "t.db")
            store.create(MagicMock())
            assert_that(_ids(store, "d")).is_equal_to([0])
            assert_that([p.page_id for p in store.list_pages("d")]).is_equal_to(["p1", "p2"])
            assert_that(store.default_page_id("d")).is_equal_to("p2")
            store.destroy()


class TestAddPageValidation:
    def test_unknown_profile_is_refused_and_leaves_no_orphan(self, store):
        store.list_profiles("d")

        with pytest.raises(ValueError):
            store.add_page("d", "X", profile_id=42)

        assert_that(store.list_pages("d", 42)).is_empty()
        assert_that([p.name for p in store.list_pages("d")]).is_equal_to(["Page 1"])
