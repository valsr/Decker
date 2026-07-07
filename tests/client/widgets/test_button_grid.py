from assertpy import assert_that

from decker.client.widgets.button_grid import ButtonGridWidget, KeyButtonWidget
from decker.common.model import KeyInfo


def _make_keys(count: int, rows: int = 3, cols: int = 5) -> list[KeyInfo]:
    keys = []
    for i in range(count):
        keys.append(KeyInfo(row=i // cols, col=i % cols, pixel_width=72, pixel_height=72, type="key"))
    return keys


class TestButtonGridWidget:
    def test_build_creates_expected_number_of_buttons(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.build(_make_keys(15))
        assert_that(grid.key_count).is_equal_to(15)
        assert_that(grid._grid_layout.count()).is_equal_to(15)  # pylint: disable=protected-access

    def test_build_rebuilds_grid(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.build(_make_keys(6))
        grid.build(_make_keys(8))
        assert_that(grid._grid_layout.count()).is_equal_to(8)  # pylint: disable=protected-access

    def test_clicking_key_emits_key_selected(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.build(_make_keys(6))
        received: list[int] = []
        grid.key_selected.connect(received.append)

        layout_item = grid._grid_layout.itemAt(2)  # pylint: disable=protected-access
        assert layout_item is not None
        button = layout_item.widget()
        assert isinstance(button, KeyButtonWidget)
        button.click()

        assert_that(received).is_equal_to([2])

    def test_set_key_label_updates_button_text(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.build(_make_keys(6))
        grid.set_key_label(0, "42")
        button = grid._buttons.get(0)  # pylint: disable=protected-access
        assert button is not None
        assert_that(button.text()).is_equal_to("42")

    def test_set_key_label_for_missing_key_does_not_raise(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.build(_make_keys(6))
        grid.set_key_label(99, "x")  # should not raise


class TestKeyButtonWidget:
    def test_set_label_updates_display(self, qapp):  # pylint: disable=unused-argument
        btn = KeyButtonWidget(0, KeyInfo(row=0, col=0, pixel_width=72, pixel_height=72, type="key"))
        btn.set_label("99")
        assert_that(btn.text()).is_equal_to("99")

    def test_default_text_is_key_number(self, qapp):  # pylint: disable=unused-argument
        btn = KeyButtonWidget(4, KeyInfo(row=0, col=4, pixel_width=72, pixel_height=72, type="key"))
        assert_that(btn.text()).is_equal_to("5")
