"""The Switch card hosted by a real PluginManager: shown children, swaps, slot actions and stored state."""

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that

from decker.plugin.gestures import Gesture
from decker.plugin.loader import InstalledPlugin
from decker.plugin.manifest import PluginManifest
from decker.plugin.protocol import Message
from decker.plugin.settings_store import PluginSettingsStore
from decker.plugin.target import CardTarget
from decker.server.plugins import PluginManager
from tests.server.test_plugins import (
    _FAST,
    Env,
    FakeBus,
    FakeDeviceManager,
    FakePages,
    _pixel,
    _wait_for,
)

_KIDS = "com.t.kids"
_RED = f"{_KIDS}.red"
_BLUE = f"{_KIDS}.blue"
_GREEN = f"{_KIDS}.green"
_RECORD = f"{_KIDS}.record"
_KIDS_MANIFEST: dict[str, Any] = {
    "format": 2,
    "id": _KIDS,
    "name": "Kids",
    "version": "1.0.0",
    "author": "Decker",
    "contributes": {
        "cards": [
            {"id": _RED, "name": "Red", "static": True, "appearance": {"background": "#ff0000"}},
            {
                "id": _BLUE,
                "name": "Blue",
                "static": True,
                "appearance": {"background": "#0000ff", "title": {"text": "Blue", "position": "bottom"}},
            },
            {"id": _GREEN, "name": "Green", "static": True, "appearance": {"background": "#00ff00"}},
        ],
        "actions": [
            {"id": _RECORD, "name": "Record", "settings": [{"key": "n", "type": "int", "label": "N", "default": 0}]}
        ],
    },
}
_REC = "com.decker.rec"
_REC_CARD = "com.decker.rec.show"
_SWITCH = CardTarget("com.decker.core", "com.decker.core.switch", "sw", "dev-1", 3)
_SWITCH_2 = CardTarget("com.decker.core", "com.decker.core.switch", "sw2", "dev-1", 4)
_RED_RGB = (0xFF, 0x00, 0x00)
_BLUE_RGB = (0x00, 0x00, 0xFF)
_GREEN_RGB = (0x00, 0xFF, 0x00)


def _card(card: str, plugin: str = _KIDS, settings: dict[str, Any] | None = None, **appearance: Any) -> dict:
    return {"kind": "card", "plugin": plugin, "card": card, "settings": settings or {}, "appearance": appearance}


def _action(action: str, **settings: Any) -> dict[str, Any]:
    return {"kind": "action", "action": action, "settings": settings}


def _write_kids(plugins_dir: Path) -> Path:
    folder = plugins_dir / _KIDS
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps(_KIDS_MANIFEST))
    return folder


class SwitchEnv(Env):
    """The plugin test environment plus a removable plugin of static child cards and a recording action."""

    def __init__(self, tmp_path: Path) -> None:
        self.kids_dir = _write_kids(tmp_path / "plugins")
        super().__init__(tmp_path)
        self.tmp_path = tmp_path
        self.calls: list[dict[str, Any]] = []
        self.manager._action_runner._builtin = {_RECORD: lambda values: self.calls.append(dict(values))}

    def place(self, target: CardTarget = _SWITCH, appearance: dict[str, Any] | None = None, **slots: Any) -> None:
        self.manager.store_settings(target, {"slots": slots})
        self.manager.activate_card(target, appearance)

    def press(self, target: CardTarget = _SWITCH) -> None:
        self.manager.dispatch_key_down(target)
        self.manager.dispatch_key_up(target)

    def live(self) -> dict[str, Any]:
        return self.manager._live  # pylint: disable=protected-access

    def color(self, key: int = 3) -> tuple[int, ...]:
        return _pixel(self.image(key), 2, 2)

    def stored(self, target: CardTarget = _SWITCH) -> dict[str, Any]:
        return self.manager._settings_store.get_settings(target.plugin_uuid, target.card_uuid, target.context_id)


@pytest.fixture(name="env")
def env_fixture(tmp_path: Path) -> Any:
    environment = SwitchEnv(tmp_path)
    yield environment
    environment.manager.destroy()


