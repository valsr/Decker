"""Drawing on the hardware: no firmware reads for layout, and no write for a key that already shows the image."""

import io
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that
from PIL import Image

from decker.server.devices import Device


def _png(color: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (72, 72), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(name="deck")
def deck_fixture() -> MagicMock:
    deck = MagicMock()
    deck.key_layout.return_value = (3, 5)
    deck.key_count.return_value = 15
    deck.key_image_format.return_value = {"size": (72, 72), "format": "JPEG", "flip": (False, False), "rotation": 0}
    deck.is_open.return_value = True
    return deck


@pytest.fixture(name="device")
def device_fixture(deck: MagicMock) -> Device:
    return Device("dev", "serial", deck)


class TestLayout:
    def test_key_position_is_column_and_row_without_asking_the_hardware(self, device: Device, deck: MagicMock) -> None:
        assert_that(device.key_position(0)).is_equal_to((0, 0))
        assert_that(device.key_position(7)).is_equal_to((2, 1))
        assert_that(device.key_position(14)).is_equal_to((4, 2))

        deck.get_firmware_version.assert_not_called()
        deck.get_serial_number.assert_not_called()

    @pytest.mark.parametrize("index", [-1, 15, 99])
    def test_a_key_outside_the_layout_has_no_position(self, device: Device, index: int) -> None:
        assert_that(device.key_position(index)).is_none()

    def test_key_count(self, device: Device) -> None:
        assert_that(device.key_count).is_equal_to(15)


class TestImageWrites:
    def test_an_image_the_key_already_shows_is_not_sent_again(self, device: Device, deck: MagicMock) -> None:
        device.set_image_bytes(3, _png("red"))
        device.set_image_bytes(3, _png("red"))

        assert_that(deck.set_key_image.call_count).is_equal_to(1)

    def test_a_different_image_is_sent(self, device: Device, deck: MagicMock) -> None:
        device.set_image_bytes(3, _png("red"))
        device.set_image_bytes(3, _png("blue"))

        assert_that(deck.set_key_image.call_count).is_equal_to(2)

    def test_each_key_is_tracked_separately(self, device: Device, deck: MagicMock) -> None:
        device.set_image_bytes(1, _png("red"))
        device.set_image_bytes(2, _png("red"))

        assert_that(deck.set_key_image.call_count).is_equal_to(2)

    def test_the_cached_image_is_kept_when_the_write_is_skipped(self, device: Device) -> None:
        device.set_image_bytes(3, _png("red"))
        first = device.get_key_image(3)
        device.set_image_bytes(3, _png("red"))

        assert_that(device.get_key_image(3)).is_equal_to(first)

    def test_a_failed_write_is_retried(self, device: Device, deck: MagicMock) -> None:
        deck.set_key_image.side_effect = [OSError("usb"), None]

        device.set_image_bytes(3, _png("red"))
        device.set_image_bytes(3, _png("red"))

        assert_that(deck.set_key_image.call_count).is_equal_to(2)


class TestBlanking:
    def test_an_already_blank_key_is_not_cleared_again(self, device: Device, deck: MagicMock) -> None:
        device.clear_key_image(4)
        device.clear_key_image(4)

        assert_that(deck.set_key_image.call_count).is_equal_to(1)

    def test_an_unknown_key_is_cleared_the_first_time(self, device: Device, deck: MagicMock) -> None:
        device.clear_key_image(4)

        deck.set_key_image.assert_called_once_with(4, None)

    def test_a_key_blanked_after_an_image_is_cleared_and_redrawn_afterwards(
        self, device: Device, deck: MagicMock
    ) -> None:
        device.set_image_bytes(4, _png("red"))
        device.clear_key_image(4)
        device.set_image_bytes(4, _png("red"))

        assert_that(deck.set_key_image.call_count).is_equal_to(3)
        assert_that(device.get_key_image(4)).is_not_none()

    def test_a_failed_clear_is_retried(self, device: Device, deck: MagicMock) -> None:
        deck.set_key_image.side_effect = [OSError("usb"), None]

        device.clear_key_image(4)
        device.clear_key_image(4)

        assert_that(deck.set_key_image.call_count).is_equal_to(2)
