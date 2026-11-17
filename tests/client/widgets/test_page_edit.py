import json
from typing import Any

import pytest
from assertpy import assert_that
from PyQt6.QtGui import QStandardItemModel

from decker.client.widgets.page_edit import PageEdit

# pylint: disable=unused-argument


class FakeRpc:
    def __init__(self, pages: list[tuple[str, str]] | None = None, fail: bool = False) -> None:
        self.pages = pages if pages is not None else [("p1", "Home"), ("p2", "Settings"), ("p3", "Media")]
        self.fail = fail
        self.calls: list[tuple[Any, ...]] = []

    def call(self, method: str, *args: Any) -> Any:
        self.calls.append((method, *args))
        if self.fail:
            raise RuntimeError("down")
        return json.dumps({"pages": [{"page_id": i, "name": n} for i, n in self.pages]})


def _edit(rpc: FakeRpc | None = None, device: str | None = "dev-1") -> PageEdit:
    fake = rpc if rpc is not None else FakeRpc()
    return PageEdit(lambda: device, lambda: fake)


def _texts(edit: PageEdit) -> list[str]:
    return [edit.itemText(i) for i in range(edit.count())]


def test_lists_the_devices_pages_in_order_with_a_no_page_entry(qapp):
    assert_that(_texts(_edit())).is_equal_to(["(no page)", "Home", "Settings", "Media"])


def test_value_is_the_page_id_not_the_name(qapp):
    edit = _edit()
    edit.set_value("p2")

    assert_that(edit.value()).is_equal_to("p2")
    assert_that(edit.currentText()).is_equal_to("Settings")


def test_selecting_emits_value_changed_and_updates_value(qapp):
    edit = _edit()
    seen: list[int] = []
    edit.value_changed.connect(lambda: seen.append(1))

    edit.setCurrentIndex(3)
    edit.activated.emit(3)

    assert_that(edit.value()).is_equal_to("p3")
    assert_that(seen).is_length(1)


def test_set_value_emits_nothing(qapp):
    edit = _edit()
    seen: list[int] = []
    edit.value_changed.connect(lambda: seen.append(1))

    edit.set_value("p2")

    assert_that(seen).is_empty()


def test_unknown_stored_id_shows_deleted_page_and_keeps_the_value(qapp):
    edit = _edit()
    edit.set_value("gone")

    assert_that(edit.currentText()).is_equal_to("(deleted page)")
    assert_that(edit.value()).is_equal_to("gone")
    model = edit.model()
    assert isinstance(model, QStandardItemModel)
    item = model.item(edit.currentIndex())
    assert item is not None
    assert_that(item.isEnabled()).is_false()


@pytest.mark.parametrize("value", [5, None, {"x": 1}])
def test_garbage_value_becomes_no_page(qapp, value):
    edit = _edit()
    edit.set_value(value)

    assert_that(edit.value()).is_equal_to("")
    assert_that(edit.currentText()).is_equal_to("(no page)")


def test_no_device_or_connection_does_not_crash(qapp):
    edit = _edit(device=None)
    edit.set_value("p2")

    assert_that(_texts(edit)).is_equal_to(["(no page)"])
    assert_that(edit.toolTip()).is_equal_to("Select a key on a device first")
    assert_that(edit.value()).is_equal_to("p2")
    assert_that(PageEdit(lambda: "dev-1", lambda: None).count()).is_equal_to(1)


def test_rpc_failure_does_not_crash(qapp):
    assert_that(_texts(_edit(FakeRpc(fail=True)))).is_equal_to(["(no page)"])


def test_renamed_page_shows_its_new_name_after_reload(qapp):
    rpc = FakeRpc()
    edit = _edit(rpc)
    edit.set_value("p2")

    rpc.pages = [("p1", "Home"), ("p2", "Renamed"), ("p3", "Media")]
    edit.reload()

    assert_that(edit.currentText()).is_equal_to("Renamed")


class ProfileAwareRpc(FakeRpc):
    def call(self, method: str, *args: Any) -> Any:
        self.calls.append((method, *args))
        pages = {(): self.pages, (2,): [("w1", "Docs"), ("w2", "Mail")]}[tuple(args[1:])]
        return json.dumps({"pages": [{"page_id": i, "name": n} for i, n in pages]})


def test_without_a_profile_the_default_call_is_unchanged(qapp):
    rpc = ProfileAwareRpc()
    _edit(rpc)

    assert_that(rpc.calls).is_equal_to([("pages_list", "dev-1")])


def test_blank_profile_lists_the_current_profiles_pages(qapp):
    rpc = ProfileAwareRpc()
    edit = _edit(rpc)

    edit.set_profile("")

    assert_that(rpc.calls[-1]).is_equal_to(("pages_list", "dev-1"))


def test_a_chosen_profile_lists_that_profiles_pages(qapp):
    rpc = ProfileAwareRpc()
    edit = _edit(rpc)

    edit.set_profile("2")

    assert_that(rpc.calls[-1]).is_equal_to(("pages_list", "dev-1", 2))
    assert_that(_texts(edit)).is_equal_to(["(no page)", "Docs", "Mail"])


def test_changing_profile_clears_a_page_that_is_not_in_the_new_list_and_notifies(qapp):
    edit = _edit(ProfileAwareRpc())
    edit.set_value("p2")
    seen: list[int] = []
    edit.value_changed.connect(lambda: seen.append(1))

    edit.set_profile("2", clear_missing=True)

    assert_that(edit.value()).is_equal_to("")
    assert_that(seen).is_length(1)


def test_changing_profile_keeps_a_page_that_is_still_listed_without_notifying(qapp):
    edit = _edit(ProfileAwareRpc())
    edit.set_value("p2")
    seen: list[int] = []
    edit.value_changed.connect(lambda: seen.append(1))

    edit.set_profile("", clear_missing=True)

    assert_that(edit.value()).is_equal_to("p2")
    assert_that(seen).is_empty()


def test_initial_profile_keeps_a_missing_page_so_it_shows_as_deleted(qapp):
    edit = _edit(ProfileAwareRpc())
    edit.set_value("p2")

    edit.set_profile("2")

    assert_that(edit.value()).is_equal_to("p2")
    assert_that(edit.currentText()).is_equal_to("(deleted page)")


def test_garbage_profile_values_mean_current(qapp):
    rpc = ProfileAwareRpc()
    edit = _edit(rpc)

    for bad in (None, 5, "x", "-1"):
        edit.set_profile(bad)
        assert_that(rpc.calls[-1]).is_equal_to(("pages_list", "dev-1"))
