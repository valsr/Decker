import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that

from decker.common.model import DeviceHardwareInfo, KeyInfo
from decker.server.device_state_store import DeviceStateStore
from decker.server.pages import initial_page_id


def _make_hw_info(
    device_id: str = "dev1",
    serial: str = "SN001",
    num_keys: int = 6,
    path: str = "/dev/usb1",
) -> DeviceHardwareInfo:
    keys = [KeyInfo(row=r, col=c, pixel_width=72, pixel_height=72, type="key") for r in range(2) for c in range(3)]
    return DeviceHardwareInfo(
        id=device_id,
        type="Stream Deck",
        vendor_id=0x0FD9,
        product_id=0x0060,
        num_keys=num_keys,
        keys=keys,
        serial=serial,
        path=path,
    )


@pytest.fixture()
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        s = DeviceStateStore(data_dir=Path(tmpdir))
        s.create(MagicMock())
        yield s
        s.destroy()


class TestDeviceStateStoreDevices:
    def test_get_device_returns_none_for_unknown(self, store):
        assert_that(store.get_device("unknown")).is_none()

    def test_save_and_get_device_round_trip(self, store):
        info = _make_hw_info()
        store.save_device(info)
        result = store.get_device("dev1")
        assert result is not None
        assert_that(result.id).is_equal_to("dev1")
        assert_that(result.type).is_equal_to("Stream Deck")
        assert_that(result.serial).is_equal_to("SN001")
        assert_that(result.path).is_equal_to("/dev/usb1")
        assert_that(result.num_keys).is_equal_to(6)
        assert_that(result.keys).is_length(6)
        assert_that(result.keys[0].row).is_equal_to(0)
        assert_that(result.keys[0].col).is_equal_to(0)
        assert_that(result.keys[0].pixel_width).is_equal_to(72)

    def test_save_device_upserts(self, store):
        store.save_device(_make_hw_info(path="/dev/usb1"))
        store.save_device(_make_hw_info(path="/dev/usb2"))
        result = store.get_device("dev1")
        assert result is not None
        assert_that(result.path).is_equal_to("/dev/usb2")

    def test_save_device_ignores_none_id(self, store):
        info = _make_hw_info()
        info_no_id = DeviceHardwareInfo(
            id=None,
            type=info.type,
            vendor_id=info.vendor_id,
            product_id=info.product_id,
            num_keys=info.num_keys,
            keys=info.keys,
        )
        store.save_device(info_no_id)
        assert_that(store.get_all_devices()).is_empty()

    def test_get_all_devices_returns_all(self, store):
        store.save_device(_make_hw_info("dev1", "SN001"))
        store.save_device(_make_hw_info("dev2", "SN002"))
        results = store.get_all_devices()
        ids = {r.id for r in results}
        assert_that(ids).contains("dev1", "dev2")

    def test_get_all_devices_empty_initially(self, store):
        assert_that(store.get_all_devices()).is_empty()


class TestDeviceStateStoreKeyImages:
    def test_get_key_image_returns_none_for_missing(self, store):
        assert_that(store.get_key_image("dev1", "p1", 0)).is_none()

    def test_save_and_get_key_image_round_trip(self, store):
        store.save_key_image("dev1", "p1", 0, b"\x89PNG\r\n")
        result = store.get_key_image("dev1", "p1", 0)
        assert_that(result).is_equal_to(b"\x89PNG\r\n")

    def test_save_key_image_upserts(self, store):
        store.save_key_image("dev1", "p1", 0, b"old")
        store.save_key_image("dev1", "p1", 0, b"new")
        assert_that(store.get_key_image("dev1", "p1", 0)).is_equal_to(b"new")

    def test_get_all_key_images_returns_all_for_device(self, store):
        store.save_key_image("dev1", "p1", 0, b"img0")
        store.save_key_image("dev1", "p1", 2, b"img2")
        store.save_key_image("dev2", "p1", 0, b"other")
        pairs = store.get_all_key_images("dev1", "p1")
        indices = {k for k, _ in pairs}
        assert_that(pairs).is_length(2)
        assert_that(indices).contains(0, 2)

    def test_get_all_key_images_empty_for_unknown_device(self, store):
        assert_that(store.get_all_key_images("no-such-device", "p1")).is_empty()

    def test_delete_key_image_removes_entry(self, store):
        store.save_key_image("dev1", "p1", 0, b"img")
        store.delete_key_state("dev1", "p1", 0)
        assert_that(store.get_key_image("dev1", "p1", 0)).is_none()

    def test_delete_key_image_no_op_for_missing(self, store):
        store.delete_key_state("dev1", "p1", 99)  # should not raise

    def test_binary_image_data_preserved(self, store):
        data = bytes(range(256)) * 10
        store.save_key_image("dev1", "p1", 3, data)
        assert_that(store.get_key_image("dev1", "p1", 3)).is_equal_to(data)


