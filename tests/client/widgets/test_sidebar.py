from assertpy import assert_that

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

    def test_device_switcher_button_exposed(self, qapp):  # pylint: disable=unused-argument
        sidebar = SidebarWidget()
        assert_that(sidebar.device_switcher_button).is_not_none()

    def test_button_signals_emit(self, qapp):  # pylint: disable=unused-argument
        sidebar = SidebarWidget()
        theme_calls = []
        settings_calls = []
        device_calls = []
        sidebar.theme_clicked.connect(lambda: theme_calls.append(1))
        sidebar.settings_clicked.connect(lambda: settings_calls.append(1))
        sidebar.device_switcher_clicked.connect(lambda: device_calls.append(1))

        sidebar.device_switcher_button.click()

        assert_that(device_calls).is_length(1)
        assert_that(theme_calls).is_empty()
        assert_that(settings_calls).is_empty()
