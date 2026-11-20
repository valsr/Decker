"""Drawing on the hardware: no firmware reads for layout, and no write for a key that already shows the image."""

import io
import threading
import time
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that
from PIL import Image

from decker.animation.factory import AnimationFactory
from decker.common.error import DeckNotOpenedError
from decker.server.devices import Device
from tests.server.animation_fixture import (
    opened_deck_manager,
    WRITER_THREAD,
    WriteLog,
    lifecycle,
    make_spec,
    stateful_deck,
    wait_until,
)


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
    deck.IMAGE_REPORT_PAYLOAD_LENGTH = 1016
    return deck


@pytest.fixture(name="device")
def device_fixture(deck: MagicMock) -> Iterator[Device]:
    device = Device("dev", "serial", deck)
    yield device
    device.close()


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


@pytest.fixture(name="factory")
def factory_fixture() -> Iterator[AnimationFactory]:
    factory = AnimationFactory(cache_bytes=8 * 1024 * 1024)
    yield factory
    factory.close()


@pytest.fixture(name="log")
def log_fixture(deck: MagicMock) -> WriteLog:
    log = WriteLog()
    deck.set_key_image.side_effect = log
    return log


@pytest.fixture(name="animated")
def animated_fixture(deck: MagicMock, factory: AnimationFactory) -> Iterator[Device]:
    device = Device("dev", "serial", deck)
    device.set_animation_support(factory, True, 0.75)
    yield device
    device.close()


