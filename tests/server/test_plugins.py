import json
import time
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that

from decker.plugin.context import ActionTarget
from decker.server.plugins import PluginManager

_MANIFEST = {
    "UUID": "com.decker.test",
    "Name": "Test",
    "Version": "1.0.0",
    "Author": "Decker",
    "Actions": [{"UUID": "com.decker.test.show", "Name": "Show"}],
}

_PLUGIN_PY = """
from decker.plugin import DeckerPlugin, action


@action("com.decker.test.show")
class ShowAction(DeckerPlugin):
    def on_will_appear(self, ctx):
        ctx.set_state(1)

    def on_key_down(self, ctx):
        ctx.set_state(2)

    def on_will_disappear(self, ctx):
        ctx.set_state(3)
"""

_TARGET = ActionTarget(
    plugin_uuid="com.decker.test",
    action_uuid="com.decker.test.show",
    context_id="ctx-1",
    device_id="dev-1",
    key_index=0,
)
_UNKNOWN_TARGET = ActionTarget(
    plugin_uuid="com.decker.test",
    action_uuid="com.decker.test.show",
    context_id="ctx-unknown",
    device_id="dev-1",
    key_index=0,
)


@pytest.fixture(autouse=True)
def _no_real_elgato_bridge(monkeypatch):
    monkeypatch.setattr("decker.server.plugins.ElgatoBridge", lambda *a, **k: MagicMock())


@pytest.fixture
def plugins_dir(tmp_path):
    plugin_dir = tmp_path / "com.decker.test"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.json").write_text(json.dumps(_MANIFEST))
    (plugin_dir / "plugin.py").write_text(_PLUGIN_PY)
    return tmp_path


@pytest.fixture
def manager(tmp_path, plugins_dir):
    mgr = PluginManager(plugins_dir)
    mgr._settings_store = mgr._settings_store.__class__(tmp_path / "plugins.db")  # pylint: disable=protected-access
    mgr._sink = MagicMock()  # pylint: disable=protected-access
    mgr.start()
    yield mgr
    mgr.stop()


_ELGATO_MANIFEST = {
    "UUID": "com.elgato.cpu-monitor",
    "Name": "CPU Monitor",
    "Version": "1.0.0",
    "Author": "Elgato",
    "Actions": [{"UUID": "com.elgato.cpu-monitor.show", "Name": "Show"}],
    "CodePath": "app.js",
}