class TestDeviceStateStoreKeyLabels:
    def test_get_key_label_returns_none_for_missing(self, store):
        assert_that(store.get_key_label("dev1", "p1", 0)).is_none()

    def test_save_and_get_key_label_round_trip(self, store):
        store.save_key_label("dev1", "p1", 0, "Play")
        assert_that(store.get_key_label("dev1", "p1", 0)).is_equal_to("Play")

    def test_save_key_label_upserts(self, store):
        store.save_key_label("dev1", "p1", 0, "old")
        store.save_key_label("dev1", "p1", 0, "new")
        assert_that(store.get_key_label("dev1", "p1", 0)).is_equal_to("new")

    def test_get_all_key_labels_returns_all_for_device(self, store):
        store.save_key_label("dev1", "p1", 0, "Play")
        store.save_key_label("dev1", "p1", 1, "Stop")
        store.save_key_label("dev2", "p1", 0, "Other")
        pairs = store.get_all_key_labels("dev1", "p1")
        assert_that(pairs).is_length(2)
        label_map = dict(pairs)
        assert_that(label_map[0]).is_equal_to("Play")
        assert_that(label_map[1]).is_equal_to("Stop")

    def test_get_all_key_labels_empty_for_unknown_device(self, store):
        assert_that(store.get_all_key_labels("no-such-device", "p1")).is_empty()

    def test_delete_key_label_removes_entry(self, store):
        store.save_key_label("dev1", "p1", 0, "Play")
        store.delete_key_state("dev1", "p1", 0)
        assert_that(store.get_key_label("dev1", "p1", 0)).is_none()

    def test_delete_key_label_no_op_for_missing(self, store):
        store.delete_key_state("dev1", "p1", 99)  # should not raise


class TestDeviceStateStoreDeleteKeyState:
    def test_delete_key_state_removes_image_and_label(self, store):
        store.save_key_image("dev1", "p1", 0, b"img")
        store.save_key_label("dev1", "p1", 0, "Play")
        store.delete_key_state("dev1", "p1", 0)
        assert_that(store.get_key_image("dev1", "p1", 0)).is_none()
        assert_that(store.get_key_label("dev1", "p1", 0)).is_none()

    def test_delete_key_state_no_op_for_missing(self, store):
        store.delete_key_state("dev1", "p1", 99)  # should not raise

    def test_delete_all_key_state_for_device_clears_that_device(self, store):
        store.save_key_image("dev1", "p1", 0, b"img")
        store.save_key_label("dev1", "p1", 0, "Play")
        store.save_key_image("dev2", "p1", 1, b"other")
        store.delete_all_key_state_for_device("dev1")
        assert_that(store.get_key_image("dev1", "p1", 0)).is_none()
        assert_that(store.get_key_label("dev1", "p1", 0)).is_none()
        assert_that(store.get_key_image("dev2", "p1", 1)).is_equal_to(b"other")

    def test_delete_all_key_state_clears_every_device(self, store):
        store.save_key_image("dev1", "p1", 0, b"img1")
        store.save_key_label("dev1", "p1", 0, "Play")
        store.save_key_image("dev2", "p1", 1, b"img2")
        store.delete_all_key_state()
        assert_that(store.get_all_key_images("dev1", "p1")).is_empty()
        assert_that(store.get_all_key_labels("dev1", "p1")).is_empty()
        assert_that(store.get_all_key_images("dev2", "p1")).is_empty()


