"""Tests for DeviceManager."""

import io
import json
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that
from PIL import Image

from decker.common import config
from decker.common.error import DeckNotOpenedError
from decker.server.device_state_store import DeviceStateStore
from decker.server.devices import Device
from decker.server.devices.manager import DeviceManager, device_id_for_serial
from tests.server.animation_fixture import (
    WRITER_THREAD,
    WriteLog,
    lifecycle,
    make_spec,
    stateful_deck,
    wait_until,
)


def _make_deck(serial: str = "ABC123") -> MagicMock:
    deck = MagicMock()
    deck.get_serial_number.return_value = serial
    opened = [False]
    deck.is_open.side_effect = lambda: opened[0]
    deck.open.side_effect = lambda: opened.__setitem__(0, True)
    deck.close.side_effect = lambda: opened.__setitem__(0, False)
    deck.KEY_PIXEL_WIDTH = 72
    deck.KEY_PIXEL_HEIGHT = 72
    deck.IMAGE_REPORT_PAYLOAD_LENGTH = 1016
    deck.key_count.return_value = 15
    deck.key_layout.return_value = (3, 5)
    deck.key_image_format.return_value = {"size": (72, 72), "format": "JPEG", "flip": (False, False), "rotation": 0}
    return deck


def _manager() -> DeviceManager:
    return DeviceManager(on_key_event=lambda *_: None)


class TestDeviceManagerOpenDevice:
    def test_returns_device_on_match(self):
        deck = _make_deck("ABC123")
        dm = _manager()
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            device = dm.open_device(device_id_for_serial("ABC123"))
        assert_that(device).is_not_none()
        deck.open.assert_called()

    def test_returns_none_when_not_found(self):
        deck = _make_deck("OTHER")
        dm = _manager()
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            device = dm.open_device(device_id_for_serial("ABC123"))
        assert_that(device).is_none()

    def test_is_idempotent(self):
        deck = _make_deck("ABC123")
        dm = _manager()
        target_id = device_id_for_serial("ABC123")
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            first = dm.open_device(target_id)
            second = dm.open_device(target_id)
        assert_that(first).is_same_as(second)
        # once in list_devices (temporary probe), once in _open_device (permanent open)
        assert_that(deck.open.call_count).is_equal_to(2)

    def test_raises_on_enumerate_error(self):
        dm = _manager()
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.side_effect = RuntimeError("no hidapi")
            with pytest.raises(RuntimeError):
                dm.open_device("abc12345")

    def test_registers_key_callback(self):
        deck = _make_deck("ABC123")
        events: list = []
        dm = DeviceManager(on_key_event=lambda did, ki, pressed: events.append((did, ki, pressed)))
        target_id = device_id_for_serial("ABC123")
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            dm.open_device(target_id)
        cb = deck.set_key_callback.call_args[0][0]
        cb(deck, 3, True)
        assert_that(events).contains((target_id, 3, True))


class TestDeviceManagerSetImageBytes:
    def test_no_op_for_unknown_device(self):
        dm = _manager()
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = []
            dm.set_image_bytes("unknown-id", 0, b"bytes")  # should not raise

    def test_hardware_error_is_caught(self):
        deck = _make_deck("ABC123")
        deck.set_key_image.side_effect = RuntimeError("hw failure")
        dm = _manager()
        target_id = device_id_for_serial("ABC123")
        with (
            patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm,
            patch("decker.server.devices.AssetRenderer") as mock_renderer_cls,
        ):
            mock_renderer_cls.return_value.render_bytes.return_value = None
            mock_dm.return_value.enumerate.return_value = [deck]
            dm.open_device(target_id)
            dm.set_image_bytes(target_id, 0, b"bytes")  # should not raise


class TestDeviceManagerDestroy:
    def test_resets_and_closes_open_devices(self):
        deck = _make_deck("ABC123")
        dm = _manager()
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            dm.open_device(device_id_for_serial("ABC123"))
        dm.destroy()
        deck.reset.assert_called()

    def test_handles_close_errors_gracefully(self):
        deck = _make_deck("ABC123")
        deck.reset.side_effect = RuntimeError("hw error")
        dm = _manager()
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            dm.open_device(device_id_for_serial("ABC123"))
        dm.destroy()  # should not raise


