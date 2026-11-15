import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that

from decker.plugin.context import ActionTarget
from decker.server.key_assignments import KeyAssignment, KeyAssignmentStore
from decker.server.pages import initial_page_id


def _target(device_id="dev1", key_index=0, plugin="com.p", action="com.p.a", ctx="ctx1"):
    return ActionTarget(
        plugin_uuid=plugin, action_uuid=action, context_id=ctx, device_id=device_id, key_index=key_index
    )


@pytest.fixture()
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        s = KeyAssignmentStore(db_path=Path(tmpdir) / "test.db")
        s.create(MagicMock())
        yield s
        s.destroy()


class TestKeyAssignmentStore:
    def test_get_returns_none_for_unassigned_slot(self, store):
        assert_that(store.get("dev1", "p1", 0)).is_none()

    def test_assign_and_get_round_trip(self, store):
        target = _target()
        store.assign("dev1", "p1", 0, target, {"step": 2})
        result = store.get("dev1", "p1", 0)
        assert result is not None
        assert_that(result.target.plugin_uuid).is_equal_to("com.p")
        assert_that(result.settings["step"]).is_equal_to(2)

    def test_assign_replaces_previous(self, store):
        store.assign("dev1", "p1", 0, _target(ctx="ctx1"), {"step": 1})
        store.assign("dev1", "p1", 0, _target(ctx="ctx2"), {"step": 5})
        result = store.get("dev1", "p1", 0)
        assert result is not None
        assert_that(result.target.context_id).is_equal_to("ctx2")
        assert_that(result.settings["step"]).is_equal_to(5)

    def test_unassign_removes_slot(self, store):
        store.assign("dev1", "p1", 0, _target(), {})
        store.unassign("dev1", "p1", 0)
        assert_that(store.get("dev1", "p1", 0)).is_none()

    def test_unassign_is_no_op_when_unassigned(self, store):
        store.unassign("dev1", "p1", 99)  # should not raise

    def test_update_settings_returns_true_on_success(self, store):
        store.assign("dev1", "p1", 0, _target(), {"step": 1})
        assert_that(store.update_settings("dev1", "p1", 0, {"step": 3, "max": 10})).is_true()
        result = store.get("dev1", "p1", 0)
        assert result is not None
        assert_that(result.settings["step"]).is_equal_to(3)
        assert_that(result.settings["max"]).is_equal_to(10)

    def test_update_settings_returns_false_for_missing_slot(self, store):
        assert_that(store.update_settings("dev1", "p1", 99, {"step": 1})).is_false()

    def test_all_for_page_returns_all_slots(self, store):
        store.assign("dev1", "p1", 0, _target(key_index=0), {"step": 1})
        store.assign("dev1", "p1", 3, _target(key_index=3, ctx="c3"), {"step": 2})
        store.assign("dev2", "p1", 0, _target(device_id="dev2", key_index=0), {})
        pairs = store.all_for_page("dev1", "p1")
        assert_that(pairs).is_length(2)
        indices = {k for k, _ in pairs}
        assert_that(indices).contains(0, 3)

    def test_all_for_page_returns_empty_for_unknown_device(self, store):
        assert_that(store.all_for_page("no-such-device", "p1")).is_empty()

    def test_settings_are_persisted_as_json(self, store):
        settings = {"step": 5, "max": 100, "label": "test"}
        store.assign("dev1", "p1", 0, _target(), settings)
        result = store.get("dev1", "p1", 0)
        assert result is not None
        assert_that(result.settings).is_equal_to(settings)


class TestPages:
    def test_same_key_on_different_pages_is_independent(self, store):
        store.assign("dev1", "p1", 0, _target(ctx="one"), {})
        store.assign("dev1", "p2", 0, _target(ctx="two"), {})

        first = store.get("dev1", "p1", 0)
        second = store.get("dev1", "p2", 0)
        assert first is not None and second is not None
        assert_that(first.target.context_id).is_equal_to("one")
        assert_that(second.target.context_id).is_equal_to("two")

    def test_all_for_page_only_returns_that_page_in_key_order(self, store):
        store.assign("dev1", "p1", 4, _target(key_index=4, ctx="a"), {})
        store.assign("dev1", "p1", 1, _target(key_index=1, ctx="b"), {})
        store.assign("dev1", "p2", 0, _target(ctx="c"), {})

        assert_that([k for k, _ in store.all_for_page("dev1", "p1")]).is_equal_to([1, 4])

    def test_delete_page_removes_only_that_page(self, store):
        store.assign("dev1", "p1", 0, _target(ctx="a"), {})
        store.assign("dev1", "p2", 0, _target(ctx="b"), {})

        store.delete_page("dev1", "p2")

        assert_that(store.all_for_page("dev1", "p2")).is_empty()
        assert_that(store.get("dev1", "p1", 0)).is_not_none()

    def test_migrates_pre_page_rows_to_each_devices_first_page(self, tmp_path):
        db = tmp_path / "legacy.db"
        legacy = sqlite3.connect(db)
        legacy.execute("""CREATE TABLE key_assignments (device_id TEXT NOT NULL, key_index INTEGER NOT NULL,
            plugin_uuid TEXT NOT NULL, action_uuid TEXT NOT NULL, context_id TEXT NOT NULL,
            settings TEXT NOT NULL DEFAULT '{}', PRIMARY KEY (device_id, key_index))""")
        legacy.execute("INSERT INTO key_assignments VALUES ('dev1', 2, 'com.p', 'com.p.a', 'c1', '{\"step\": 3}')")
        legacy.execute("INSERT INTO key_assignments VALUES ('dev2', 0, 'com.p', 'com.p.a', 'c2', '{}')")
        legacy.commit()
        legacy.close()

        migrated = KeyAssignmentStore(db_path=db)
        migrated.create(MagicMock())

        first = migrated.get("dev1", initial_page_id("dev1"), 2)
        assert first is not None
        assert_that(first.settings).is_equal_to({"step": 3})
        assert_that(migrated.get("dev2", initial_page_id("dev2"), 0)).is_not_none()
        migrated.destroy()

        reopened = KeyAssignmentStore(db_path=db)
        reopened.create(MagicMock())
        assert_that(reopened.all_for_page("dev1", initial_page_id("dev1"))).is_length(1)
        reopened.destroy()
