from assertpy import assert_that
from PyQt6.QtWidgets import QToolButton, QVBoxLayout

from decker.client.widgets.sidebar import SidebarWidget

_ACTIONS = [
    {"plugin_uuid": "p", "plugin_name": "P", "action_uuid": "p.show", "action_name": "Show Clock"},
    {"plugin_uuid": "p", "plugin_name": "P", "action_uuid": "p.toggle", "action_name": "Toggle Light"},
]


class TestSidebarWidget:
    def test_set_actions_populates_list(self, qapp):  # pylint: disable=unused-argument
        sidebar = SidebarWidget()
        sidebar.set_actions(_ACTIONS)
        assert_that(sidebar._action_list.count()).is_equal_to(2)  # pylint: disable=protected-access

    def test_search_filters_case_insensitively(self, qapp):  # pylint: disable=unused-argument
        sidebar = SidebarWidget()
        sidebar.set_actions(_ACTIONS)

        sidebar._search.setText("clock")  # pylint: disable=protected-access

        assert_that(sidebar._action_list.count()).is_equal_to(1)  # pylint: disable=protected-access
        item = sidebar._action_list.item(0)  # pylint: disable=protected-access
        assert item is not None
        assert_that(item.text()).is_equal_to("Show Clock")

    def test_search_with_no_matches_clears_list(self, qapp):  # pylint: disable=unused-argument
        sidebar = SidebarWidget()
        sidebar.set_actions(_ACTIONS)

        sidebar._search.setText("nonexistent")  # pylint: disable=protected-access

        assert_that(sidebar._action_list.count()).is_equal_to(0)  # pylint: disable=protected-access

    def test_clearing_search_restores_full_list(self, qapp):  # pylint: disable=unused-argument
        sidebar = SidebarWidget()
        sidebar.set_actions(_ACTIONS)
        sidebar._search.setText("clock")  # pylint: disable=protected-access

        sidebar._search.setText("")  # pylint: disable=protected-access

        assert_that(sidebar._action_list.count()).is_equal_to(2)  # pylint: disable=protected-access

    def test_has_no_buttons_and_list_fills_remaining_space(self, qapp):  # pylint: disable=unused-argument
        sidebar = SidebarWidget()
        layout = sidebar.layout()
        assert isinstance(layout, QVBoxLayout)

        assert_that(sidebar.findChildren(QToolButton)).is_empty()
        assert_that(layout.stretch(layout.indexOf(sidebar._action_list))).is_equal_to(
            1
        )  # pylint: disable=protected-access
