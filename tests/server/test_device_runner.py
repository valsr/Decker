from unittest.mock import MagicMock, patch

from assertpy import assert_that

from decker.server.device_runner import DeviceRunner
from decker.server.devices import device_id_for_serial


def _make_deck(serial="ABC123"):
    deck = MagicMock()
    deck.get_serial_number.return_value = serial
    deck.KEY_PIXEL_WIDTH = 72
    deck.KEY_PIXEL_HEIGHT = 72
    deck.key_image_format.return_value = {"size": (72, 72), "format": "JPEG", "flip": (False, False), "rotation": 0}
    return deck


_NO_CALLBACK: list = []


def _runner() -> DeviceRunner:
    return DeviceRunner(on_key_event=lambda *_: None)


class TestDeviceRunnerOpenDevice:
    def test_open_device_returns_true_on_match(self):
        deck = _make_deck("ABC123")
        runner = _runner()
        with patch("decker.server.device_runner.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            result = runner.open_device(device_id_for_serial("ABC123"))
        assert_that(result).is_true()
        deck.open.assert_called_once()

    def test_open_device_returns_false_when_not_found(self):
        deck = _make_deck("OTHER")
        runner = _runner()
        with patch("decker.server.device_runner.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            result = runner.open_device(device_id_for_serial("ABC123"))
        assert_that(result).is_false()

    def test_open_device_skips_non_matching_decks(self):
        deck = _make_deck("OTHER")
        runner = _runner()
        with patch("decker.server.device_runner.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            runner.open_device(device_id_for_serial("ABC123"))
        deck.close.assert_called_once()

    def test_open_device_is_idempotent(self):
        deck = _make_deck("ABC123")
        runner = _runner()
        with patch("decker.server.device_runner.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            target_id = device_id_for_serial("ABC123")
            runner.open_device(target_id)
            result = runner.open_device(target_id)
        assert_that(result).is_true()
        assert_that(deck.open.call_count).is_equal_to(1)

    def test_open_device_returns_false_on_enumerate_error(self):
        runner = _runner()
        with patch("decker.server.device_runner.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.side_effect = RuntimeError("no hidapi")
            result = runner.open_device("abc12345")
        assert_that(result).is_false()

    def test_open_device_registers_key_callback(self):
        deck = _make_deck("ABC123")
        events: list = []
        runner = DeviceRunner(on_key_event=lambda did, ki, pressed: events.append((did, ki, pressed)))
        target_id = device_id_for_serial("ABC123")
        with patch("decker.server.device_runner.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            runner.open_device(target_id)
        # Simulate the callback being invoked
        _cb = deck.set_key_callback.call_args[0][0]
        _cb(deck, 3, True)
        assert_that(events).contains((target_id, 3, True))


class TestDeviceRunnerSetImageBytes:
    def test_set_image_bytes_calls_set_key_image(self):
        deck = _make_deck("ABC123")
        runner = _runner()
        target_id = device_id_for_serial("ABC123")
        with patch("decker.server.device_runner.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            runner.open_device(target_id)
        with (
            patch("decker.server.device_runner.PILHelper") as mock_pil,
            patch.object(runner._renderer, "render_bytes", return_value=None),  # pylint: disable=protected-access
        ):
            runner.set_image_bytes(target_id, 2, b"rawbytes")
        deck.set_key_image.assert_called_once_with(2, b"rawbytes")

    def test_set_image_bytes_for_unknown_device_does_not_raise(self):
        runner = _runner()
        runner.set_image_bytes("unknown-id", 0, b"bytes")  # should not raise

    def test_set_image_bytes_hardware_error_is_caught(self):
        deck = _make_deck("ABC123")
        deck.set_key_image.side_effect = RuntimeError("hw failure")
        runner = _runner()
        target_id = device_id_for_serial("ABC123")
        with patch("decker.server.device_runner.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            runner.open_device(target_id)
        with patch.object(runner._renderer, "render_bytes", return_value=None):  # pylint: disable=protected-access
            runner.set_image_bytes(target_id, 0, b"bytes")  # should not raise


class TestDeviceRunnerRenderTextImage:
    def test_returns_png_bytes(self):
        runner = _runner()
        data = runner.render_text_image("42")
        assert_that(data).is_not_none()
        assert_that(len(data)).is_greater_than(0)
        assert_that(data[:4]).is_equal_to(b"\x89PNG")


class TestDeviceRunnerCloseAll:
    def test_close_all_resets_and_closes_open_decks(self):
        deck = _make_deck("ABC123")
        runner = _runner()
        with patch("decker.server.device_runner.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            runner.open_device(device_id_for_serial("ABC123"))
        runner.close_all()
        deck.reset.assert_called_once()
        deck.close.assert_called_once()

    def test_close_all_handles_errors_gracefully(self):
        deck = _make_deck("ABC123")
        deck.reset.side_effect = RuntimeError("hw error")
        runner = _runner()
        with patch("decker.server.device_runner.DeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            runner.open_device(device_id_for_serial("ABC123"))
        runner.close_all()  # should not raise
