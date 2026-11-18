import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that

from decker.animation.model import AnimationSpec
from decker.common.model import KeyPressState
from decker.server.device_state_store import DeviceStateStore
from decker.server.devices.state import DeviceState, PerKeyState


def _make_store(tmpdir: str) -> DeviceStateStore:
    s = DeviceStateStore(data_dir=Path(tmpdir))
    s.create(MagicMock())
    return s


def _make_state(store: DeviceStateStore | None = None, press_state: KeyPressState = KeyPressState.UP) -> DeviceState:
    return DeviceState(
        device_id="dev1",
        store=store,
        press_state_getter=lambda _: press_state,
        page_id="p1",
    )


class TestPerKeyState:
    def test_defaults(self):
        s = PerKeyState(key_index=3)
        assert_that(s.image).is_none()
        assert_that(s.label).is_equal_to("")
        assert_that(s.press_state).is_equal_to(KeyPressState.UP)


class TestDeviceStateImages:
    def test_get_key_state_returns_none_image_for_unset_key(self):
        state = _make_state()
        assert_that(state.get_key_state(0).image).is_none()

    def test_update_key_image_stored_in_memory(self):
        state = _make_state()
        state.update_key_image(2, b"PNG")
        assert_that(state.get_key_state(2).image).is_equal_to(b"PNG")

    def test_update_key_image_persists_to_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store(tmpdir)
            state = _make_state(store)
            state.update_key_image(1, b"PNG")
            assert_that(store.get_key_image("dev1", "p1", 1)).is_equal_to(b"PNG")
            store.destroy()

    def test_update_key_image_no_store_does_not_raise(self):
        state = _make_state(store=None)
        state.update_key_image(0, b"PNG")
        assert_that(state.get_key_state(0).image).is_equal_to(b"PNG")

    def test_get_all_images_returns_all_stored(self):
        state = _make_state()
        state.update_key_image(0, b"img0")
        state.update_key_image(2, b"img2")
        pairs = dict(state.get_all_images())
        assert_that(pairs).is_length(2)
        assert_that(pairs[0]).is_equal_to(b"img0")
        assert_that(pairs[2]).is_equal_to(b"img2")

    def test_get_all_images_empty_when_no_images(self):
        assert_that(_make_state().get_all_images()).is_empty()


class TestDeviceStateLabels:
    def test_get_key_state_returns_empty_label_for_unset_key(self):
        state = _make_state()
        assert_that(state.get_key_state(0).label).is_equal_to("")

    def test_update_key_label_stored_in_memory(self):
        state = _make_state()
        state.update_key_label(1, "Play")
        assert_that(state.get_key_state(1).label).is_equal_to("Play")

    def test_update_key_label_persists_to_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store(tmpdir)
            state = _make_state(store)
            state.update_key_label(3, "Stop")
            assert_that(store.get_key_label("dev1", "p1", 3)).is_equal_to("Stop")
            store.destroy()

    def test_update_key_label_no_store_does_not_raise(self):
        state = _make_state(store=None)
        state.update_key_label(0, "Play")
        assert_that(state.get_key_state(0).label).is_equal_to("Play")

    def test_get_all_labels_returns_all_stored(self):
        state = _make_state()
        state.update_key_label(0, "A")
        state.update_key_label(1, "B")
        pairs = dict(state.get_all_labels())
        assert_that(pairs).is_length(2)
        assert_that(pairs[0]).is_equal_to("A")
        assert_that(pairs[1]).is_equal_to("B")


class TestDeviceStatePressState:
    def test_get_key_state_press_state_comes_from_getter(self):
        state = DeviceState("dev1", None, lambda _: KeyPressState.HELD, "p1")
        assert_that(state.get_key_state(0).press_state).is_equal_to(KeyPressState.HELD)

    def test_press_state_getter_receives_key_index(self):
        received: list[int] = []

        def getter(key_index: int) -> KeyPressState:
            received.append(key_index)
            return KeyPressState.UP

        state = DeviceState("dev1", None, getter, "p1")
        state.get_key_state(5)
        assert_that(received).contains(5)


class TestDeviceStateClearKey:
    def test_clear_key_removes_image_and_label_from_memory(self):
        state = _make_state()
        state.update_key_image(0, b"img")
        state.update_key_label(0, "Play")
        state.clear_key(0)
        ks = state.get_key_state(0)
        assert_that(ks.image).is_none()
        assert_that(ks.label).is_equal_to("")

    def test_clear_key_deletes_from_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store(tmpdir)
            state = _make_state(store)
            state.update_key_image(0, b"img")
            state.update_key_label(0, "Play")
            state.clear_key(0)
            assert_that(store.get_key_image("dev1", "p1", 0)).is_none()
            assert_that(store.get_key_label("dev1", "p1", 0)).is_none()
            store.destroy()

    def test_clear_key_no_op_for_unset_key(self):
        state = _make_state()
        state.clear_key(99)  # should not raise