def test_activating_switch_shows_display_card_face(env: SwitchEnv) -> None:
    env.place(display=_card(_RED), press=_card(_BLUE))

    assert_that(env.color()).is_equal_to(_RED_RGB)
    assert_that(env.live()).contains_key("sw", "sw:display")
    child = env.live()["sw:display"]
    assert_that(child.parent).is_equal_to("sw")
    assert_that((child.target.device_id, child.target.key_index, child.target.card_uuid)).is_equal_to(
        ("dev-1", 3, _RED)
    )


def test_press_on_card_slot_swaps_child_and_deactivates_old(env: SwitchEnv) -> None:
    env.place(display=_card(_RED), press=_card(_BLUE))

    env.press()

    assert_that(env.live()).does_not_contain_key("sw:display")
    assert_that(env.live()).contains_key("sw:press")
    assert_that(env.color()).is_equal_to(_BLUE_RGB)


def test_press_on_action_slot_runs_action_and_keeps_face(env: SwitchEnv) -> None:
    env.place(display=_card(_RED), press=_action(_RECORD, n=4))

    env.press()

    assert _wait_for(lambda: bool(env.calls))
    assert_that(env.calls).is_equal_to([{"n": 4}])
    assert_that(env.live()).contains_key("sw:display")
    assert_that(env.color()).is_equal_to(_RED_RGB)


def test_shown_card_survives_deactivate_and_reactivate(env: SwitchEnv) -> None:
    env.place(display=_card(_RED), press=_card(_BLUE))
    env.press()

    env.manager.deactivate_card(_SWITCH)
    env.manager.activate_card(_SWITCH)

    assert_that(env.live()).contains_key("sw:press")
    assert_that(env.color()).is_equal_to(_BLUE_RGB)


def test_new_manager_starts_from_display(env: SwitchEnv) -> None:
    env.place(display=_card(_RED), press=_card(_BLUE))
    env.press()
    dm = FakeDeviceManager()
    restarted = PluginManager(env.plugins_dir, _FAST, PluginSettingsStore(env.tmp_path / "plugins.db"))
    pages = FakePages()
    context = SimpleNamespace(
        device_manager=dm,
        event_bus=FakeBus(),
        page_controller=pages,
        page_store=pages,
        key_assignment_store=MagicMock(),
    )
    restarted.create(context)  # type: ignore[arg-type]
    try:
        restarted.activate_card(_SWITCH)

        assert_that(restarted._live).contains_key("sw:display")  # pylint: disable=protected-access
        assert_that(_pixel(dm.state.get_key_state(3).image, 2, 2)).is_equal_to(_RED_RGB)
    finally:
        restarted.destroy()


def test_child_receives_no_key_events(env: SwitchEnv) -> None:
    env.place(display=_card(_REC_CARD, _REC), long_press=_card(_BLUE), press=_card(_GREEN))
    assert _wait_for(lambda: env.received("will_appear"))
    assert_that(env.received("will_appear")[0]["context"]).is_equal_to("sw:display")

    with patch.object(env.manager, "_send_context", wraps=env.manager._send_context) as sent:
        env.manager.dispatch_key_down(_SWITCH)
        child = env.live()["sw:display"]
        env.manager.dispatch_key_up(_SWITCH)

    assert_that([call.args[0] for call in sent.call_args_list]).does_not_contain(child)
    assert_that(env.received("key_down") + env.received("key_up") + env.received("press")).is_empty()


def test_non_headless_child_is_told_it_appears_and_disappears(env: SwitchEnv) -> None:
    env.place(display=_card(_REC_CARD, _REC), press=_card(_BLUE))
    assert _wait_for(lambda: env.received("will_appear"))

    env.press()

    assert _wait_for(lambda: env.received("will_disappear"))
    assert_that(env.received("will_disappear")[0]["context"]).is_equal_to("sw:display")
    assert_that(env.color()).is_equal_to(_BLUE_RGB)


