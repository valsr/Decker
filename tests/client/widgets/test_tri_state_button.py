from assertpy import assert_that
from PyQt6.QtWidgets import QAbstractButton

from decker.client.widgets.tri_state_button import (
    TriStateButton,
    colour_wheel_icon,
    cross_icon,
    image_icon,
)


def _btn(button: TriStateButton, index: int) -> QAbstractButton:
    found = button._group.button(index)  # pylint: disable=protected-access
    assert found is not None
    return found


def _press(button: TriStateButton, index: int) -> None:
    _btn(button, index).click()


def _button() -> TriStateButton:
    return TriStateButton([("a", "A", cross_icon()), ("b", "B", colour_wheel_icon()), ("c", "C", image_icon())])


class TestTriStateButton:
    def test_starts_on_the_first_entry(self, qapp):  # pylint: disable=unused-argument
        button = _button()

        assert_that(button.currentData()).is_equal_to("a")
        assert_that(button.findData("c")).is_equal_to(2)
        assert_that(button.findData("zzz")).is_equal_to(-1)

    def test_clicking_a_segment_selects_it_and_emits_once(self, qapp):  # pylint: disable=unused-argument
        button = _button()
        seen: list[int] = []
        button.currentIndexChanged.connect(seen.append)

        _press(button, 2)  # pylint: disable=protected-access
        _press(button, 2)  # pylint: disable=protected-access

        assert_that(button.currentData()).is_equal_to("c")
        assert_that(seen).is_equal_to([2])

    def test_set_current_index_presses_the_segment_exclusively(self, qapp):  # pylint: disable=unused-argument
        button = _button()
        button.setCurrentIndex(1)

        checked = [_btn(button, i).isChecked() for i in range(3)]  # pylint: disable=protected-access
        assert_that(checked).is_equal_to([False, True, False])
        button.setCurrentIndex(7)
        assert_that(button.currentData()).is_equal_to("b")
