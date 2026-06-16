from assertpy import assert_that

from decker.client.widgets.button_grid import (
    ButtonGridWidget,
    KeyButtonWidget,
    grid_dimensions_for_key_count,
)


class TestGridDimensionsForKeyCount:
    def test_known_layout_6(self):
        assert_that(grid_dimensions_for_key_count(6)).is_equal_to((2, 3))

    def test_known_layout_15(self):
        assert_that(grid_dimensions_for_key_count(15)).is_equal_to((3, 5))

    def test_known_layout_32(self):
        assert_that(grid_dimensions_for_key_count(32)).is_equal_to((4, 8))

    def test_zero_keys(self):
        assert_that(grid_dimensions_for_key_count(0)).is_equal_to((0, 0))

    def test_unknown_count_falls_back_to_near_square(self):
        rows, cols = grid_dimensions_for_key_count(10)
        assert_that(rows * cols).is_greater_than_or_equal_to(10)


class TestButtonGridWidget:
    def test_set_key_count_creates_expected_number_of_buttons(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.set_key_count(15)
        assert_that(grid.key_count).is_equal_to(15)
        assert_that(grid._grid_layout.count()).is_equal_to(15)  # pylint: disable=protected-access

    def test_set_key_count_rebuilds_grid(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.set_key_count(6)
        grid.set_key_count(8)
        assert_that(grid._grid_layout.count()).is_equal_to(8)  # pylint: disable=protected-access

    def test_clicking_key_emits_key_selected(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.set_key_count(6)
        received: list[int] = []
        grid.key_selected.connect(received.append)

        layout_item = grid._grid_layout.itemAt(2)  # pylint: disable=protected-access
        assert layout_item is not None
        button = layout_item.widget()
        assert isinstance(button, KeyButtonWidget)
        button.click()

        assert_that(received).is_equal_to([2])