class TestAnimatedDevice:
    def test_set_image_bytes_writes_through_the_writer_and_still_skips_an_unchanged_image(
        self, animated: Device, log: WriteLog
    ) -> None:
        animated.set_image_bytes(3, _png("red"))
        animated.set_image_bytes(3, _png("red"))

        assert_that(len(log.writes)).is_equal_to(1)
        assert_that(log.writes[0][2]).is_equal_to(WRITER_THREAD)
        assert_that(animated.get_key_image(3)).is_not_none()

    def test_the_writer_starts_with_the_first_write(self, animated: Device, log: WriteLog) -> None:
        assert_that([t for t in threading.enumerate() if t.name == WRITER_THREAD]).is_empty()

        animated.clear_key_image(1)

        assert_that(log.writes[0][:3]).is_equal_to((1, None, WRITER_THREAD))

    def test_animation_support_given_after_the_first_write_still_animates(
        self, device: Device, factory: AnimationFactory, log: WriteLog
    ) -> None:
        device.set_image_bytes(3, _png("red"))
        device.set_animation_support(factory, True, 0.75)

        device.play_animation(3, make_spec())

        assert_that(wait_until(lambda: len(log.for_key(3)) >= 3)).is_true()
        assert_that(log.writes[0][2]).is_not_equal_to(WRITER_THREAD)  # direct write, as before
        assert_that(log.for_key(3)[-1][2]).is_equal_to(WRITER_THREAD)

    def test_without_animation_support_play_animation_keeps_the_static_image(
        self, device: Device, log: WriteLog
    ) -> None:
        device.set_image_bytes(3, _png("red"))

        device.play_animation(3, make_spec())
        time.sleep(0.3)

        assert_that(len(log.writes)).is_equal_to(1)

    def test_a_write_that_fails_in_the_writer_is_retried(self, animated: Device, deck: MagicMock) -> None:
        deck.set_key_image.side_effect = [OSError("usb"), None]

        animated.set_image_bytes(3, _png("red"))
        animated.set_image_bytes(3, _png("red"))

        assert_that(deck.set_key_image.call_count).is_equal_to(2)

    def test_static_write_stops_that_keys_animation(self, animated: Device, log: WriteLog) -> None:
        animated.set_image_bytes(3, _png("red"))
        animated.play_animation(3, make_spec())
        assert_that(wait_until(lambda: len(log.for_key(3)) >= 3)).is_true()

        animated.set_image_bytes(3, _png("red"))  # the poster again: must still be written, ending the animation
        static_data = log.for_key(3)[-1][1]
        written = len(log.for_key(3))
        time.sleep(0.4)  # four frame periods

        assert_that(len(log.for_key(3))).is_equal_to(written)
        assert_that(log.for_key(3)[-1][1] == static_data).is_true()
        assert_that(log.for_key(3)[0][1] == static_data).is_true()

    def test_stop_animations_leaves_no_frame_writes_after_it_returns(
        self, animated: Device, deck: MagicMock, log: WriteLog
    ) -> None:
        animated.play_animation(1, make_spec())
        assert_that(wait_until(lambda: len(log.for_key(1)) >= 2)).is_true()
        entered, release = threading.Event(), threading.Event()

        def slow_write(key_index: int, data: bytes | None) -> None:
            entered.set()
            release.wait(5)
            log(key_index, data)

        deck.set_key_image.side_effect = slow_write
        assert_that(entered.wait(2)).is_true()  # a frame write is under way
        stopper = threading.Thread(target=animated.stop_animations)
        stopper.start()
        stopper.join(0.2)
        waited_for_the_write = stopper.is_alive()
        release.set()
        stopper.join(2)
        stopped_at = time.monotonic()
        time.sleep(0.3)

        assert_that(waited_for_the_write).is_true()
        assert_that(len([write for write in log.writes if write[3] > stopped_at])).is_zero()

    def test_device_close_returns_promptly_with_animations_running(
        self, deck: MagicMock, factory: AnimationFactory, log: WriteLog
    ) -> None:
        device = Device("dev", "serial", deck)
        device.set_animation_support(factory, True, 0.75)
        for key_index in range(4):
            device.play_animation(key_index, make_spec())
        assert_that(wait_until(lambda: all(len(log.for_key(k)) >= 2 for k in range(4)))).is_true()
        release = threading.Event()
        deck.set_key_image.side_effect = lambda *_: release.wait(10)  # the deck went away mid-write
        assert_that(wait_until(lambda: deck.set_key_image.call_count > len(log.writes))).is_true()

        started = time.monotonic()
        device.close()
        elapsed = time.monotonic() - started
        release.set()

        assert_that(elapsed).is_less_than(1.5)
        deck.reset.assert_called_once()
        deck.close.assert_called_once()
        assert_that(wait_until(lambda: not [t for t in threading.enumerate() if t.name == WRITER_THREAD])).is_true()

    def test_a_closed_device_does_not_start_a_writer(self, deck: MagicMock, factory: AnimationFactory) -> None:
        device = Device("dev", "serial", deck)
        device.set_animation_support(factory, True, 0.75)
        device.close()

        device.play_animation(1, make_spec())

        assert_that([t for t in threading.enumerate() if t.name == WRITER_THREAD]).is_empty()

    def test_animation_frames_issue_no_hid_reads(self, animated: Device, deck: MagicMock, log: WriteLog) -> None:
        animated.play_animation(1, make_spec())
        assert_that(wait_until(lambda: len(log.for_key(1)) >= 2)).is_true()
        deck.get_serial_number.reset_mock()
        deck.is_open.reset_mock()
        frames_before = len(log.for_key(1))

        assert_that(wait_until(lambda: len(log.for_key(1)) >= frames_before + 3)).is_true()

        assert_that(deck.get_serial_number.call_count).is_zero()
        assert_that(deck.is_open.call_count).is_zero()

    def test_static_writes_still_check_the_deck_first(self, animated: Device, deck: MagicMock, log: WriteLog) -> None:
        animated.set_image_bytes(3, _png("red"))

        deck.get_serial_number.assert_called()
        assert_that(len(log.writes)).is_equal_to(1)

    def test_stop_animation_stops_only_that_key(self, animated: Device, log: WriteLog) -> None:
        animated.play_animation(1, make_spec())
        animated.play_animation(2, make_spec())
        assert_that(wait_until(lambda: len(log.for_key(1)) >= 2 and len(log.for_key(2)) >= 2)).is_true()

        animated.stop_animation(1)
        time.sleep(0.15)  # a frame already under way may still land
        key1, key2 = len(log.for_key(1)), len(log.for_key(2))
        time.sleep(0.35)

        assert_that(len(log.for_key(1))).is_equal_to(key1)
        assert_that(len(log.for_key(2))).is_greater_than(key2)

    def test_close_runs_once(self, animated: Device, deck: MagicMock, log: WriteLog) -> None:
        animated.set_image_bytes(3, _png("red"))

        animated.close()
        animated.close()

        deck.reset.assert_called_once()
        deck.close.assert_called_once()

    def test_close_from_the_writer_thread_does_not_hang(self, animated: Device, deck: MagicMock, log: WriteLog) -> None:
        animated.play_animation(1, make_spec())
        assert_that(wait_until(lambda: len(log.for_key(1)) >= 1)).is_true()

        deck.set_key_image.side_effect = lambda *_: animated.close()

        assert_that(wait_until(lambda: deck.close.call_count == 1)).is_true()
        assert_that(wait_until(lambda: not [t for t in threading.enumerate() if t.name == WRITER_THREAD])).is_true()

    def test_a_lost_device_reports_itself(self, deck: MagicMock) -> None:
        reported: list[Device] = []
        device = Device("dev", "serial", deck, reported.append)
        deck.get_serial_number.side_effect = OSError("gone")

        assert_that(device.try_validate()).is_false()

        assert_that(reported).is_length(1)
        assert_that(reported[0]).is_same_as(device)
        device.close()


