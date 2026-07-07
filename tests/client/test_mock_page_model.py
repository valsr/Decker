from assertpy import assert_that

from decker.client.mock_page_model import MockPageModel


class TestMockPageModel:
    def test_provides_two_pages(self):
        model = MockPageModel(key_count=15)
        assert_that(model.pages).is_length(2)

    def test_pages_have_expected_names(self):
        model = MockPageModel(key_count=15)
        names = [page.name for page in model.pages]
        assert_that(names).is_equal_to(["Page 1", "Page 2"])

    def test_pages_have_unique_ids(self):
        model = MockPageModel(key_count=15)
        ids = [page.page_id for page in model.pages]
        assert_that(len(set(ids))).is_equal_to(2)

    def test_slots_match_key_count(self):
        model = MockPageModel(key_count=6)
        for page in model.pages:
            assert_that(page.slots).is_length(6)
            assert_that(page.key_count).is_equal_to(6)
