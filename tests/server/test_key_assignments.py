import tempfile
from pathlib import Path

import pytest
from assertpy import assert_that

from decker.plugin.context import ActionTarget
from decker.server.key_assignments import KeyAssignment, KeyAssignmentStore


def _target(device_id="dev1", key_index=0, plugin="com.p", action="com.p.a", ctx="ctx1"):
    return ActionTarget(
        plugin_uuid=plugin, action_uuid=action, context_id=ctx, device_id=device_id, key_index=key_index
    )


@pytest.fixture()
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        s = KeyAssignmentStore(db_path=Path(tmpdir) / "test.db")
        yield s
        s.close()


class TestKeyAssignmentStore:
    def test_get_returns_none_for_unassigned_slot(self, store):
        assert_that(store.get("dev1", 0)).is_none()

    def test_assign_and_get_round_trip(self, store):
        target = _target()
        store.assign("dev1", 0, target, {"step": 2})
        result = store.get("dev1", 0)
        assert result is not None
        assert_that(result.target.plugin_uuid).is_equal_to("com.p")
        assert_that(result.settings["step"]).is_equal_to(2)

    def test_assign_replaces_previous(self, store):
        store.assign("dev1", 0, _target(ctx="ctx1"), {"step": 1})
        store.assign("dev1", 0, _target(ctx="ctx2"), {"step": 5})
        result = store.get("dev1", 0)
        assert result is not None
        assert_that(result.target.context_id).is_equal_to("ctx2")
        assert_that(result.settings["step"]).is_equal_to(5)

    def test_unassign_removes_slot(self, store):
        store.assign("dev1", 0, _target(), {})
        store.unassign("dev1", 0)
        assert_that(store.get("dev1", 0)).is_none()

    def test_unassign_is_no_op_when_unassigned(self, store):
        store.unassign("dev1", 99)  # should not raise

    def test_update_settings_returns_true_on_success(self, store):
        store.assign("dev1", 0, _target(), {"step": 1})
        assert_that(store.update_settings("dev1", 0, {"step": 3, "max": 10})).is_true()
        result = store.get("dev1", 0)
        assert result is not None
        assert_that(result.settings["step"]).is_equal_to(3)
        assert_that(result.settings["max"]).is_equal_to(10)

    def test_update_settings_returns_false_for_missing_slot(self, store):
        assert_that(store.update_settings("dev1", 99, {"step": 1})).is_false()

    def test_all_for_device_returns_all_slots(self, store):
        store.assign("dev1", 0, _target(key_index=0), {"step": 1})
        store.assign("dev1", 3, _target(key_index=3, ctx="c3"), {"step": 2})
        store.assign("dev2", 0, _target(device_id="dev2", key_index=0), {})
        pairs = store.all_for_device("dev1")
        assert_that(pairs).is_length(2)
        indices = {k for k, _ in pairs}
        assert_that(indices).contains(0, 3)

    def test_all_for_device_returns_empty_for_unknown_device(self, store):
        assert_that(store.all_for_device("no-such-device")).is_empty()

    def test_settings_are_persisted_as_json(self, store):
        settings = {"step": 5, "max": 100, "label": "test"}
        store.assign("dev1", 0, _target(), settings)
        result = store.get("dev1", 0)
        assert result is not None
        assert_that(result.settings).is_equal_to(settings)