class TestDevice:
    def test_set_image_bytes_pushes_native_image(self):
        deck = _make_deck()
        with (
            patch("decker.server.devices.PILHelper") as mock_pil,
            patch("decker.server.devices.AssetRenderer") as mock_renderer_cls,
        ):
            mock_renderer_cls.return_value.render_bytes.return_value = MagicMock()
            mock_pil.create_scaled_key_image.return_value = MagicMock()  # PIL Image mock
            mock_pil.to_native_key_format.return_value = b"native"
            device = Device("abc12345", "ABC123", deck)
            device.set_image_bytes(0, b"img")
        deck.set_key_image.assert_called_once_with(0, b"native")

    def test_close_resets_and_closes_deck(self):
        deck = _make_deck()
        device = Device("abc12345", "ABC123", deck)
        device.close()
        deck.reset.assert_called_once()
        deck.close.assert_called_once()


class TestDeviceClearKeyImage:
    def test_blanks_key_and_forgets_cached_image(self):
        deck = _make_deck()
        device = Device("abc12345", "ABC123", deck)

        device.clear_key_image(2)

        deck.set_key_image.assert_called_once_with(2, None)
        assert_that(device.get_key_image(2)).is_none()

    def test_hardware_error_is_caught(self):
        deck = _make_deck()
        deck.set_key_image.side_effect = OSError("unplugged")
        device = Device("abc12345", "ABC123", deck)

        device.clear_key_image(0)  # should not raise


class TestDeviceManagerPages:
    def _open(self, dm: DeviceManager, deck: MagicMock):
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            return dm.open_device(device_id_for_serial("ABC123"))

    def _manager_with_store(self, tmp_path, active_page: str) -> tuple[DeviceManager, DeviceStateStore]:
        store = DeviceStateStore(data_dir=tmp_path)
        store.create(MagicMock())
        store.save_device = MagicMock()  # type: ignore[method-assign]  # mocked deck info is not storable
        context = MagicMock()
        context.device_state_store = store
        context.page_controller.active_page_id.return_value = active_page
        dm = _manager()
        dm.create(context)
        return dm, store

    def test_opened_device_tracks_active_page(self, tmp_path):
        dm, store = self._manager_with_store(tmp_path, "p-active")

        device = self._open(dm, _make_deck("ABC123"))
        assert device is not None
        state = dm.get_device_state(device.device_id)

        assert state is not None
        assert_that(state.page_id).is_equal_to("p-active")
        dm.destroy()
        store.destroy()

    def test_show_page_draws_cached_images_and_blanks_the_rest(self, tmp_path):
        dm, store = self._manager_with_store(tmp_path, "p1")
        device = self._open(dm, _make_deck("ABC123"))
        assert device is not None
        store.save_key_image(device.device_id, "p2", 1, b"img1")
        store.save_key_label(device.device_id, "p2", 4, "Four")

        with (
            patch.object(device, "set_image_bytes") as set_image,
            patch.object(device, "clear_key_image") as clear_image,
        ):
            assert_that(dm.show_page(device.device_id, "p2")).is_true()

        set_image.assert_called_once_with(1, b"img1")
        assert_that(clear_image.call_count).is_equal_to(14)
        state = dm.get_device_state(device.device_id)
        assert state is not None
        assert_that(state.page_id).is_equal_to("p2")
        assert_that(state.get_key_state(4).label).is_equal_to("Four")
        dm.destroy()
        store.destroy()

    def test_show_page_returns_false_for_unavailable_device(self):
        dm = _manager()
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = []
            assert_that(dm.show_page("nope", "p1")).is_false()

    def test_clear_key_state_without_open_device_uses_active_page(self, tmp_path):
        dm, store = self._manager_with_store(tmp_path, "p-active")
        store.save_key_label("dev1", "p-active", 0, "x")
        store.save_key_label("dev1", "other", 0, "y")

        dm.clear_key_state("dev1", 0)

        assert_that(store.get_key_label("dev1", "p-active", 0)).is_none()
        assert_that(store.get_key_label("dev1", "other", 0)).is_equal_to("y")
        dm.destroy()
        store.destroy()


