from unittest.mock import MagicMock

import pytest
from assertpy import assert_that

from decker.common.model import PageInfo
from decker.server.pages import PageStore, initial_page_id


@pytest.fixture()
def store(tmp_path):
    s = PageStore(db_path=tmp_path / "test.db")
    s.create(MagicMock())
    yield s
    s.destroy()


class TestListPages:
    def test_device_starts_with_page_one(self, store):
        assert_that(store.list_pages("dev1")).is_equal_to([PageInfo(page_id=initial_page_id("dev1"), name="Page 1")])

    def test_seeding_is_idempotent_and_per_device(self, store):
        store.list_pages("dev1")

        assert_that(store.list_pages("dev1")).is_length(1)
        assert_that(store.list_pages("dev2")[0].page_id).is_equal_to(initial_page_id("dev2"))

    def test_pages_persist_across_reopen(self, tmp_path):
        first = PageStore(db_path=tmp_path / "test.db")
        first.create(MagicMock())
        page = first.add_page("dev1", "Media")
        first.destroy()

        second = PageStore(db_path=tmp_path / "test.db")
        second.create(MagicMock())

        assert_that(second.list_pages("dev1")).contains(page)
        second.destroy()


class TestAddPage:
    def test_appends_with_next_free_number(self, store):
        store.add_page("dev1")

        assert_that([p.name for p in store.list_pages("dev1")]).is_equal_to(["Page 1", "Page 2"])

    def test_fills_gap_in_numbering(self, store):
        second = store.add_page("dev1")
        store.add_page("dev1")
        store.delete_page("dev1", second.page_id)

        assert_that(store.add_page("dev1").name).is_equal_to("Page 2")

    def test_uses_given_name_and_appends_after_last(self, store):
        store.add_page("dev1", "A")
        page = store.add_page("dev1", "  Media  ")

        assert_that(page.name).is_equal_to("Media")
        assert_that(store.list_pages("dev1")[-1]).is_equal_to(page)

    def test_blank_name_falls_back_to_numbering(self, store):
        assert_that(store.add_page("dev1", "   ").name).is_equal_to("Page 2")


class TestRenamePage:
    def test_rename(self, store):
        page_id = store.list_pages("dev1")[0].page_id

        assert_that(store.rename_page("dev1", page_id, " Home ")).is_true()
        assert_that(store.get("dev1", page_id)).is_equal_to(PageInfo(page_id=page_id, name="Home"))

    @pytest.mark.parametrize("name", ["", "  "])
    def test_rejects_blank(self, store, name):
        page_id = store.list_pages("dev1")[0].page_id

        assert_that(store.rename_page("dev1", page_id, name)).is_false()

    def test_rejects_unknown_or_other_devices_page(self, store):
        other = store.list_pages("dev2")[0].page_id

        assert_that(store.rename_page("dev1", "nope", "x")).is_false()
        assert_that(store.rename_page("dev1", other, "x")).is_false()


class TestDeletePage:
    def test_delete(self, store):
        page = store.add_page("dev1")

        assert_that(store.delete_page("dev1", page.page_id)).is_true()
        assert_that(store.get("dev1", page.page_id)).is_none()

    def test_cannot_delete_last_page(self, store):
        only = store.list_pages("dev1")[0].page_id

        assert_that(store.delete_page("dev1", only)).is_false()

    def test_cannot_delete_unknown_page(self, store):
        store.add_page("dev1")

        assert_that(store.delete_page("dev1", "nope")).is_false()

    def test_deleting_default_falls_back_to_first_page(self, store):
        first = store.list_pages("dev1")[0].page_id
        page = store.add_page("dev1")
        store.set_default_page("dev1", page.page_id)

        store.delete_page("dev1", page.page_id)

        assert_that(store.default_page_id("dev1")).is_equal_to(first)


class TestDefaultPage:
    def test_first_page_is_default(self, store):
        assert_that(store.default_page_id("dev1")).is_equal_to(initial_page_id("dev1"))

    def test_set_default(self, store):
        page = store.add_page("dev1")

        assert_that(store.set_default_page("dev1", page.page_id)).is_true()
        assert_that(store.default_page_id("dev1")).is_equal_to(page.page_id)

    def test_set_default_rejects_unknown_page(self, store):
        assert_that(store.set_default_page("dev1", "nope")).is_false()
