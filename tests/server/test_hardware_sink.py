from unittest.mock import MagicMock, patch

from assertpy import assert_that

from decker.server.devices import device_id_for_serial
from decker.server.plugins import _StreamDeckHardwareSink


def _make_deck(serial="ABC123"):
    deck = MagicMock()
    deck.get_serial_number.return_value = serial
    return deck


class TestStreamDeckHardwareSink:
    def test_set_image_calls_set_key_image_on_matching_device(self):
        deck = _make_deck()
        with patch("decker.server.plugins.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            _StreamDeckHardwareSink().set_image(device_id_for_serial("ABC123"), 2, b"img")
        deck.set_key_image.assert_called_once_with(2, b"img")

    def test_set_image_skips_non_matching_device(self):
        deck = _make_deck(serial="OTHER")
        with patch("decker.server.plugins.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            _StreamDeckHardwareSink().set_image(device_id_for_serial("ABC123"), 2, b"img")
        deck.set_key_image.assert_not_called()

    def test_set_image_closes_device_after_use(self):
        deck = _make_deck()
        with patch("decker.server.plugins.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            _StreamDeckHardwareSink().set_image(device_id_for_serial("ABC123"), 2, b"img")
        deck.close.assert_called_once()

    def test_enumerate_failure_does_not_raise(self):
        with patch("decker.server.plugins.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.side_effect = RuntimeError("no hidapi")
            _StreamDeckHardwareSink().set_image("abc12345", 0, b"img")  # should not raise

    def test_no_matching_device_does_not_raise(self):
        with patch("decker.server.plugins.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = []
            _StreamDeckHardwareSink().set_image("abc12345", 0, b"img")  # should not raise

    def test_hardware_operation_error_is_caught(self):
        deck = _make_deck()
        deck.set_key_image.side_effect = RuntimeError("hardware failure")
        with patch("decker.server.plugins.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            _StreamDeckHardwareSink().set_image(device_id_for_serial("ABC123"), 0, b"img")  # should not raise
        deck.close.assert_called_once()

    def test_unimplemented_methods_are_no_ops(self):
        sink = _StreamDeckHardwareSink()
        sink.set_title("dev", 0, "title")
        sink.set_state("dev", 0, 1)
        sink.show_alert("dev", 0)
        sink.show_ok("dev", 0)
        assert_that(True).is_true()
