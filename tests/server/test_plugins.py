import base64
import json
import time
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that

from decker.plugin.context import ActionTarget
from decker.plugin.gestures import Gesture
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

    def on_press(self, ctx):
        ctx.set_state(4)
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


def _mock_context() -> MagicMock:
    ctx = MagicMock()
    ctx.device_manager = MagicMock()
    return ctx


@pytest.fixture
def manager(tmp_path, plugins_dir):
    mgr = PluginManager(plugins_dir)
    mgr._settings_store = mgr._settings_store.__class__(tmp_path / "plugins.db")  # pylint: disable=protected-access
    mgr.create(_mock_context())
    mgr._sink = MagicMock()  # pylint: disable=protected-access
    yield mgr
    mgr.destroy()


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
    mgr.create(_mock_context())
    mgr.process_instances = process_instances  # type: ignore[attr-defined]
    yield mgr
    mgr.destroy()


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
        actions = manager.list_actions()
        assert_that(actions).extracting("plugin_uuid").contains("com.decker.test")
        test_action = next(a for a in actions if a["plugin_uuid"] == "com.decker.test")
        assert_that(test_action).is_equal_to(
            {
                "plugin_uuid": "com.decker.test",
                "plugin_name": "Test",
                "action_uuid": "com.decker.test.show",
                "action_name": "Show",
                "icon_b64": "",
            }
        )

    def test_bundled_counter_action_has_its_icon(self, manager):
        counter = next(a for a in manager.list_actions() if a["action_uuid"] == "com.decker.counter.counter")

        assert base64.b64decode(counter["icon_b64"]).startswith(b"\x89PNG")

    def test_action_icons_are_read_once(self, manager, monkeypatch):
        manager.list_actions()
        monkeypatch.setattr("decker.server.plugins.read_icon", MagicMock(side_effect=AssertionError("re-read")))

        assert_that(manager.list_actions()).is_not_empty()

    def test_elgato_action_icon_is_included(self, elgato_manager, plugins_dir):
        icon_dir = plugins_dir / "com.elgato.cpu-monitor.sdPlugin" / "imgs"
        icon_dir.mkdir()
        (icon_dir / "show.png").write_bytes(b"\x89PNGdata")
        manifest = dict(
            _ELGATO_MANIFEST, Actions=[{"UUID": "com.elgato.cpu-monitor.show", "Name": "Show", "Icon": "imgs/show"}]
        )
        (plugins_dir / "com.elgato.cpu-monitor.sdPlugin" / "manifest.json").write_text(json.dumps(manifest))
        rescanned = PluginManager(plugins_dir)
        for discovered in rescanned._user_loader.scan().elgato:  # pylint: disable=protected-access
            rescanned._elgato_plugins[discovered.manifest.uuid] = discovered  # pylint: disable=protected-access

        show = next(a for a in rescanned.list_actions() if a["plugin_uuid"] == "com.elgato.cpu-monitor")

        assert_that(base64.b64decode(show["icon_b64"])).is_equal_to(b"\x89PNGdata")
        rescanned.destroy()

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

    def test_press_reaches_on_press_without_waiting(self, manager):
        manager.activate_action(_TARGET)
        manager.dispatch_key_down(_TARGET)
        manager._sink.reset_mock()  # pylint: disable=protected-access

        manager.dispatch_key_up(_TARGET)

        manager._sink.set_state.assert_called_with("dev-1", 0, 4)  # pylint: disable=protected-access

    def test_broken_gestures_falls_back_to_press_only(self, manager):
        manager.activate_action(_TARGET)
        instance = manager._registry.get(  # pylint: disable=protected-access
            _TARGET.plugin_uuid, _TARGET.action_uuid, _TARGET.context_id
        )
        instance.gestures = MagicMock(side_effect=RuntimeError("boom"))

        gestures = manager._registered_gestures(_TARGET)  # pylint: disable=protected-access

        assert_that(gestures).is_equal_to(frozenset({Gesture.PRESS}))

    def test_registered_gestures_for_unknown_target_is_empty(self, manager):
        assert_that(manager._registered_gestures(_UNKNOWN_TARGET)).is_empty()  # pylint: disable=protected-access

    def test_deactivate_drops_the_gesture_recognizer(self, manager):
        manager.activate_action(_TARGET)
        assert_that(manager._recognizers).contains_key(_TARGET.context_id)  # pylint: disable=protected-access

        manager.deactivate_action(_TARGET)

        assert_that(manager._recognizers).does_not_contain_key(_TARGET.context_id)  # pylint: disable=protected-access

    def test_counter_gestures_follow_double_step_setting(self, manager):
        target = ActionTarget(
            plugin_uuid="com.decker.counter",
            action_uuid="com.decker.counter.counter",
            context_id="ctr",
            device_id="dev-1",
            key_index=1,
        )
        manager.activate_action(target)

        assert_that(manager._registered_gestures(target)).does_not_contain(
            Gesture.DOUBLE_PRESS
        )  # pylint: disable=protected-access
        manager.store_settings(target, {"double_step": 5})
        assert_that(manager._registered_gestures(target)).contains(
            Gesture.DOUBLE_PRESS
        )  # pylint: disable=protected-access

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
