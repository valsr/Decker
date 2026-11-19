"""Tests for decker.server.reconfigure."""

import pytest
from assertpy import assert_that

from decker.server.reconfigure import RESTART_EXIT_CODE, ReconfigurePolicy

_LOOPBACKS = ["127.0.0.1", "::1", "::ffff:127.0.0.1"]


def test_restart_exit_code_is_75() -> None:
    assert_that(RESTART_EXIT_CODE).is_equal_to(75)


@pytest.mark.parametrize("peer", [*_LOOPBACKS, "10.1.2.3", None])
def test_disabled_denies_everyone(peer: str | None) -> None:
    assert_that(ReconfigurePolicy(None).allows(peer)).is_false()


def test_bare_allows_any_known_peer() -> None:
    policy = ReconfigurePolicy([])
    assert_that(policy.allows("10.1.2.3")).is_true()
    assert_that(policy.allows("::1")).is_true()


def test_bare_denies_unknown_peer() -> None:
    assert_that(ReconfigurePolicy([]).allows(None)).is_false()


@pytest.mark.parametrize("peer", ["10.0.0.5", *_LOOPBACKS])
def test_list_allows_listed_and_loopback(peer: str) -> None:
    assert_that(ReconfigurePolicy(["10.0.0.5"]).allows(peer)).is_true()


def test_list_denies_others() -> None:
    assert_that(ReconfigurePolicy(["10.0.0.5"]).allows("10.0.0.6")).is_false()


def test_list_matches_ipv6_forms() -> None:
    policy = ReconfigurePolicy(["fe80::0001"])
    assert_that(policy.allows("fe80::1")).is_true()


def test_hostname_is_resolved_once() -> None:
    policy = ReconfigurePolicy(["localhost"])
    assert_that(policy.allows("127.0.0.1")).is_true()
    assert_that(policy.allows("10.9.9.9")).is_false()


def test_unresolvable_host_is_ignored() -> None:
    policy = ReconfigurePolicy(["no-such-host.invalid"])
    assert_that(policy.allows("10.9.9.9")).is_false()
    assert_that(policy.allows("127.0.0.1")).is_true()
