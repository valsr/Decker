import json
from typing import Any

from assertpy import assert_that
from PyQt6.QtGui import QStandardItemModel

from decker.client.widgets.profile_edit import ProfileEdit

# pylint: disable=unused-argument


class FakeRpc:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[Any, ...]] = []

    def call(self, method: str, *args: Any) -> Any:
        self.calls.append((method, *args))
        if self.fail:
            raise RuntimeError("down")
        profiles = [
            {"profile_id": 0, "name": "Default"},
            {"profile_id": 2, "name": "Work"},
            {"profile_id": 1, "name": "Play"},
        ]
        return json.dumps({"device_id": args[0], "profiles": profiles, "active_profile_id": 0})


def _edit(rpc: FakeRpc | None = None, device: str | None = "dev-1") -> ProfileEdit:
    fake = rpc if rpc is not None else FakeRpc()
    return ProfileEdit(lambda: device, lambda: fake)


def _texts(edit: ProfileEdit) -> list[str]:
    return [edit.itemText(i) for i in range(edit.count())]


def test_lists_current_then_the_devices_profiles_in_dropdown_order(qapp):
    assert_that(_texts(_edit())).is_equal_to(["(current profile)", "Default", "Work", "Play"])


def test_value_is_blank_or_the_decimal_id(qapp):
    edit = _edit()
    assert_that(edit.value()).is_equal_to("")

    edit.set_value("2")

    assert_that(edit.value()).is_equal_to("2")
    assert_that(edit.currentText()).is_equal_to("Work")


def test_selecting_emits_and_updates_value(qapp):
    edit = _edit()
    seen: list[int] = []
    edit.value_changed.connect(lambda: seen.append(1))

    edit.setCurrentIndex(3)
    edit.activated.emit(3)

    assert_that(edit.value()).is_equal_to("1")
    assert_that(seen).is_length(1)


def test_set_value_emits_nothing_and_garbage_means_current(qapp):
    edit = _edit()
    seen: list[int] = []
    edit.value_changed.connect(lambda: seen.append(1))

    edit.set_value("x")
    assert_that(edit.value()).is_equal_to("")
    edit.set_value(None)
    edit.set_value(2)

    assert_that(edit.value()).is_equal_to("")
    assert_that(seen).is_empty()


def test_unknown_stored_id_shows_a_disabled_deleted_entry_and_keeps_the_value(qapp):
    edit = _edit()

    edit.set_value("9")

    assert_that(edit.currentText()).is_equal_to("(deleted profile)")
    assert_that(edit.value()).is_equal_to("9")
    model = edit.model()
    assert isinstance(model, QStandardItemModel)
    item = model.item(edit.currentIndex())
    assert item is not None
    assert_that(item.isEnabled()).is_false()


def test_without_a_device_only_current_is_listed_and_a_hint_is_shown(qapp):
    edit = _edit(device=None)

    assert_that(_texts(edit)).is_equal_to(["(current profile)"])
    assert_that(edit.toolTip()).is_not_empty()


def test_rpc_failure_lists_only_current(qapp):
    assert_that(_texts(_edit(FakeRpc(fail=True)))).is_equal_to(["(current profile)"])
