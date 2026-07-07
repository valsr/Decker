"""Tests for device enumeration and device ID utilities."""

import zlib
from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that

from decker.server.devices.manager import DeviceManager, device_id_for_serial


def _make_deck(deck_type="Stream Deck", vendor=4057, product=96, rows=3, cols=5, serial="ABC123"):
    deck = MagicMock()
    deck.deck_type.return_value = deck_type
    deck.vendor_id.return_value = vendor
    deck.product_id.return_value = product
    deck.key_count.return_value = rows * cols
    deck.key_layout.return_value = (rows, cols)
    deck.key_image_format.return_value = {"size": (72, 72), "format": "JPEG", "flip": (False, False), "rotation": 0}
    deck.get_serial_number.return_value = serial
    opened = [False]
    deck.is_open.side_effect = lambda: opened[0]
    deck.open.side_effect = lambda: opened.__setitem__(0, True)
    deck.close.side_effect = lambda: opened.__setitem__(0, False)
    return deck


def _manager() -> DeviceManager:
    return DeviceManager(on_key_event=lambda *_: None)


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
        dm = _manager()
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = []
            assert_that(dm.list_devices()).is_equal_to([])

    def test_returns_one_entry_per_device(self):
        dm = _manager()
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [_make_deck(), _make_deck(serial="OTHER")]
            result = dm.list_devices()
        assert_that(result).is_length(2)

    def test_entry_has_expected_fields(self):
        dm = _manager()
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [_make_deck()]
            result = dm.list_devices()
        info = result[0]
        assert_that(info.id).is_not_none()
        assert_that(info.type).is_not_none()
        assert_that(info.num_keys).is_greater_than(0)
        assert_that(info.keys).is_not_empty()
        assert_that(info.keys[0].row).is_equal_to(0)
        assert_that(info.keys[0].col).is_equal_to(0)
        assert_that(info.keys[0].pixel_width).is_greater_than(0)
        assert_that(info.keys[0].pixel_height).is_greater_than(0)

    def test_id_is_crc32_of_serial(self):
        dm = _manager()
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [_make_deck(serial="ABC123")]
            result = dm.list_devices()
        assert_that(result[0].id).is_equal_to(device_id_for_serial("ABC123"))

    def test_serial_populated_when_open_succeeds(self):
        dm = _manager()
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [_make_deck(serial="XYZ999")]
            result = dm.list_devices()
        assert_that(result[0].serial).is_equal_to("XYZ999")

    def test_close_called_after_open(self):
        deck = _make_deck()
        dm = _manager()
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            dm.list_devices()
        deck.close.assert_called_once()

    def test_raises_on_enumerate_error(self):
        dm = _manager()
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.side_effect = RuntimeError("no hidapi")
            with pytest.raises(RuntimeError):
                dm.list_devices()

    def test_other_device_errors_are_caught(self):
        deck = _make_deck()
        deck.get_serial_number.side_effect = OSError("read failed")
        dm = _manager()
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            result = dm.list_devices()  # should not raise
        assert_that(result).is_empty()
