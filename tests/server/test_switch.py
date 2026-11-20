from typing import Any

from assertpy import assert_that

from decker.common.slots import normalize_slots
from decker.plugin.gestures import Gesture
from decker.server.switch import SwitchController, SwitchOutcome


def _card(card: str) -> dict[str, Any]:
    return {"kind": "card", "plugin": "p", "card": card, "settings": {}}


def _action(action: str) -> dict[str, Any]:
    return {"kind": "action", "action": action, "settings": {"a": 1}}


def _slots(**kwargs: Any) -> dict[str, Any]:
    return normalize_slots(kwargs)


def test_gestures_follow_filled_slots() -> None:
    slots = _slots(display=_card("d"), press=_card("a"), long_press=_action("x"))
    assert_that(SwitchController().gestures(slots)).is_equal_to(frozenset({Gesture.PRESS, Gesture.LONG_PRESS}))


def test_shown_slot_prefers_remembered_then_display_then_press_card() -> None:
    controller = SwitchController()
    slots = _slots(display=_card("d"), press=_card("a"), long_press=_card("b"))
    assert_that(controller.shown_slot("c", slots)).is_equal_to("display")
    controller.handle("c", slots, Gesture.LONG_PRESS)
    assert_that(controller.shown_slot("c", slots)).is_equal_to("long_press")
    assert_that(SwitchController().shown_slot("c", _slots(press=_card("a")))).is_equal_to("press")


def test_shown_slot_none_when_press_is_action_and_no_display() -> None:
    assert_that(SwitchController().shown_slot("c", _slots(press=_action("x")))).is_none()


def test_handle_action_returns_action_without_changing_shown() -> None:
    controller = SwitchController()
    slots = _slots(display=_card("d"), press=_action("x"))
    outcome = controller.handle("c", slots, Gesture.PRESS)
    assert_that(outcome).is_equal_to(SwitchOutcome(action=("x", {"a": 1})))
    assert_that(controller.shown_slot("c", slots)).is_equal_to("display")


def test_handle_card_remembers_and_shows() -> None:
    controller = SwitchController()
    slots = _slots(display=_card("d"), press=_card("a"))
    assert_that(controller.handle("c", slots, Gesture.PRESS)).is_equal_to(SwitchOutcome(show="press"))
    assert_that(controller.shown_slot("c", slots)).is_equal_to("press")


def test_handle_same_card_is_noop() -> None:
    controller = SwitchController()
    slots = _slots(display=_card("d"), press=_card("d"), long_press=_card("b"))
    assert_that(controller.handle("c", slots, Gesture.PRESS)).is_equal_to(SwitchOutcome())
    controller.handle("c", slots, Gesture.LONG_PRESS)
    assert_that(controller.handle("c", slots, Gesture.LONG_PRESS)).is_equal_to(SwitchOutcome())
    assert_that(controller.shown_slot("c", slots)).is_equal_to("long_press")


def test_remembered_slot_cleared_falls_back_to_display() -> None:
    controller = SwitchController()
    controller.handle("c", _slots(display=_card("d"), press=_card("a")), Gesture.PRESS)
    assert_that(controller.shown_slot("c", _slots(display=_card("d")))).is_equal_to("display")


def test_all_empty_slots_do_nothing() -> None:
    controller = SwitchController()
    slots = _slots()
    assert_that(controller.gestures(slots)).is_empty()
    assert_that(controller.shown_slot("c", slots)).is_none()
    assert_that(controller.handle("c", slots, Gesture.PRESS)).is_equal_to(SwitchOutcome())
