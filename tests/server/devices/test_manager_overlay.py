from unittest.mock import MagicMock

from assertpy import assert_that

from decker.server.device_state_store import DeviceStateStore
from tests.server.devices.overlay_fixture import (
    DEVICE_ID,
    make_deck,
    open_manager,
    png,
    press,
    state_of,
)


def _events() -> tuple[list[tuple[str, int, bool]], list[str], list[str]]:
    return [], [], []


def _wired(deck):
    delivered, woke, active = _events()
    manager, device = open_manager(deck, lambda d, k, p: delivered.append((d, k, p)))
    manager.set_wake_hook(woke.append)
    manager.set_activity_hook(active.append)
    return manager, device, delivered, woke, active


def test_wake_press_and_release_are_swallowed():
    deck = make_deck()
    manager, device, delivered, woke, _ = _wired(deck)
    manager.set_overlay(DEVICE_ID, True)
    press(deck, 1, True)
    manager.set_overlay(DEVICE_ID, False)
    press(deck, 1, False)  # the release of the wake press arrives after the overlay is gone
    assert_that(woke).is_equal_to([DEVICE_ID])
    assert_that(delivered).is_empty()
    assert_that(device.get_key_state(1).name).is_equal_to("UP")
    press(deck, 1, True)
    press(deck, 1, False)
    assert_that(delivered).is_equal_to([(DEVICE_ID, 1, True), (DEVICE_ID, 1, False)])
    manager.destroy()


def test_other_key_release_during_overlay_swallowed():
    deck = make_deck()
    manager, _, delivered, woke, _ = _wired(deck)
    manager.set_overlay(DEVICE_ID, True)
    press(deck, 2, False)
    assert_that(woke).is_empty()
    assert_that(delivered).is_empty()
    manager.destroy()


def test_normal_events_pass_through_and_call_activity_hook():
    deck = make_deck()
    manager, _, delivered, woke, active = _wired(deck)
    press(deck, 0, True)
    press(deck, 0, False)
    assert_that(delivered).is_length(2)
    assert_that(active).is_equal_to([DEVICE_ID, DEVICE_ID])
    assert_that(woke).is_empty()
    manager.set_activity_hook(lambda _: 1 / 0)  # a bad hook never breaks delivery
    press(deck, 0, True)
    assert_that(delivered).is_length(3)
    manager.destroy()


def test_writes_during_overlay_update_state_but_not_hardware():
    deck = make_deck()
    manager, device = open_manager(deck)
    manager.set_overlay(DEVICE_ID, True)
    deck.set_key_image.reset_mock()
    manager.set_image_bytes(DEVICE_ID, 0, png("red"))
    manager.blank_key(DEVICE_ID, 1)
    device.clear_key_image(2)
    assert_that(state_of(manager).get_key_state(0).image).is_not_none()
    assert_that(manager.show_page(DEVICE_ID, "p2")).is_true()
    deck.set_key_image.assert_not_called()
    manager.destroy()


def test_write_overlay_bypasses_gate():
    deck = make_deck()
    manager, _ = open_manager(deck)
    manager.set_overlay(DEVICE_ID, True)
    deck.set_key_image.reset_mock()
    assert_that(manager.write_overlay(DEVICE_ID, [png("red"), png("blue"), png("green")])).is_true()
    assert_that(deck.set_key_image.call_count).is_equal_to(3)
    assert_that(manager.write_overlay(DEVICE_ID, None)).is_true()
    assert_that(deck.set_key_image.call_args_list[-1].args[1]).is_none()
    assert_that(manager.write_overlay("unknown", None)).is_false()
    deck.set_key_image.side_effect = RuntimeError("usb")
    assert_that(manager.write_overlay(DEVICE_ID, None)).is_false()
    manager.destroy()


def test_show_page_after_overlay_off_redraws_cached_state(tmp_path):
    store = DeviceStateStore(data_dir=tmp_path)
    store.create(MagicMock())
    deck = make_deck()
    manager, _ = open_manager(deck, store=store)
    page = state_of(manager).page_id
    manager.set_image_bytes(DEVICE_ID, 0, png("red"))
    manager.set_overlay(DEVICE_ID, True)
    manager.write_overlay(DEVICE_ID, None)
    manager.set_image_bytes(DEVICE_ID, 1, png("blue"))  # a plugin write while the screensaver shows
    deck.set_key_image.reset_mock()
    manager.set_overlay(DEVICE_ID, False)
    manager.show_page(DEVICE_ID, page)
    written = {call.args[0]: call.args[1] for call in deck.set_key_image.call_args_list}
    assert_that(written).contains_key(0, 1)
    assert_that(written[0]).is_not_none()
    assert_that(written[1]).is_not_none()
    assert_that(written[2]).is_none()
    assert_that(manager.overlay_active(DEVICE_ID)).is_false()
    manager.destroy()
    store.destroy()


def test_stale_device_events_do_not_wake():
    deck = make_deck()
    manager, device, delivered, woke, active = _wired(deck)
    manager.set_overlay(DEVICE_ID, True)
    manager.close_device(device)
    press(deck, 0, True)
    assert_that(woke).is_empty()
    assert_that(active).is_empty()
    assert_that(delivered).is_empty()
