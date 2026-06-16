from unittest.mock import MagicMock

from assertpy import assert_that

from decker.plugin.events import PluginLoadFailedEvent
from decker.server.service import DeckerService


class TestPluginsLoadFailures:
    def test_returns_empty_list_when_no_plugin_manager_configured(self):
        DeckerService._plugin_manager = None  # pylint: disable=protected-access
        service = DeckerService()
        assert_that(service.plugins_load_failures()).is_equal_to([])

    def test_returns_failures_from_plugin_manager(self):
        manager = MagicMock()
        manager.load_failures.return_value = [PluginLoadFailedEvent(plugin_uuid="com.decker.broken", error="boom")]
        DeckerService.configure_plugin_manager(manager)
        service = DeckerService()
        try:
            result = service.plugins_load_failures()
            assert_that(result).is_equal_to([{"plugin_uuid": "com.decker.broken", "error": "boom"}])
        finally:
            DeckerService._plugin_manager = None  # pylint: disable=protected-access


class TestPluginsActionsList:
    def test_returns_empty_list_when_no_plugin_manager_configured(self):
        DeckerService._plugin_manager = None  # pylint: disable=protected-access
        service = DeckerService()
        assert_that(service.plugins_actions_list()).is_equal_to([])

    def test_returns_actions_from_plugin_manager(self):
        manager = MagicMock()
        manager.list_actions.return_value = [
            {"plugin_uuid": "p", "plugin_name": "P", "action_uuid": "p.a", "action_name": "A"}
        ]
        DeckerService.configure_plugin_manager(manager)
        service = DeckerService()
        try:
            result = service.plugins_actions_list()
            assert_that(result).is_equal_to(
                [{"plugin_uuid": "p", "plugin_name": "P", "action_uuid": "p.a", "action_name": "A"}]
            )
        finally:
            DeckerService._plugin_manager = None  # pylint: disable=protected-access