def test_empty_switch_draws_own_face_and_press_is_noop(env: SwitchEnv) -> None:
    env.place(appearance={"background": "#ffff00"})
    before = env.image()

    env.press()

    assert_that(env.color()).is_equal_to((0xFF, 0xFF, 0x00))
    assert_that(list(env.live())).is_equal_to(["sw"])
    assert_that(env.image()).is_equal_to(before)
    assert_that(env.live()["sw"].gestures).is_empty()


def test_uninstalled_slot_card_is_noop_and_stays_stored(env: SwitchEnv) -> None:
    gone = _card("com.t.gone.card", "com.t.gone")
    env.place(display=_card(_RED), press=gone, long_press=_action("com.t.gone.action"))

    env.press()

    assert_that(env.live()).contains_key("sw:display")
    assert_that(env.live()).does_not_contain_key("sw:press")
    assert_that(env.color()).is_equal_to(_RED_RGB)
    assert_that(env.live()["sw"].gestures).is_empty()
    assert_that(env.stored()["slots"]["press"]).is_equal_to(gone)
    assert_that(env.live()["sw"].settings["slots"]["press"]).is_equal_to(gone)


def test_double_press_slot_delays_press_but_press_only_does_not(env: SwitchEnv) -> None:
    env.place(display=_card(_RED), press=_card(_BLUE))
    env.place(_SWITCH_2, display=_card(_RED), press=_card(_BLUE), double_press=_card(_GREEN))

    env.press()
    env.press(_SWITCH_2)

    assert_that(env.live()["sw"].gestures).is_equal_to(frozenset({Gesture.PRESS}))
    assert_that(env.live()["sw2"].gestures).is_equal_to(frozenset({Gesture.PRESS, Gesture.DOUBLE_PRESS}))
    assert_that(env.live()).contains_key("sw:press")
    assert_that(env.live()).contains_key("sw2:display")
    assert _wait_for(lambda: "sw2:press" in env.live())


def test_child_set_settings_writes_back_into_slot(env: SwitchEnv) -> None:
    env.place(display=_card(_REC_CARD, _REC, {"n": 2}), press=_card(_BLUE))

    env.manager._on_plugin_message(_REC, Message("set_settings", "sw:display", {"settings": {"n": 7}}))

    assert_that(env.live()["sw:display"].settings["n"]).is_equal_to(7)
    assert_that(env.stored()["slots"]["display"]["settings"]["n"]).is_equal_to(7)
    assert_that(env.stored()["slots"]["press"]).is_equal_to(_card(_BLUE))
    target, settings = env.persisted[-1]
    assert_that(target.context_id).is_equal_to("sw")
    assert_that(settings["slots"]["display"]["settings"]["n"]).is_equal_to(7)
    assert_that(env.manager._settings_store.get_settings(_REC, _REC_CARD, "sw:display")).is_empty()


def test_deactivating_switch_deactivates_child(env: SwitchEnv) -> None:
    env.place(display=_card(_RED), press=_card(_BLUE))

    env.manager.deactivate_card(_SWITCH)

    assert_that(env.live()).is_empty()


def test_settings_changed_rebuilds_gestures_and_child(env: SwitchEnv) -> None:
    env.place(display=_card(_RED))
    assert_that(env.live()["sw"].gestures).is_empty()

    env.manager.store_settings(_SWITCH, {"slots": {"display": _card(_BLUE), "long_press": _action(_RECORD)}})
    env.manager.dispatch_settings_changed(_SWITCH)

    assert_that(env.live()["sw"].gestures).is_equal_to(frozenset({Gesture.LONG_PRESS}))
    assert_that(env.live()["sw:display"].target.card_uuid).is_equal_to(_BLUE)
    assert_that(env.color()).is_equal_to(_BLUE_RGB)


def test_key_display_states_report_the_switch_key_once(env: SwitchEnv) -> None:
    env.place(display=_card(_REC_CARD, _REC), press=_card(_RED), appearance={"background": "#123456"})
    env.manager._on_plugin_message(_REC, Message("set_title", "sw:display", {"title": "Hi"}))

    states = env.manager.get_key_display_states("dev-1")

    assert_that([(s["key_index"], s["label"]) for s in states]).is_equal_to([(3, "Hi")])
    appearance, _defaults = env.manager._key_appearance("dev-1", 3)
    assert_that(appearance["background"]["color"]).is_equal_to("#123456")


