from assertpy import assert_that

from decker.client.mock_page_model import MockPageModel
from decker.client.widgets.page_pill_bar import PagePillBar


class TestPagePillBar:
    def test_set_pages_creates_one_pill_per_page(self, qapp):  # pylint: disable=unused-argument
        bar = PagePillBar()
        pages = MockPageModel(key_count=6).pages

        bar.set_pages(pages)

        assert_that(bar.button_group.buttons()).is_length(2)

    def test_first_pill_checked_by_default(self, qapp):  # pylint: disable=unused-argument
        bar = PagePillBar()
        pages = MockPageModel(key_count=6).pages

        bar.set_pages(pages)

        checked = bar.button_group.checkedButton()
        assert_that(checked).is_not_none()
        assert checked is not None
        assert_that(checked.text()).is_equal_to(pages[0].name)

    def test_exactly_one_pill_checked_after_clicking_another(self, qapp):  # pylint: disable=unused-argument
        bar = PagePillBar()
        pages = MockPageModel(key_count=6).pages
        bar.set_pages(pages)

        bar.button_group.buttons()[1].click()

        checked = bar.button_group.checkedButton()
        assert checked is not None
        assert_that(checked.text()).is_equal_to(pages[1].name)
        assert_that(sum(1 for b in bar.button_group.buttons() if b.isChecked())).is_equal_to(1)

    def test_clicking_pill_emits_page_selected_with_page_id(self, qapp):  # pylint: disable=unused-argument
        bar = PagePillBar()
        pages = MockPageModel(key_count=6).pages
        bar.set_pages(pages)
        received: list[str] = []
        bar.page_selected.connect(received.append)

        bar.button_group.buttons()[1].click()

        assert_that(received).is_equal_to([pages[1].page_id])

    def test_set_pages_replaces_previous_pills(self, qapp):  # pylint: disable=unused-argument
        bar = PagePillBar()
        bar.set_pages(MockPageModel(key_count=6).pages)
        bar.set_pages(MockPageModel(key_count=6).pages)
        assert_that(bar.button_group.buttons()).is_length(2)

    def test_gear_menu_has_four_actions(self, qapp):  # pylint: disable=unused-argument
        bar = PagePillBar()
        labels = [action.text() for action in bar.gear_menu.actions()]
        assert_that(labels).is_equal_to(["Add Page", "Delete Page", "Rename Page", "Set as Default"])

    def test_gear_menu_actions_trigger_signals(self, qapp):  # pylint: disable=unused-argument
        bar = PagePillBar()
        calls = {"add": 0, "delete": 0, "rename": 0, "default": 0}
        bar.add_page_requested.connect(lambda: calls.__setitem__("add", calls["add"] + 1))
        bar.delete_page_requested.connect(lambda: calls.__setitem__("delete", calls["delete"] + 1))
        bar.rename_page_requested.connect(lambda: calls.__setitem__("rename", calls["rename"] + 1))
        bar.set_default_page_requested.connect(lambda: calls.__setitem__("default", calls["default"] + 1))

        for action in bar.gear_menu.actions():
            action.trigger()

        assert_that(calls).is_equal_to({"add": 1, "delete": 1, "rename": 1, "default": 1})

    def test_sidebar_toggle_requested_emitted_on_click(self, qapp):  # pylint: disable=unused-argument
        bar = PagePillBar()
        received = []
        bar.sidebar_toggle_requested.connect(lambda: received.append(1))

        bar._toggle_button.click()  # pylint: disable=protected-access

        assert_that(received).is_length(1)
