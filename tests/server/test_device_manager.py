"""Tests for DeviceManager."""

import json
from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that

from decker.server.device_state_store import DeviceStateStore
from decker.server.devices import Device
from decker.server.devices.manager import DeviceManager, device_id_for_serial


def _make_deck(serial: str = "ABC123") -> MagicMock:
    deck = MagicMock()
    deck.get_serial_number.return_value = serial
    opened = [False]
    deck.is_open.side_effect = lambda: opened[0]
    deck.open.side_effect = lambda: opened.__setitem__(0, True)
    deck.close.side_effect = lambda: opened.__setitem__(0, False)
    deck.KEY_PIXEL_WIDTH = 72
    deck.KEY_PIXEL_HEIGHT = 72
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
