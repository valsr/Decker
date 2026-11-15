"""Tests for decker.client.view_name."""

from assertpy import assert_that

from decker.client.view_name import ViewName


class TestViewName:
    def test_covers_all_views(self):
        assert_that({v.value for v in ViewName}).is_equal_to({"connecting", "dashboard", "device", "error"})

    def test_invalid_name_raises_value_error(self):
        assert_that(ViewName).raises(ValueError).when_called_with("not-a-view")
