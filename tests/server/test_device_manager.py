from unittest.mock import MagicMock, patch

from assertpy import assert_that

from decker.server.device_manager import Device, DeviceManager
from decker.server.devices import device_id_for_serial


def _make_deck(serial: str = "ABC123") -> MagicMock:
    deck = MagicMock()
    deck.get_serial_number.return_value = serial
    deck.KEY_PIXEL_WIDTH = 72
    deck.KEY_PIXEL_HEIGHT = 72
    deck.key_image_format.return_value = {"size": (72, 72), "format": "JPEG", "flip": (False, False), "rotation": 0}
    return deck


def _manager() -> DeviceManager:
    return DeviceManager(on_key_event=lambda *_: None)


class TestDeviceManagerGetDevice:
    def test_returns_device_on_match(self):
        deck = _make_deck("ABC123")
        dm = _manager()
        with patch("decker.server.device_manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            device = dm.get_device(device_id_for_serial("ABC123"))
        assert_that(device).is_not_none()
        deck.open.assert_called_once()

    def test_returns_none_when_not_found(self):
        deck = _make_deck("OTHER")
        dm = _manager()
        with patch("decker.server.device_manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            device = dm.get_device(device_id_for_serial("ABC123"))
        assert_that(device).is_none()

    def test_closes_non_matching_decks(self):
        deck = _make_deck("OTHER")
        dm = _manager()
        with patch("decker.server.device_manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            dm.get_device(device_id_for_serial("ABC123"))
        deck.close.assert_called_once()

    def test_is_idempotent(self):
        deck = _make_deck("ABC123")
        dm = _manager()
        target_id = device_id_for_serial("ABC123")
        with patch("decker.server.device_manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            first = dm.get_device(target_id)
            second = dm.get_device(target_id)
        assert_that(first).is_same_as(second)
        assert_that(deck.open.call_count).is_equal_to(1)

    def test_returns_none_on_enumerate_error(self):
        dm = _manager()
        with patch("decker.server.device_manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.side_effect = RuntimeError("no hidapi")
            device = dm.get_device("abc12345")
        assert_that(device).is_none()

    def test_registers_key_callback(self):
        deck = _make_deck("ABC123")
        events: list = []
        dm = DeviceManager(on_key_event=lambda did, ki, pressed: events.append((did, ki, pressed)))
        target_id = device_id_for_serial("ABC123")
        with patch("decker.server.device_manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            dm.get_device(target_id)
        cb = deck.set_key_callback.call_args[0][0]
        cb(deck, 3, True)
        assert_that(events).contains((target_id, 3, True))


class TestDeviceManagerSetImageBytes:
    def test_delegates_to_open_device(self):
        deck = _make_deck("ABC123")
        dm = _manager()
        target_id = device_id_for_serial("ABC123")
        with patch("decker.server.device_manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            dm.get_device(target_id)
        with (
            patch("decker.server.device_manager.PILHelper") as mock_pil,
            patch("decker.server.device_manager.AssetRenderer") as mock_renderer_cls,
        ):
            mock_pil.create_scaled_key_image.return_value = b"scaled"
            mock_pil.to_native_key_format.return_value = b"native"
            mock_renderer_cls.return_value.render_bytes.return_value = None
            dm.set_image_bytes(target_id, 2, b"rawbytes")
        deck.set_key_image.assert_called_once_with(2, b"rawbytes")

    def test_no_op_for_unknown_device(self):
        dm = _manager()
        dm.set_image_bytes("unknown-id", 0, b"bytes")  # should not raise

    def test_hardware_error_is_caught(self):
        deck = _make_deck("ABC123")
        deck.set_key_image.side_effect = RuntimeError("hw failure")
        dm = _manager()
        target_id = device_id_for_serial("ABC123")
        with patch("decker.server.device_manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            dm.get_device(target_id)
        with patch("decker.server.device_manager.AssetRenderer") as mock_renderer_cls:
            mock_renderer_cls.return_value.render_bytes.return_value = None
            dm.set_image_bytes(target_id, 0, b"bytes")  # should not raise


class TestDeviceManagerDestroy:
    def test_resets_and_closes_open_devices(self):
        deck = _make_deck("ABC123")
        dm = _manager()
        with patch("decker.server.device_manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            dm.get_device(device_id_for_serial("ABC123"))
        dm.destroy()
        deck.reset.assert_called_once()
        deck.close.assert_called_once()

    def test_handles_close_errors_gracefully(self):
        deck = _make_deck("ABC123")
        deck.reset.side_effect = RuntimeError("hw error")
        dm = _manager()
        with patch("decker.server.device_manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            dm.get_device(device_id_for_serial("ABC123"))
        dm.destroy()  # should not raise


class TestDevice:
    def test_set_image_bytes_pushes_native_image(self):
        deck = _make_deck()
        device = Device(deck, "abc12345", lambda *_: None)
        with (
            patch("decker.server.device_manager.PILHelper") as mock_pil,
            patch.object(
                device._renderer, "render_bytes", return_value=MagicMock()
            ),  # pylint: disable=protected-access
        ):
            mock_pil.create_scaled_key_image.return_value = b"scaled"
            mock_pil.to_native_key_format.return_value = b"native"
            device.set_image_bytes(0, b"img")
        deck.set_key_image.assert_called_once_with(0, b"native")

    def test_close_resets_and_closes_deck(self):
        deck = _make_deck()
        device = Device(deck, "abc12345", lambda *_: None)
        device.close()
        deck.reset.assert_called_once()
        deck.close.assert_called_once()
