from assertpy import assert_that

from tests.server.devices.overlay_fixture import DEVICE_ID, make_deck, open_manager


def test_set_brightness_calls_deck():
    deck = make_deck()
    manager, device = open_manager(deck)
    manager.set_brightness(DEVICE_ID, 40)
    deck.set_brightness.assert_called_once_with(40)
    device.set_brightness(250)
    assert_that(deck.set_brightness.call_args.args[0]).is_equal_to(100)
    manager.destroy()