class TestBlankKey:
    def test_clears_the_cached_state_and_the_hardware_key(self, tmp_path):
        helper = TestDeviceManagerPages()
        dm, store = helper._manager_with_store(tmp_path, "p1")  # pylint: disable=protected-access
        device = helper._open(dm, _make_deck("ABC123"))  # pylint: disable=protected-access
        assert device is not None
        store.save_key_label(device.device_id, "p1", 2, "Two")
        state = dm.get_device_state(device.device_id)
        assert state is not None
        state.update_key_label(2, "Two")

        with patch.object(device, "clear_key_image") as clear_image:
            dm.blank_key(device.device_id, 2)

        clear_image.assert_called_once_with(2)
        assert_that(store.get_key_label(device.device_id, "p1", 2)).is_none()
        dm.destroy()
        store.destroy()

    def test_unavailable_device_is_a_no_op(self):
        dm = _manager()
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = []
            dm.blank_key("nope", 0)


class TestDeviceWatcher:
    """After a PC sleep the USB handle is dead: the watcher must notice, reopen and redraw the device."""

    @staticmethod
    def _deck(serial: str = "ABC123", path: str | None = None) -> MagicMock:
        deck = _make_deck(serial)
        deck.id.return_value = path or f"/dev/hidraw-{serial}"
        deck.get_firmware_version.return_value = "1.0"
        deck.deck_type.return_value = "Stream Deck"
        deck.vendor_id.return_value = 1
        deck.product_id.return_value = 2
        return deck

    @pytest.fixture(name="watched")
    def watched_fixture(self, tmp_path):
        store = DeviceStateStore(data_dir=tmp_path)
        store.create(MagicMock())
        store.save_device = MagicMock()  # type: ignore[method-assign]
        context = MagicMock()
        context.device_state_store = store
        context.page_controller.active_page_id.return_value = "p1"
        dm = _manager()
        dm.create(context)
        yield dm, context
        dm.destroy()
        store.destroy()

    @staticmethod
    def _enumerate(*decks):
        patcher = patch("decker.server.devices.manager._HardwareDeviceManager")
        mock = patcher.start()
        mock.return_value.enumerate.return_value = list(decks)
        return patcher

    @staticmethod
    def _pushed(context):
        return [(c.args[0], json.loads(c.args[1])) for c in context.event_bus.push.call_args_list]

    def test_a_new_device_is_opened_restored_and_announced(self, watched):
        dm, context = watched
        deck = self._deck()
        patcher = self._enumerate(deck)

        dm.check_devices()
        patcher.stop()

        device_id = device_id_for_serial("ABC123")
        assert_that(dm.get_device_state(device_id)).is_not_none()
        context.page_controller.restore.assert_called_once_with(device_id)
        assert_that(self._pushed(context)).is_equal_to([("devices_changed", {"device_id": device_id})])
        deck.set_key_callback.assert_called_once()

    def test_healthy_devices_are_left_alone(self, watched):
        dm, context = watched
        patcher = self._enumerate(self._deck())

        dm.check_devices()
        context.reset_mock()
        dm.check_devices()
        dm.check_devices()
        patcher.stop()

        context.page_controller.restore.assert_not_called()
        context.event_bus.push.assert_not_called()

    def test_a_device_that_stops_answering_is_dropped_closed_and_reported(self, watched):
        dm, context = watched
        deck = self._deck()
        patcher = self._enumerate(deck)
        dm.check_devices()
        patcher.stop()
        context.reset_mock()
        deck.get_serial_number.side_effect = OSError("device went away")
        patcher = self._enumerate()  # nothing is plugged in while the PC sleeps

        dm.check_devices()
        patcher.stop()

        assert_that(dm._devices).is_empty()  # pylint: disable=protected-access
        deck.close.assert_called()
        context.page_controller.restore.assert_not_called()
        device_id = device_id_for_serial("ABC123")
        assert_that(self._pushed(context)).is_equal_to([("devices_changed", {"device_id": device_id})])

    def test_a_device_that_comes_back_is_reopened_restored_and_announced(self, watched):
        dm, context = watched
        old = self._deck(path="/dev/hidraw3")
        patcher = self._enumerate(old)
        dm.check_devices()
        patcher.stop()
        old.get_serial_number.side_effect = OSError("gone")
        patcher = self._enumerate()
        dm.check_devices()
        patcher.stop()
        context.reset_mock()
        new = self._deck(path="/dev/hidraw7")  # the same deck, with a new device path after the wake
        patcher = self._enumerate(new)

        dm.check_devices()
        patcher.stop()

        device_id = device_id_for_serial("ABC123")
        context.page_controller.restore.assert_called_once_with(device_id)
        new.set_key_callback.assert_called_once()
        assert_that(dm.get_device_state(device_id)).is_not_none()
        assert_that(self._pushed(context)).is_equal_to([("devices_changed", {"device_id": device_id})])

    def test_a_new_device_is_evaluated_against_app_rules_after_restore(self, watched):
        dm, context = watched
        patcher = self._enumerate(self._deck())

        dm.check_devices()
        patcher.stop()

        context.app_rule_engine.evaluate_device.assert_called_once_with(device_id_for_serial("ABC123"))

    def test_a_lost_device_is_forgotten_by_the_app_rule_engine(self, watched):
        dm, context = watched
        deck = self._deck()
        patcher = self._enumerate(deck)
        dm.check_devices()
        patcher.stop()
        deck.get_serial_number.side_effect = OSError("gone")
        patcher = self._enumerate()

        dm.check_devices()
        patcher.stop()

        context.app_rule_engine.forget_device.assert_called_once_with(device_id_for_serial("ABC123"))

    def test_a_lost_device_that_is_already_back_in_the_same_pass_is_reopened_at_once(self, watched):
        dm, context = watched
        old = self._deck(path="/dev/hidraw3")
        patcher = self._enumerate(old)
        dm.check_devices()
        patcher.stop()
        context.reset_mock()
        old.get_serial_number.side_effect = OSError("gone")
        new = self._deck(path="/dev/hidraw4")
        patcher = self._enumerate(new)

        dm.check_devices()
        patcher.stop()

        context.page_controller.restore.assert_called_once_with(device_id_for_serial("ABC123"))

    def test_an_open_failure_is_retried_on_the_next_pass(self, watched):
        dm, context = watched
        stubborn = self._deck()
        stubborn.open.side_effect = OSError("busy")
        patcher = self._enumerate(stubborn)
        dm.check_devices()
        patcher.stop()
        assert_that(dm._devices).is_empty()  # pylint: disable=protected-access
        context.page_controller.restore.assert_not_called()

        patcher = self._enumerate(self._deck())
        dm.check_devices()
        patcher.stop()

        context.page_controller.restore.assert_called_once_with(device_id_for_serial("ABC123"))

    def test_one_bad_deck_does_not_stop_the_others(self, watched):
        dm, context = watched
        bad = self._deck("BAD", path="/dev/hidraw1")
        bad.open.side_effect = OSError("busy")
        good = self._deck("GOOD", path="/dev/hidraw2")
        patcher = self._enumerate(bad, good)

        dm.check_devices()
        patcher.stop()

        context.page_controller.restore.assert_called_once_with(device_id_for_serial("GOOD"))

    def test_an_enumeration_failure_changes_nothing(self, watched):
        dm, context = watched
        patcher = patch("decker.server.devices.manager._HardwareDeviceManager")
        mock = patcher.start()
        mock.return_value.enumerate.side_effect = OSError("hid broke")

        dm.check_devices()
        patcher.stop()

        context.event_bus.push.assert_not_called()

    def test_a_failing_restore_does_not_break_the_pass(self, watched):
        dm, context = watched
        context.page_controller.restore.side_effect = RuntimeError("boom")
        patcher = self._enumerate(self._deck("A", "/dev/hidraw1"), self._deck("B", "/dev/hidraw2"))

        dm.check_devices()
        patcher.stop()

        assert_that(context.page_controller.restore.call_count).is_equal_to(2)

    def test_the_watcher_runs_passes_until_stopped_and_survives_errors(self, watched):
        import time

        dm, _context = watched
        calls: list[int] = []

        def check():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("boom")

        dm.check_devices = check

        dm.start_watching(0.01)
        deadline = time.monotonic() + 3
        while len(calls) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        dm.stop_watching()
        settled = len(calls)
        time.sleep(0.05)

        assert_that(settled).is_greater_than_or_equal_to(3)
        assert_that(len(calls)).is_equal_to(settled)

    def test_start_watching_twice_runs_one_watcher(self, watched):
        import threading

        dm, _context = watched
        dm.check_devices = lambda: None

        dm.start_watching(0.05)
        dm.start_watching(0.05)

        assert_that([t for t in threading.enumerate() if t.name == "device-watch"]).is_length(1)
        dm.stop_watching()

    def test_destroy_stops_the_watcher(self, watched):
        import threading

        dm, _context = watched
        dm.check_devices = lambda: None
        dm.start_watching(0.05)

        dm.destroy()

        assert_that([t for t in threading.enumerate() if t.name == "device-watch"]).is_empty()