class TestClosedDevice:
    """A Device that has been closed, or closed itself while reporting, never opens its deck again."""

    def test_a_device_closed_by_its_own_report_ends_closed_without_reopening(self) -> None:
        deck = stateful_deck()
        deck.open()
        device = Device("dev", "serial", deck, lambda lost: lost.close())
        deck.get_serial_number.side_effect = OSError("gone")

        device.set_image_bytes(3, _png("red"))

        assert_that(lifecycle(deck)).is_equal_to(["open", "reset", "close"])
        assert_that(deck.is_open()).is_false()
        deck.set_key_image.assert_not_called()

    def test_a_closed_device_does_not_touch_the_deck(self) -> None:
        deck = stateful_deck()
        device = Device("dev", "serial", deck, MagicMock())
        device.close()
        deck.reset_mock()

        device.set_image_bytes(3, _png("red"))
        device.clear_key_image(4)
        assert_that(device.try_validate()).is_false()
        assert_that(device.validate).raises(DeckNotOpenedError).when_called_with()

        deck.open.assert_not_called()
        deck.get_serial_number.assert_not_called()
        deck.set_key_image.assert_not_called()

    def test_a_closed_device_reports_nothing(self) -> None:
        reported: list[Device] = []
        deck = stateful_deck()
        device = Device("dev", "serial", deck, reported.append)
        device.close()

        device.try_validate()
        device.set_image_bytes(3, _png("red"))

        assert_that(reported).is_empty()


def test_resetting_the_same_bytes_neither_renders_nor_writes_again(tmp_path) -> None:
    buf = io.BytesIO()
    Image.new("RGB", (72, 72), (10, 20, 30)).save(buf, "PNG")
    with opened_deck_manager(tmp_path) as (manager, device_id, log):
        device = manager.open_device(device_id)
        assert device is not None
        device.set_image_bytes(0, buf.getvalue())
        writes = len(log.writes)
        with patch.object(device, "_render", wraps=device._render) as render:  # pylint: disable=protected-access
            device.set_image_bytes(0, buf.getvalue())

        assert_that(render.call_count).is_zero()
        assert_that(len(log.writes)).is_equal_to(writes)