class TestDeviceStateRestoreFromStore:
    def test_restore_loads_images_and_labels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store(tmpdir)
            store.save_key_image("dev1", "p1", 0, b"img0")
            store.save_key_image("dev1", "p1", 1, b"img1")
            store.save_key_label("dev1", "p1", 0, "Play")
            store.save_key_label("dev1", "p1", 2, "Stop")

            state = _make_state(store)
            state.restore_from_store()

            assert_that(state.get_key_state(0).image).is_equal_to(b"img0")
            assert_that(state.get_key_state(1).image).is_equal_to(b"img1")
            assert_that(state.get_key_state(0).label).is_equal_to("Play")
            assert_that(state.get_key_state(2).label).is_equal_to("Stop")
            store.destroy()

    def test_restore_no_op_without_store(self):
        state = _make_state(store=None)
        state.restore_from_store()  # should not raise

    def test_restore_empty_store_leaves_state_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store(tmpdir)
            state = _make_state(store)
            state.restore_from_store()
            assert_that(state.get_all_images()).is_empty()
            assert_that(state.get_all_labels()).is_empty()
            store.destroy()


class TestDeviceStatePages:
    def test_writes_go_to_current_page(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store(tmpdir)
            state = _make_state(store)

            state.update_key_image(0, b"on-p1")
            state.update_key_label(0, "P1")

            assert_that(state.page_id).is_equal_to("p1")
            assert_that(store.get_key_image("dev1", "p1", 0)).is_equal_to(b"on-p1")
            assert_that(store.get_key_image("dev1", "p2", 0)).is_none()
            store.destroy()

    def test_switch_page_loads_that_pages_state_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store(tmpdir)
            store.save_key_image("dev1", "p2", 3, b"on-p2")
            store.save_key_label("dev1", "p2", 4, "Two")
            state = _make_state(store)
            state.update_key_image(0, b"on-p1")

            state.switch_page("p2")

            assert_that(state.page_id).is_equal_to("p2")
            assert_that(state.get_all_images()).is_equal_to([(3, b"on-p2")])
            assert_that(state.get_all_labels()).is_equal_to([(4, "Two")])
            state.clear_key(3)
            assert_that(store.get_key_image("dev1", "p2", 3)).is_none()
            assert_that(store.get_key_image("dev1", "p1", 0)).is_equal_to(b"on-p1")
            store.destroy()

    def test_switch_page_without_store_just_clears(self):
        state = _make_state(store=None)
        state.update_key_image(0, b"img")

        state.switch_page("p2")

        assert_that(state.get_all_images()).is_empty()


class TestUnchangedImages:
    def test_an_identical_image_is_not_written_to_the_store_again(self):
        store = MagicMock()
        state = DeviceState(device_id="dev1", store=store, press_state_getter=lambda _: KeyPressState.UP, page_id="p1")

        state.update_key_image(0, b"one")
        state.update_key_image(0, b"one")
        state.update_key_image(0, b"two")

        assert_that(store.save_key_image.call_count).is_equal_to(2)

    def test_has_image_reports_cached_keys(self):
        state = _make_state()
        state.update_key_image(2, b"png")

        assert_that(state.has_image(2)).is_true()
        assert_that(state.has_image(3)).is_false()


class TestDeviceStateAnimations:
    def test_animations_are_per_page_and_in_memory_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _make_store(tmpdir)
            state = _make_state(store)
            on_p1 = AnimationSpec(b"gif1", {}, "", 1.0)
            on_p2 = AnimationSpec(b"gif2", {}, "", 1.0)
            state.set_key_animation(1, on_p1)

            state.switch_page("p2")
            assert_that(state.get_all_animations()).is_empty()
            state.set_key_animation(3, on_p2)
            state.switch_page("p1")

            assert_that(state.get_all_animations()).is_equal_to({1: on_p1})
            assert_that(state.get_key_animation(1)).is_same_as(on_p1)
            assert_that(state.get_key_animation(3)).is_none()
            reopened = _make_state(store)
            reopened.restore_from_store()
            assert_that(reopened.get_all_animations()).is_empty()
            store.destroy()

    def test_setting_none_forgets_the_animation(self):
        state = _make_state()
        state.set_key_animation(1, AnimationSpec(b"gif", {}, "", 1.0))

        state.set_key_animation(1, None)

        assert_that(state.get_key_animation(1)).is_none()

    def test_clear_key_drops_the_animation(self):
        state = _make_state()
        state.set_key_animation(1, AnimationSpec(b"gif", {}, "", 1.0))

        state.clear_key(1)

        assert_that(state.get_all_animations()).is_empty()

    def test_get_all_animations_is_a_copy(self):
        state = _make_state()
        state.set_key_animation(1, AnimationSpec(b"gif", {}, "", 1.0))

        state.get_all_animations().clear()

        assert_that(state.get_all_animations()).is_length(1)