def _png(color: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (72, 72), color).save(buf, format="PNG")
    return buf.getvalue()


class TestDeviceManagerAnimations:
    """Animations play through each device's writer; page switches stop the old page's and restart the new one's."""

    @pytest.fixture(name="store")
    def store_fixture(self, tmp_path):
        store = DeviceStateStore(data_dir=tmp_path)
        store.create(MagicMock())
        store.save_device = MagicMock()  # type: ignore[method-assign]  # mocked deck info is not storable
        yield store
        store.destroy()

    @staticmethod
    def _open(store: DeviceStateStore, log: WriteLog) -> tuple[DeviceManager, str]:
        context = MagicMock()
        context.device_state_store = store
        context.page_controller.active_page_id.return_value = "p1"
        dm = _manager()
        dm.create(context)
        deck = _make_deck("ABC123")
        deck.set_key_image.side_effect = log
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = [deck]
            device = dm.open_device(device_id_for_serial("ABC123"))
        assert device is not None
        return dm, device.device_id

    @pytest.fixture(name="opened")
    def opened_fixture(self, store):
        log = WriteLog()
        dm, device_id = self._open(store, log)
        yield dm, device_id, log
        dm.destroy()

    @staticmethod
    def _animate(dm: DeviceManager, device_id: str, key_index: int, log: WriteLog) -> None:
        dm.set_image_bytes(device_id, key_index, _png("red"))  # the poster
        dm.set_animation(device_id, key_index, make_spec())
        assert_that(wait_until(lambda: len(log.for_key(key_index)) >= 3)).is_true()

    def test_set_animation_plays_on_the_writer_and_records_the_spec(self, opened):
        dm, device_id, log = opened

        self._animate(dm, device_id, 2, log)

        assert_that({write[2] for write in log.for_key(2)}).is_equal_to({WRITER_THREAD})
        state = dm.get_device_state(device_id)
        assert state is not None
        assert_that(state.get_key_animation(2)).is_not_none()

    def test_show_page_leaves_no_writes_to_previous_page_keys_after_it_returns(self, opened, store):
        dm, device_id, log = opened
        store.save_key_image(device_id, "p2", 2, _png("red"))  # same image as the poster: the redraw skips it
        self._animate(dm, device_id, 2, log)
        self._animate(dm, device_id, 5, log)

        assert_that(dm.show_page(device_id, "p2")).is_true()
        returned_at = time.monotonic()
        time.sleep(0.4)  # four frame periods

        stale = [write[0] for write in log.writes if write[3] > returned_at]
        assert_that(stale).is_empty()

    def test_show_page_restarts_animations_recorded_for_the_new_page(self, opened):
        dm, device_id, log = opened
        self._animate(dm, device_id, 2, log)
        dm.show_page(device_id, "p2")

        assert_that(dm.show_page(device_id, "p1")).is_true()
        returned_at = time.monotonic()

        assert_that(wait_until(lambda: len([w for w in log.for_key(2) if w[3] > returned_at]) >= 2)).is_true()
        frames = {write[1] for write in log.for_key(2) if write[3] > returned_at}
        assert_that(len(frames)).is_greater_than_or_equal_to(2)

    def test_a_static_image_forgets_the_recorded_animation(self, opened):
        dm, device_id, log = opened
        self._animate(dm, device_id, 2, log)

        dm.set_image_bytes(device_id, 2, _png("blue"))

        state = dm.get_device_state(device_id)
        assert state is not None
        assert_that(state.get_key_animation(2)).is_none()

    def test_playing_animation_id_follows_what_the_key_actually_plays(self, opened):
        dm, device_id, log = opened
        animation_id = make_spec().animation_id
        assert_that(dm.playing_animation_id(device_id, 2)).is_none()

        self._animate(dm, device_id, 2, log)
        assert_that(dm.playing_animation_id(device_id, 2)).is_equal_to(animation_id)
        dm.show_page(device_id, "p2")
        assert_that(dm.playing_animation_id(device_id, 2)).is_none()
        dm.show_page(device_id, "p1")
        assert_that(dm.playing_animation_id(device_id, 2)).is_equal_to(animation_id)
        dm.set_image_bytes(device_id, 2, _png("blue"))
        assert_that(dm.playing_animation_id(device_id, 2)).is_none()

        self._animate(dm, device_id, 2, log)
        dm.close_device(device_id)
        assert_that(dm.playing_animation_id(device_id, 2)).is_none()
        assert_that(dm.playing_animation_id("nope", 2)).is_none()

    def test_clear_key_state_forgets_the_animation(self, opened):
        dm, device_id, log = opened
        self._animate(dm, device_id, 2, log)

        dm.clear_key_state(device_id, 2)

        state = dm.get_device_state(device_id)
        assert state is not None
        assert_that(state.get_key_animation(2)).is_none()
        assert_that(state.get_all_animations()).is_empty()

    def test_clear_key_state_stops_the_keys_animation(self, opened):
        dm, device_id, log = opened
        self._animate(dm, device_id, 2, log)
        self._animate(dm, device_id, 5, log)

        dm.clear_key_state(device_id, 2)
        time.sleep(0.15)  # a frame already under way may still land
        key2, key5 = len(log.for_key(2)), len(log.for_key(5))
        time.sleep(0.35)

        assert_that(len(log.for_key(2))).is_equal_to(key2)
        assert_that(len(log.for_key(5))).is_greater_than(key5)

    def test_delete_stored_key_state_drops_the_animation_of_a_page_that_is_not_shown(self, opened, store):
        dm, device_id, log = opened
        self._animate(dm, device_id, 2, log)
        dm.show_page(device_id, "p2")

        dm.delete_stored_key_state(device_id, "p1", 2)
        store.save_key_image(device_id, "p1", 2, _png("red"))  # a new poster appears under the same key
        dm.show_page(device_id, "p1")

        assert_that(dm.playing_animation_id(device_id, 2)).is_none()

    def test_animation_disabled_in_config_keeps_the_static_poster_only(self, store, monkeypatch):
        real = config.get_as_or_default
        monkeypatch.setattr(
            "decker.server.devices.manager.config.get_as_or_default",
            lambda path, kind, default: False if path == "animation.enabled" else real(path, kind, default),
        )
        log = WriteLog()
        dm, device_id = self._open(store, log)
        try:
            dm.set_image_bytes(device_id, 2, _png("red"))
            accepted = dm.set_animation(device_id, 2, make_spec())
            time.sleep(0.4)
            state = dm.get_device_state(device_id)
            assert state is not None
            recorded = state.get_key_animation(2)
        finally:
            dm.destroy()

        assert_that(len(log.for_key(2))).is_equal_to(1)
        assert_that(accepted).is_false()
        assert_that(recorded).is_none()

    def test_set_animation_for_an_unavailable_device_is_a_no_op(self):
        dm = _manager()
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = []
            dm.set_animation("nope", 0, make_spec())

    def test_create_builds_one_shared_factory_and_destroy_closes_it(self, store):
        log = WriteLog()
        dm, _device_id = self._open(store, log)
        factory = dm.animation_factory
        assert factory is not None

        dm.destroy()

        assert_that(dm.animation_factory).is_none()
        assert_that(factory.frames_for(make_spec(), MagicMock(), 90)).is_none()  # closed: never builds


