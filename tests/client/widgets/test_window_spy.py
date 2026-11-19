"""Tests for decker.client.widgets.window_spy.WindowSpyDialog."""

from typing import Any

import pytest
from assertpy import assert_that
from PyQt6.QtWidgets import QApplication

from decker.client.events import DetectionStatusEvent
from decker.client.widgets.profiles_dialog import ProfilesDialog
from decker.client.widgets.window_spy import WindowSpyDialog, rule_from_window
from decker.common.model import (
    AppRule,
    DefaultRule,
    DeviceProfiles,
    DeviceRules,
    PageInfo,
    ProfileInfo,
    WindowInfo,
)

# pylint: disable=protected-access,redefined-outer-name,unused-argument

OWN_PID = 100
_KONSOLE = WindowInfo("konsole", "normal", "Shell", "/usr/bin/konsole", "org.kde.konsole", 42)
_OWN = WindowInfo("decker", "normal", "Decker", "/usr/bin/decker", "", OWN_PID)
_DIALOG = WindowInfo("firefox", "dialog", "Open", "/usr/bin/firefox", "firefox.desktop", 7)


def _status(state: str = "active", backend: str = "kwin", pick: bool = True, reason: str = "") -> DetectionStatusEvent:
    return DetectionStatusEvent(state, reason, backend, pick, None)


class Picker:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.calls = 0

    def __call__(self) -> bool:
        self.calls += 1
        return self.result


@pytest.fixture()
def picker() -> Picker:
    return Picker()


@pytest.fixture()
def spy(qapp, picker):
    dlg = WindowSpyDialog(picker, OWN_PID)
    dlg.set_status(_status())
    dlg.show()
    yield dlg
    dlg.close()


def _value(spy: WindowSpyDialog, field: str) -> str:
    return spy._values[field].text()


def _tick(spy: WindowSpyDialog, times: int) -> None:
    for _ in range(times):
        spy._tick_timer.timeout.emit()


def test_pick_button_calls_window_pick_and_shows_result(spy, picker):
    spy._pick_button.click()

    assert_that(picker.calls).is_equal_to(1)
    assert_that(spy._pick_button.isEnabled()).is_false()
    assert_that(spy._message.text()).contains("Click a window").contains("Escape")

    spy.on_picked(_KONSOLE)

    assert_that(_value(spy, "window_class")).is_equal_to("konsole")
    assert_that(_value(spy, "pid")).is_equal_to("42")
    assert_that(spy._pick_button.isEnabled()).is_true()


def test_refused_pick_shows_message_and_reenables(qapp):
    dlg = WindowSpyDialog(Picker(False), OWN_PID)
    dlg.set_status(_status())

    dlg._pick_button.click()

    assert_that(dlg._message.text()).is_not_empty()
    assert_that(dlg._pick_button.isEnabled()).is_true()


def test_cancelled_pick_keeps_previous_window(spy):
    spy.on_picked(_KONSOLE)
    spy._pick_button.click()

    spy.on_picked(None)

    assert_that(_value(spy, "window_class")).is_equal_to("konsole")
    assert_that(spy._message.text()).is_equal_to("Pick cancelled")
    assert_that(spy._pick_button.isEnabled()).is_true()


def test_capture_mode_when_pick_unsupported_ignores_own_pid(spy, picker):
    spy.set_status(_status(backend="x11", pick=False))
    assert_that(spy._pick_button.isHidden()).is_true()
    assert_that(spy._capture_button.isHidden()).is_false()

    spy._capture_button.click()
    assert_that(spy._capture_button.text()).contains("3")
    _tick(spy, 1)
    assert_that(spy._capture_button.text()).contains("2")
    _tick(spy, 2)
    spy.on_focused(_OWN)
    assert_that(_value(spy, "window_class")).is_equal_to("")

    spy.on_focused(_KONSOLE)
    assert_that(_value(spy, "window_class")).is_equal_to("konsole")
    spy.on_focused(_DIALOG)
    assert_that(_value(spy, "window_class")).is_equal_to("konsole")
    assert_that(spy._capture_button.isEnabled()).is_true()
    assert_that(picker.calls).is_equal_to(0)


def test_capture_times_out(spy):
    spy.set_status(_status(pick=False))
    spy._capture_button.click()
    _tick(spy, 3)

    spy._timeout_timer.timeout.emit()
    spy.on_focused(_KONSOLE)

    assert_that(spy._message.text()).contains("timed out")
    assert_that(_value(spy, "window_class")).is_equal_to("")
    assert_that(spy._capture_button.isEnabled()).is_true()