@pytest.fixture
def elgato_manager(tmp_path, plugins_dir, monkeypatch):
    elgato_dir = plugins_dir / "com.elgato.cpu-monitor.sdPlugin"
    elgato_dir.mkdir()
    (elgato_dir / "manifest.json").write_text(json.dumps(_ELGATO_MANIFEST))

    process_instances = []

    class _FakeProcess:
        def __init__(self, config):
            self.config = config
            self.started = False
            self.stopped = False
            process_instances.append(self)

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    monkeypatch.setattr("decker.server.plugins.ElgatoPluginProcess", _FakeProcess)

    mgr = PluginManager(plugins_dir)
    mgr._settings_store = mgr._settings_store.__class__(tmp_path / "plugins.db")  # pylint: disable=protected-access
    mgr.start()
    mgr.process_instances = process_instances  # type: ignore[attr-defined]
    yield mgr
    mgr.stop()


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestPluginManagerLifecycle:
    def test_start_loads_native_plugin(self, manager):
        assert_that(manager.load_failures()).is_empty()
        assert_that(manager._native_plugins).contains_key("com.decker.test")  # pylint: disable=protected-access

    def test_list_actions_returns_native_plugin_actions(self, manager):
        assert_that(manager.list_actions()).is_equal_to(
            [
                {
                    "plugin_uuid": "com.decker.test",
                    "plugin_name": "Test",
                    "action_uuid": "com.decker.test.show",
                    "action_name": "Show",
                }
            ]
        )

    def test_activate_action_dispatches_on_will_appear(self, manager):
        manager.activate_action(_TARGET)
        assert _wait_for(lambda: manager._sink.set_state.called)  # pylint: disable=protected-access
        manager._sink.set_state.assert_called_with("dev-1", 0, 1)  # pylint: disable=protected-access

    def test_key_down_dispatches_to_live_instance(self, manager):
        manager.activate_action(_TARGET)
        _wait_for(lambda: manager._sink.set_state.called)  # pylint: disable=protected-access
        manager._sink.reset_mock()  # pylint: disable=protected-access
        manager.dispatch_key_down(_TARGET)
        assert _wait_for(lambda: manager._sink.set_state.called)  # pylint: disable=protected-access
        manager._sink.set_state.assert_called_with("dev-1", 0, 2)  # pylint: disable=protected-access

    def test_key_down_without_activation_is_noop(self, manager):
        manager.dispatch_key_down(_UNKNOWN_TARGET)
        time.sleep(0.05)
        manager._sink.set_state.assert_not_called()  # pylint: disable=protected-access

    def test_deactivate_dispatches_on_will_disappear_then_unregisters(self, manager):
        manager.activate_action(_TARGET)
        _wait_for(lambda: manager._sink.set_state.called)  # pylint: disable=protected-access
        manager._sink.reset_mock()  # pylint: disable=protected-access
        manager.deactivate_action(_TARGET)
        assert _wait_for(lambda: manager._sink.set_state.called)  # pylint: disable=protected-access
        manager._sink.set_state.assert_called_with("dev-1", 0, 3)  # pylint: disable=protected-access

        manager._sink.reset_mock()  # pylint: disable=protected-access
        manager.dispatch_key_down(_TARGET)
        time.sleep(0.05)
        manager._sink.set_state.assert_not_called()  # pylint: disable=protected-access

    def test_settings_persist_across_context(self, manager):
        manager.activate_action(_TARGET)
        _wait_for(lambda: manager._sink.set_state.called)  # pylint: disable=protected-access
        manager._settings_store.set_settings(  # pylint: disable=protected-access
            "com.decker.test", "com.decker.test.show", "ctx-1", {"v": 1}
        )
        assert_that(
            manager._settings_store.get_settings(  # pylint: disable=protected-access
                "com.decker.test", "com.decker.test.show", "ctx-1"
            )
        ).is_equal_to({"v": 1})


class TestElgatoActivation:
    def test_activate_unknown_plugin_is_noop(self, elgato_manager):
        elgato_manager.activate_elgato_action("com.elgato.unknown", "ctx-1")
        assert_that(elgato_manager.process_instances).is_empty()

    def test_activate_starts_process_on_first_context(self, elgato_manager):
        elgato_manager.activate_elgato_action("com.elgato.cpu-monitor", "ctx-1")
        assert_that(elgato_manager.process_instances).is_length(1)
        assert_that(elgato_manager.process_instances[0].started).is_true()

    def test_activate_does_not_spawn_second_process_for_second_context(self, elgato_manager):
        elgato_manager.activate_elgato_action("com.elgato.cpu-monitor", "ctx-1")
        elgato_manager.activate_elgato_action("com.elgato.cpu-monitor", "ctx-2")
        assert_that(elgato_manager.process_instances).is_length(1)

    def test_deactivate_unknown_plugin_is_noop(self, elgato_manager):
        elgato_manager.deactivate_elgato_action("com.elgato.unknown", "ctx-1")  # should not raise

    def test_deactivate_last_context_stops_process(self, elgato_manager):
        elgato_manager.activate_elgato_action("com.elgato.cpu-monitor", "ctx-1")
        elgato_manager.deactivate_elgato_action("com.elgato.cpu-monitor", "ctx-1")
        assert_that(elgato_manager.process_instances[0].stopped).is_true()

    def test_deactivate_keeps_process_alive_while_other_contexts_remain(self, elgato_manager):
        elgato_manager.activate_elgato_action("com.elgato.cpu-monitor", "ctx-1")
        elgato_manager.activate_elgato_action("com.elgato.cpu-monitor", "ctx-2")
        elgato_manager.deactivate_elgato_action("com.elgato.cpu-monitor", "ctx-1")
        assert_that(elgato_manager.process_instances[0].stopped).is_false()