class TestAnimationSettingsAreClamped:
    @staticmethod
    def _created(monkeypatch, settings: dict[str, float]) -> DeviceManager:
        real = config.get_as_or_default
        monkeypatch.setattr(
            "decker.server.devices.manager.config.get_as_or_default",
            lambda path, kind, default: settings.get(path, real(path, kind, default)),
        )
        dm = _manager()
        dm.create(MagicMock())
        return dm

    @pytest.mark.parametrize(
        ("percent", "used"), [(30, 0.30), (-5, 0.10), (0, 0.10), (5, 0.10), (150, 0.90), (91, 0.90), (75, 0.75)]
    )
    def test_budget_percent_is_clamped_to_10_to_90_with_one_warning(self, monkeypatch, caplog, percent, used):
        dm = self._created(monkeypatch, {"animation.budget_percent": percent})
        try:
            warned = [r for r in caplog.records if "animation.budget_percent" in r.getMessage()]
            assert_that(dm._animation_budget).is_close_to(used, 1e-9)  # pylint: disable=protected-access
            assert_that(warned).is_length(0 if 10 <= percent <= 90 else 1)
            if warned:
                assert_that(warned[0].getMessage()).contains(str(percent)).contains(f"using {used * 100}")
        finally:
            dm.destroy()

    @pytest.mark.parametrize(("megabytes", "used"), [(0, 1), (-3, 1), (1, 1), (64, 64)])
    def test_cache_mb_is_at_least_1_with_one_warning(self, monkeypatch, caplog, megabytes, used):
        dm = self._created(monkeypatch, {"animation.cache_mb": megabytes})
        try:
            warned = [r for r in caplog.records if "animation.cache_mb" in r.getMessage()]
            assert dm.animation_factory is not None
            assert_that(dm.animation_factory._cache_bytes).is_equal_to(
                used * 1024 * 1024
            )  # pylint: disable=protected-access
            assert_that(warned).is_length(1 if megabytes < 1 else 0)
        finally:
            dm.destroy()