def test_follow_ignores_own_pid(spy):
    spy.set_status(_status(pick=False))
    spy.on_focused(_KONSOLE)
    assert_that(_value(spy, "window_class")).is_equal_to("")

    spy._follow.setChecked(True)
    spy.on_focused(_KONSOLE)
    spy.on_focused(_OWN)
    assert_that(_value(spy, "window_class")).is_equal_to("konsole")

    spy.on_focused(_DIALOG)
    assert_that(_value(spy, "window_class")).is_equal_to("firefox")


def test_unsupported_fields_greyed(spy):
    spy.set_status(_status(backend="windows"))
    spy.on_picked(_KONSOLE)

    assert_that(_value(spy, "desktop_file")).is_equal_to("not available on this system")
    assert_that(spy._values["desktop_file"].isEnabled()).is_false()
    assert_that(spy._copy_buttons["desktop_file"].isEnabled()).is_false()
    assert_that(spy._values["title"].isEnabled()).is_true()


def test_disabled_with_reason_when_unavailable(spy):
    spy.set_status(_status(state="unavailable", reason="no portal", pick=False))

    assert_that(spy._pick_button.isEnabled()).is_false()
    assert_that(spy._capture_button.isEnabled()).is_false()
    assert_that(spy._follow.isEnabled()).is_false()
    assert_that(spy._message.text()).contains("no portal")


def test_copy_button_copies_value(spy):
    spy.on_picked(_KONSOLE)

    spy._copy_buttons["executable"].click()

    assert_that((QApplication.clipboard() or pytest.fail("no clipboard")).text()).is_equal_to("/usr/bin/konsole")


def test_create_rule_button_emits_window(spy):
    got: list[WindowInfo] = []
    spy.create_rule.connect(got.append)
    assert_that(spy._create_button.isEnabled()).is_false()

    spy.on_picked(_KONSOLE)
    spy._create_button.click()

    assert_that(got).is_equal_to([_KONSOLE])


def test_rule_from_window_prefills_class_and_non_normal_type():
    rule = rule_from_window(_DIALOG)

    assert_that(rule.name).is_equal_to("firefox")
    assert_that([(c.field, c.op, c.value) for c in rule.conditions]).is_equal_to(
        [("window_class", "equals", "firefox"), ("window_type", "equals", "dialog")]
    )
    assert_that((rule.rule_id, rule.enabled, rule.profile_id, rule.page_id)).is_equal_to(("", True, 0, ""))
    assert_that(rule_from_window(_KONSOLE).conditions).is_length(1)


def test_rule_from_window_empty_class_has_no_condition():
    rule = rule_from_window(WindowInfo(window_type="normal"))

    assert_that(rule.name).is_equal_to("New rule")
    assert_that(rule.conditions).is_empty()


class _Api:
    def __init__(self) -> None:
        self.rules: list[AppRule] = []
        self.picks = 0

    def app_rule_add(self, device_id: str, rule: AppRule) -> AppRule | None:
        stored = AppRule(f"r{len(self.rules) + 1}", rule.name, rule.enabled, rule.conditions, rule.profile_id)
        self.rules.append(stored)
        return stored

    def app_rule_update(self, device_id: str, rule: AppRule) -> bool:
        return True

    def app_rule_delete(self, device_id: str, rule_id: str) -> bool:
        return True

    def app_rule_move(self, device_id: str, rule_id: str, position: int) -> bool:
        return True

    def app_default_rule_set(self, device_id: str, default_rule: DefaultRule) -> bool:
        return True

    def window_pick(self) -> bool:
        self.picks += 1
        return True


def test_create_rule_signal_opens_new_rule_in_dialog(qapp):
    api = _Api()
    dialog = ProfilesDialog(lambda *a: True, api, lambda pid: [PageInfo("d1", "Home")])
    dialog.set_profiles(DeviceProfiles("dev1", [ProfileInfo(0, "Default", "")], 0))
    dialog.set_rules(DeviceRules("dev1", [], DefaultRule()))
    dialog.set_status(_status())
    dialog.show()

    dialog._spy_button.click()
    spy = dialog._spy
    assert spy is not None
    dialog._spy_button.click()
    assert_that(dialog._spy).is_same_as(spy)
    dialog.on_picked(_DIALOG)
    spy._create_button.click()
    dialog.set_rules(DeviceRules("dev1", list(api.rules), DefaultRule()))  # the server's event arrives later

    assert_that(dialog._rule_list.count()).is_equal_to(1)
    assert_that(dialog._rule_list.currentRow()).is_equal_to(0)
    assert_that(dialog._editor.rule().conditions[0].value).is_equal_to("firefox")
    spy.close()
    dialog.close()