def test_uninstalling_child_plugin_reshows_switch(env: SwitchEnv) -> None:
    env.place(display=_card("com.decker.blank.blank", "com.decker.blank", background="#00ff00"), press=_card(_BLUE))
    env.press()
    assert_that([t.context_id for t in env.manager.live_targets(_KIDS)]).is_equal_to(["sw:press"])
    plugin = next(p for p in env.manager.plugins() if p.manifest.id == _KIDS)

    for target in env.manager.live_targets(_KIDS):
        env.manager.deactivate_card(target)
    env.manager.remove_plugin(_KIDS)

    assert_that(env.live()).contains_key("sw:display")
    assert_that(env.color()).is_equal_to(_GREEN_RGB)
    assert_that(env.stored()["slots"]["press"]).is_equal_to(_card(_BLUE))

    env.manager.add_plugin(InstalledPlugin(PluginManifest.from_dict(_KIDS_MANIFEST), plugin.plugin_dir))

    assert_that(env.live()).contains_key("sw:press")
    assert_that(env.live()).does_not_contain_key("sw:display")
    assert_that(env.color()).is_equal_to(_BLUE_RGB)


def test_preview_of_a_switch_shows_its_child_face(env: SwitchEnv) -> None:
    env.place(display=_card(_RED))

    preview = env.manager.preview_image(_SWITCH, {"background": "#ffff00"})

    assert_that(_pixel(preview, 2, 2)).is_equal_to(_RED_RGB)


def test_preview_of_an_empty_switch_uses_the_draft(env: SwitchEnv) -> None:
    env.place()

    preview = env.manager.preview_image(_SWITCH, {"background": "#ffff00"})

    assert_that(_pixel(preview, 2, 2)).is_equal_to((0xFF, 0xFF, 0x00))


def test_preview_of_switch_shows_display_card_face(env: SwitchEnv) -> None:
    env.place(display=_card(_RED), press=_card(_BLUE))
    env.press()  # the live Switch now remembers Press; a preview starts fresh

    preview = env.manager.preview_image(_SWITCH, {"background": "#ffff00"})

    assert_that(_pixel(preview, 2, 2)).is_equal_to(_RED_RGB)
    assert_that(env.live()).contains_key("sw:press").does_not_contain_key("sw:display")
    assert_that(env.color()).is_equal_to(_BLUE_RGB)


def test_preview_of_switch_without_display_shows_press_card_face(env: SwitchEnv) -> None:
    env.place(press=_card(_BLUE), long_press=_card(_GREEN))

    preview = env.manager.preview_image(_SWITCH, {})

    assert_that(_pixel(preview, 2, 2)).is_equal_to(_BLUE_RGB)


def test_preview_uses_draft_slots_and_leaves_live_state_alone(env: SwitchEnv) -> None:
    env.place(display=_card(_RED))
    child = env.live()["sw:display"]
    draft = {"slots": {"display": _card(_GREEN)}, "background": "#ffff00"}

    preview = env.manager.preview_image(_SWITCH, draft)

    assert_that(_pixel(preview, 2, 2)).is_equal_to(_GREEN_RGB)
    assert_that(env.live()["sw:display"]).is_same_as(child)
    assert_that(env.live()).is_length(2)
    assert_that(env.color()).is_equal_to(_RED_RGB)


def test_concurrent_presses_and_page_switches_leave_no_orphan_child(env: SwitchEnv) -> None:
    env.place(display=_card(_RED), press=_card(_BLUE), long_press=_card(_GREEN))
    stop = threading.Event()

    def _presser() -> None:
        while not stop.is_set():
            env.press()

    thread = threading.Thread(target=_presser, daemon=True)
    thread.start()
    try:
        for _ in range(50):
            env.manager.deactivate_card(_SWITCH)
            env.manager.activate_card(_SWITCH)
    finally:
        stop.set()
        thread.join(timeout=5)
    env.manager.deactivate_card(_SWITCH)

    assert_that(env.live()).is_empty()
