from unittest.mock import MagicMock, patch

from assertpy import assert_that

from decker.server.devices import list_devices


def _make_deck(deck_id="usb:1:2", deck_type="Stream Deck", vendor=4057, product=96, keys=15, serial="ABC123"):
    deck = MagicMock()
    deck.id.return_value = deck_id
    deck.deck_type.return_value = deck_type
    deck.vendor_id.return_value = vendor
    deck.product_id.return_value = product
    deck.key_count.return_value = keys
    deck.get_serial_number.return_value = serial
    return deck


class TestListDevices:
    def test_returns_empty_list_when_no_devices(self):
        with patch("decker.server.devices.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = []
            assert_that(list_devices()).is_equal_to([])

    def test_returns_one_entry_per_device(self):
        with patch("decker.server.devices.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [_make_deck(), _make_deck(deck_id="usb:1:3")]
            result = list_devices()
        assert_that(result).is_length(2)

    def test_entry_contains_expected_keys(self):
        with patch("decker.server.devices.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [_make_deck()]
            result = list_devices()
        entry = result[0]
        assert_that(entry).contains_key("id", "type", "vendor_id", "product_id", "keys", "serial")

    def test_serial_populated_when_open_succeeds(self):
        with patch("decker.server.devices.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [_make_deck(serial="XYZ999")]
            result = list_devices()
        assert_that(result[0]["serial"]).is_equal_to("XYZ999")

    def test_serial_is_none_when_open_fails(self):
        deck = _make_deck()
        deck.open.side_effect = OSError("permission denied")
        with patch("decker.server.devices.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            result = list_devices()
        assert_that(result[0]["serial"]).is_none()

    def test_other_fields_populated_even_when_open_fails(self):
        deck = _make_deck(deck_type="Stream Deck XL", keys=32)
        deck.open.side_effect = OSError("permission denied")
        with patch("decker.server.devices.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            result = list_devices()
        assert_that(result[0]["type"]).is_equal_to("Stream Deck XL")
        assert_that(result[0]["keys"]).is_equal_to(32)

    def test_returns_empty_list_when_enumerate_raises(self):
        with patch("decker.server.devices.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.side_effect = RuntimeError("no hidapi")
            result = list_devices()
        assert_that(result).is_equal_to([])

    def test_close_called_after_open(self):
        deck = _make_deck()
        with patch("decker.server.devices.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            list_devices()
        deck.close.assert_called_once()

    def test_close_called_even_when_serial_read_fails(self):
        deck = _make_deck()
        deck.get_serial_number.side_effect = OSError("read failed")
        with patch("decker.server.devices.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            list_devices()
        deck.close.assert_called_once()
