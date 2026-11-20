from assertpy import assert_that

from decker.common.slots import SLOT_NAMES, SWITCH_CARD_ID, normalize_slots

CARD = {"kind": "card", "plugin": "com.decker.blank", "card": "com.decker.blank.blank"}
ACTION = {"kind": "action", "action": "com.decker.core.httprequest", "settings": {"url": "x"}}


def test_normalize_slots_fills_all_four_keys() -> None:
    assert_that(normalize_slots(None)).is_equal_to(dict.fromkeys(SLOT_NAMES))
    assert_that(normalize_slots("junk")).is_equal_to(dict.fromkeys(SLOT_NAMES))
    result = normalize_slots({"display": CARD, "press": ACTION})
    assert_that(list(result)).is_equal_to(list(SLOT_NAMES))
    assert_that(result["display"]).is_equal_to({**CARD, "settings": {}, "appearance": {}})
    assert_that(result["press"]).is_equal_to(ACTION)
    assert_that(result["long_press"]).is_none()


def test_normalize_slots_drops_malformed_slots() -> None:
    bad: dict[str, object] = {
        "display": {"kind": "card", "plugin": 1, "card": "c"},
        "press": {"kind": "action"},
        "double_press": "nope",
        "long_press": {"kind": "card", "plugin": "p", "card": "c", "settings": []},
    }
    assert_that(normalize_slots(bad)).is_equal_to(dict.fromkeys(SLOT_NAMES))
    assert_that(normalize_slots({"press": {"kind": "other"}})["press"]).is_none()


def test_display_slot_rejects_action() -> None:
    result = normalize_slots({"display": ACTION, "press": ACTION})
    assert_that(result["display"]).is_none()
    assert_that(result["press"]).is_not_none()


def test_switch_card_cannot_nest() -> None:
    nested = {"kind": "card", "plugin": "com.decker.core", "card": SWITCH_CARD_ID}
    result = normalize_slots({"display": nested, "press": nested})
    assert_that(result).is_equal_to(dict.fromkeys(SLOT_NAMES))
