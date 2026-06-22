import zlib
from unittest.mock import MagicMock, patch

from assertpy import assert_that

from decker.server.devices import device_id_for_serial, list_devices


def _make_deck(deck_type="Stream Deck", vendor=4057, product=96, keys=15, serial="ABC123"):
    deck = MagicMock()
    deck.deck_type.return_value = deck_type
    deck.vendor_id.return_value = vendor
    deck.product_id.return_value = product
    deck.key_count.return_value = keys
    deck.get_serial_number.return_value = serial
    return deck


class TestDeviceId:
    def test_returns_eight_hex_chars(self):
        assert_that(device_id_for_serial("ABC123")).is_length(8)

    def test_no_0x_prefix(self):
        assert_that(device_id_for_serial("ABC123")).does_not_contain("0x")

    def test_only_hex_characters(self):
        result = device_id_for_serial("ABC123")
        assert_that(all(c in "0123456789abcdef" for c in result)).is_true()

    def test_same_serial_gives_same_id(self):
        assert_that(device_id_for_serial("XYZ999")).is_equal_to(device_id_for_serial("XYZ999"))

    def test_different_serials_give_different_ids(self):
        assert_that(device_id_for_serial("AAA")).is_not_equal_to(device_id_for_serial("BBB"))

    def test_matches_expected_crc32(self):
        serial = "A00NA437306BLR"
        expected = format(zlib.crc32(serial.encode()) & 0xFFFFFFFF, "08x")
        assert_that(device_id_for_serial(serial)).is_equal_to(expected)


class TestListDevices:
    def test_returns_empty_list_when_no_devices(self):
        with patch("decker.server.devices.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = []
            assert_that(list_devices()).is_equal_to([])

    def test_returns_one_entry_per_device(self):
        with patch("decker.server.devices.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [_make_deck(), _make_deck(serial="OTHER")]
            result = list_devices()
        assert_that(result).is_length(2)

    def test_entry_has_expected_fields(self):
        with patch("decker.server.devices.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [_make_deck()]
            result = list_devices()
        info = result[0]
        assert_that(info.id).is_not_none()
        assert_that(info.type).is_not_none()
        assert_that(info.keys).is_greater_than(0)

    def test_id_is_crc32_of_serial(self):
        with patch("decker.server.devices.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [_make_deck(serial="ABC123")]
            result = list_devices()
        assert_that(result[0].id).is_equal_to(device_id_for_serial("ABC123"))

    def test_id_is_none_when_open_fails(self):
        deck = _make_deck()
        deck.open.side_effect = OSError("permission denied")
        with patch("decker.server.devices.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            result = list_devices()
        assert_that(result[0].id).is_none()

    def test_serial_populated_when_open_succeeds(self):
        with patch("decker.server.devices.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [_make_deck(serial="XYZ999")]
            result = list_devices()
        assert_that(result[0].serial).is_equal_to("XYZ999")

    def test_serial_is_none_when_open_fails(self):
        deck = _make_deck()
        deck.open.side_effect = OSError("permission denied")
        with patch("decker.server.devices.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            result = list_devices()
        assert_that(result[0].serial).is_none()

    def test_other_fields_populated_even_when_open_fails(self):
        deck = _make_deck(deck_type="Stream Deck XL", keys=32)
        deck.open.side_effect = OSError("permission denied")
        with patch("decker.server.devices.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            result = list_devices()
        assert_that(result[0].type).is_equal_to("Stream Deck XL")
        assert_that(result[0].keys).is_equal_to(32)

    def test_returns_empty_list_when_enumerate_raises(self):
        with patch("decker.server.devices.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.side_effect = RuntimeError("no hidapi")
            assert_that(list_devices()).is_equal_to([])

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