class TestLostAnimatingDevice:
    """A deck that vanishes (PC sleep) while animating must be dropped and fully closed, and never evict its successor."""

    @pytest.fixture(name="watched")
    def watched_fixture(self, tmp_path):
        store = DeviceStateStore(data_dir=tmp_path)
        store.create(MagicMock())
        store.save_device = MagicMock()  # type: ignore[method-assign]
        context = MagicMock()
        context.device_state_store = store
        context.page_controller.active_page_id.return_value = "p1"
        dm = _manager()
        dm.create(context)
        yield dm
        dm.destroy()
        store.destroy()

    @staticmethod
    def _check(dm: DeviceManager, *decks: MagicMock) -> None:
        with patch("decker.server.devices.manager._HardwareDeviceManager") as mock_dm:
            mock_dm.return_value.enumerate.return_value = list(decks)
            dm.check_devices()

    @staticmethod
    def _writers() -> list[str]:
        return [t.name for t in threading.enumerate() if t.name == WRITER_THREAD and t.is_alive()]

    def _animating(self, dm: DeviceManager, path: str) -> tuple[MagicMock, Device, WriteLog]:
        deck = stateful_deck(path=path)
        log = WriteLog()
        deck.set_key_image.side_effect = log
        self._check(dm, deck)
        device_id = device_id_for_serial("ABC123")
        device = dm._devices[device_id]  # pylint: disable=protected-access
        dm.set_image_bytes(device_id, 2, _png("red"))
        dm.set_animation(device_id, 2, make_spec())
        assert_that(wait_until(lambda: len(log.for_key(2)) >= 3)).is_true()
        return deck, device, log

    @staticmethod
    def _go_away(deck: MagicMock) -> None:
        deck.get_serial_number.side_effect = OSError("device went away")
        deck.set_key_image.side_effect = OSError("device went away")

    def test_a_static_write_to_a_lost_animating_deck_drops_and_closes_it(self, watched):
        dm = watched
        deck, _device, _log = self._animating(dm, "/dev/hidraw3")
        self._go_away(deck)

        dm.set_image_bytes(device_id_for_serial("ABC123"), 4, _png("blue"))

        assert_that(dm._devices).is_empty()  # pylint: disable=protected-access
        deck.reset.assert_called_once()
        deck.close.assert_called_once()
        assert_that(wait_until(lambda: not self._writers())).is_true()

    def test_the_watcher_closes_a_lost_animating_deck_once_and_its_writer_ends(self, watched):
        dm = watched
        deck, _device, _log = self._animating(dm, "/dev/hidraw3")
        self._go_away(deck)

        self._check(dm)

        assert_that(dm._devices).is_empty()  # pylint: disable=protected-access
        deck.reset.assert_called_once()
        deck.close.assert_called_once()
        assert_that(wait_until(lambda: not self._writers())).is_true()

    def test_a_stale_device_failing_later_does_not_evict_the_reopened_one(self, watched):
        dm = watched
        old_deck, stale, _log = self._animating(dm, "/dev/hidraw3")
        self._go_away(old_deck)
        new_deck = stateful_deck(path="/dev/hidraw7")

        self._check(dm, new_deck)
        reopened = dm._devices[device_id_for_serial("ABC123")]  # pylint: disable=protected-access
        stale.set_image_bytes(4, _png("blue"))
        stale.play_animation(2, make_spec())
        assert_that(stale.try_validate()).is_false()

        assert_that(reopened).is_not_same_as(stale)
        assert_that(dm._devices).is_equal_to(
            {device_id_for_serial("ABC123"): reopened}
        )  # pylint: disable=protected-access
        old_deck.reset.assert_called_once()
        new_deck.close.assert_not_called()

    @staticmethod
    def _assert_closed_for_good(deck: MagicMock) -> None:
        calls = lifecycle(deck)
        assert_that(calls[-1]).is_equal_to("close")
        assert_that(calls[calls.index("reset") :]).is_equal_to(["reset", "close"])
        assert_that(deck.is_open()).is_false()

    def test_a_lost_deck_ends_closed_with_no_open_after_close(self, watched):
        dm = watched
        deck, _device, _log = self._animating(dm, "/dev/hidraw3")
        self._go_away(deck)

        dm.set_image_bytes(device_id_for_serial("ABC123"), 4, _png("blue"))

        self._assert_closed_for_good(deck)

    def test_the_watcher_leaves_a_lost_deck_closed_with_no_open_after_close(self, watched):
        dm = watched
        deck, _device, _log = self._animating(dm, "/dev/hidraw3")
        self._go_away(deck)

        self._check(dm)

        self._assert_closed_for_good(deck)

    def test_a_stale_device_never_reopens_its_deck_and_the_reopened_one_keeps_working(self, watched):
        events: list[tuple[str, int, bool]] = []
        dm = watched
        dm._on_key_event_cb = lambda *event: events.append(event)  # pylint: disable=protected-access
        old_deck, stale, _log = self._animating(dm, "/dev/hidraw3")
        stale_callback = old_deck.set_key_callback.call_args[0][0]
        self._go_away(old_deck)
        new_deck = stateful_deck(path="/dev/hidraw7")
        new_log = WriteLog()
        new_deck.set_key_image.side_effect = new_log
        self._check(dm, new_deck)
        old_deck.reset_mock()

        stale.set_image_bytes(4, _png("blue"))
        stale.clear_key_image(5)
        assert_that(stale.validate).raises(DeckNotOpenedError).when_called_with()
        stale_callback(old_deck, 1, True)  # a press arriving on the old handle
        device_id = device_id_for_serial("ABC123")
        dm.set_image_bytes(device_id, 4, _png("green"))
        new_deck.set_key_callback.call_args[0][0](new_deck, 2, True)

        old_deck.open.assert_not_called()
        assert_that(old_deck.is_open()).is_false()
        assert_that(new_log.for_key(4)).is_length(1)
        assert_that(events).is_equal_to([(device_id, 2, True)])
