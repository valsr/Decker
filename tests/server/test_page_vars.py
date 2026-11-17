from types import MappingProxyType

import pytest
from assertpy import assert_that

from decker.common.icon_ref import DECKER_ICON_REF
from decker.common.model import PageInfo, ProfileInfo
from decker.plugin.settings_schema import parse_settings_schema
from decker.server.page_vars import (
    DeviceLayout,
    deliver_settings,
    has_dynamic_fields,
    page_variables,
    resolve_page,
    resolve_profile,
    resolve_profile_switch_target,
    resolve_switch_target,
    stored_profile_ids,
)

P1, P2, Q1 = PageInfo("p1", "One"), PageInfo("p2", "Two"), PageInfo("q1", "Other")
PROFILES = (ProfileInfo(0, "Default", ""), ProfileInfo(2, "Work", "pack:a/b.svg"), ProfileInfo(1, "Play", ""))


def _layout(active_profile=0, active_page="p1"):
    by_profile = {0: (P1, P2), 2: (Q1,), 1: ()}
    return DeviceLayout(
        pages=by_profile[active_profile],
        active_page_id=active_page,
        profiles=PROFILES,
        active_profile_id=active_profile,
        pages_by_profile=MappingProxyType(by_profile),
    )


class TestVariables:
    def test_page_and_profile_variables(self):
        assert_that(page_variables(_layout())).is_equal_to(
            {"page_name": "One", "page_index": "1", "page_count": "2", "current_profile": "Default", "profile_id": "0"}
        )

    def test_profile_id_is_the_id_not_the_position(self):
        variables = page_variables(_layout(active_profile=2, active_page="q1"))

        assert_that(variables["current_profile"]).is_equal_to("Work")
        assert_that(variables["profile_id"]).is_equal_to("2")

    def test_empty_layout_has_no_variables(self):
        assert_that(page_variables(DeviceLayout())).is_empty()


class TestResolveProfile:
    def test_blank_follows_the_active_profile(self):
        assert_that(resolve_profile(_layout(active_profile=2, active_page="q1"), "")).is_equal_to(
            {"profile_id": 2, "name": "Work", "index": 2, "icon": "pack:a/b.svg"}
        )

    def test_id_resolves_with_dropdown_position_and_decker_icon_fallback(self):
        assert_that(resolve_profile(_layout(), "1")).is_equal_to(
            {"profile_id": 1, "name": "Play", "index": 3, "icon": DECKER_ICON_REF}
        )

    @pytest.mark.parametrize("value", ["7", None, 5, "x", "-1", " 1", True])
    def test_unknown_or_garbage_is_empty(self, value):
        assert_that(resolve_profile(_layout(), value)).is_equal_to(
            {"profile_id": -1, "name": "", "index": 0, "icon": ""}
        )


class TestResolvePage:
    def test_page_in_another_profile_carries_its_profile(self):
        assert_that(resolve_page(_layout(), "q1")).is_equal_to(
            {"page_id": "q1", "name": "Other", "index": 1, "profile_id": 2}
        )

    def test_active_page_and_missing_page(self):
        assert_that(resolve_page(_layout(), "p2")).is_equal_to(
            {"page_id": "p2", "name": "Two", "index": 2, "profile_id": 0}
        )
        assert_that(resolve_page(_layout(), "gone")).is_equal_to(
            {"page_id": "", "name": "", "index": 0, "profile_id": -1}
        )
        assert_that(resolve_page(_layout(), 5)).is_equal_to({"page_id": "", "name": "", "index": 0, "profile_id": -1})


class TestDeliverSettings:
    SCHEMA = parse_settings_schema(
        [
            {"key": "profile", "type": "profile"},
            {"key": "page", "type": "page", "profile_field": "profile"},
            {"key": "title", "type": "text", "template": True},
        ],
        "here",
    )

    def test_profile_and_page_are_resolved_and_templates_expanded(self):
        layout = _layout()
        settings = {"profile": "2", "page": "q1", "title": "{current_profile}/{profile_id}"}

        delivered = deliver_settings(self.SCHEMA, settings, layout)

        assert_that(delivered["profile"]["name"]).is_equal_to("Work")
        assert_that(delivered["page"]["profile_id"]).is_equal_to(2)
        assert_that(delivered["title"]).is_equal_to("Default/0")
        assert_that(settings["profile"]).is_equal_to("2")  # the input is left raw

    def test_has_dynamic_fields_includes_profile(self):
        schema = parse_settings_schema([{"key": "profile", "type": "profile"}], "here")

        assert_that(has_dynamic_fields(schema)).is_true()


class TestStoredProfileIds:
    SCHEMA = TestDeliverSettings.SCHEMA

    def test_unchanged_echo_keeps_the_stored_follow_current_value(self):
        delivered = {"profile": resolve_profile(_layout(), "")}

        result = stored_profile_ids(self.SCHEMA, {"profile": delivered["profile"]}, delivered, {"profile": ""})

        assert_that(result["profile"]).is_equal_to("")

    def test_changed_echo_stores_the_decimal_id(self):
        delivered = {"profile": resolve_profile(_layout(), "")}
        chosen = resolve_profile(_layout(), "2")

        assert_that(
            stored_profile_ids(self.SCHEMA, {"profile": chosen}, delivered, {"profile": ""})["profile"]
        ).is_equal_to("2")

    def test_empty_resolved_value_stores_blank_and_strings_pass_through(self):
        empty = resolve_profile(_layout(), "9")

        assert_that(stored_profile_ids(self.SCHEMA, {"profile": empty}, {}, {})["profile"]).is_equal_to("")
        assert_that(stored_profile_ids(self.SCHEMA, {"profile": "1"}, {}, {})["profile"]).is_equal_to("1")


class TestSwitchTargets:
    def test_page_in_another_profile_is_a_valid_target(self):
        assert_that(resolve_switch_target(_layout(), {"page_id": "q1"})).is_equal_to("q1")

    def test_relative_moves_stay_in_the_active_profile(self):
        assert_that(resolve_switch_target(_layout(), {"to": "next"})).is_equal_to("p2")
        assert_that(resolve_switch_target(_layout(), {"to": "previous", "wrap": True})).is_equal_to("p2")
        assert_that(resolve_switch_target(_layout(), {"to": "previous"})).is_none()

    def test_unknown_same_or_garbage_page_is_refused(self):
        assert_that(resolve_switch_target(_layout(), {"page_id": "p1"})).is_none()
        assert_that(resolve_switch_target(_layout(), {"page_id": "gone"})).is_none()
        assert_that(resolve_switch_target(_layout(), {"page_id": 3})).is_none()

    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            ({"profile_id": 2}, 2),
            ({"profile_id": 0}, None),
            ({"profile_id": 9}, None),
            ({"profile_id": True}, None),
            ({"profile_id": "1"}, None),
            ({"profile_id": None}, None),
            ({"to": "next"}, 2),
            ({"to": "last"}, 1),
            ({"to": "first"}, None),
            ({"to": "previous"}, None),
            ({"to": "previous", "wrap": True}, 1),
            ({"to": "sideways"}, None),
            ({}, None),
        ],
    )
    def test_profile_switch_targets(self, payload, expected):
        assert_that(resolve_profile_switch_target(_layout(), payload)).is_equal_to(expected)

    def test_single_profile_has_no_target(self):
        layout = DeviceLayout(profiles=(ProfileInfo(0, "Default", ""),), active_profile_id=0)

        assert_that(resolve_profile_switch_target(layout, {"to": "next", "wrap": True})).is_none()