class TestDeviceStateStorePages:
    @pytest.fixture()
    def store(self, tmp_path):
        s = DeviceStateStore(data_dir=tmp_path)
        s.create(MagicMock())
        yield s
        s.destroy()

    def test_pages_are_isolated(self, store):
        store.save_key_image("dev1", "p1", 0, b"one")
        store.save_key_image("dev1", "p2", 0, b"two")
        store.save_key_label("dev1", "p2", 0, "Two")

        assert_that(store.get_key_image("dev1", "p1", 0)).is_equal_to(b"one")
        assert_that(store.get_all_key_images("dev1", "p2")).is_equal_to([(0, b"two")])
        assert_that(store.get_key_label("dev1", "p1", 0)).is_none()

    def test_delete_page_state_removes_only_that_page(self, store):
        store.save_key_image("dev1", "p1", 0, b"one")
        store.save_key_image("dev1", "p2", 0, b"two")
        store.save_key_label("dev1", "p2", 1, "Two")

        store.delete_page_state("dev1", "p2")

        assert_that(store.get_all_key_images("dev1", "p2")).is_empty()
        assert_that(store.get_all_key_labels("dev1", "p2")).is_empty()
        assert_that(store.get_key_image("dev1", "p1", 0)).is_equal_to(b"one")

    def test_migrates_pre_page_tables_to_first_page(self, tmp_path):
        legacy = sqlite3.connect(tmp_path / "device-dev1.db")
        legacy.execute(
            "CREATE TABLE key_images (key_index INTEGER PRIMARY KEY, image BLOB NOT NULL, updated_at DATETIME)"
        )
        legacy.execute(
            "CREATE TABLE key_labels (key_index INTEGER PRIMARY KEY, label TEXT NOT NULL, updated_at DATETIME)"
        )
        legacy.execute("INSERT INTO key_images (key_index, image) VALUES (2, ?)", (b"old",))
        legacy.execute("INSERT INTO key_labels (key_index, label) VALUES (2, 'Old')")
        legacy.commit()
        legacy.close()
        store = DeviceStateStore(data_dir=tmp_path)
        store.create(MagicMock())

        page = initial_page_id("dev1")
        assert_that(store.get_key_image("dev1", page, 2)).is_equal_to(b"old")
        assert_that(store.get_key_label("dev1", page, 2)).is_equal_to("Old")
        tables = {
            row[0]
            for row in (
                sqlite3.connect(tmp_path / "device-dev1.db")
                .execute("SELECT name FROM sqlite_master WHERE type = 'table'")
                .fetchall()
            )
        }
        assert_that(tables).does_not_contain("key_images", "key_labels")
        store.destroy()


class TestCopyPageState:
    @pytest.fixture()
    def store(self, tmp_path):
        s = DeviceStateStore(data_dir=tmp_path)
        s.create(MagicMock())
        yield s
        s.destroy()

    def test_copies_images_and_labels_and_leaves_source(self, store):
        store.save_key_image("dev1", "p1", 0, b"one")
        store.save_key_label("dev1", "p1", 1, "lbl")

        store.copy_page_state("dev1", "p1", "p2")

        assert_that(store.get_all_key_images("dev1", "p2")).is_equal_to([(0, b"one")])
        assert_that(store.get_key_label("dev1", "p2", 1)).is_equal_to("lbl")
        assert_that(store.get_all_key_images("dev1", "p1")).is_equal_to([(0, b"one")])

    def test_copy_of_empty_page_does_nothing(self, store):
        store.copy_page_state("dev1", "none", "p2")

        assert_that(store.get_all_key_images("dev1", "p2")).is_empty()
