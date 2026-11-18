import threading
import time

import pytest
from assertpy import assert_that

from decker.animation.cache import SizedLru


def _wait_for_waiters(lru: SizedLru, key: str, count: int) -> None:
    deadline = time.monotonic() + 5
    while lru.waiters(key) < count:
        assert time.monotonic() < deadline, "waiters never arrived"
        time.sleep(0)


def test_evicts_least_recently_used_until_under_budget() -> None:
    lru = SizedLru(10)
    lru.put("a", "A", 4)
    lru.put("b", "B", 4)
    assert_that(lru.get("a")).is_equal_to("A")

    lru.put("c", "C", 4)

    assert_that(lru.get("b")).is_none()
    assert_that(lru.get("a")).is_equal_to("A")
    assert_that(lru.get("c")).is_equal_to("C")
    assert_that(lru.size_bytes).is_equal_to(8)


def test_putting_an_existing_key_replaces_its_size() -> None:
    lru = SizedLru(10)
    lru.put("a", "A", 4)
    lru.put("a", "A2", 6)

    assert_that(lru.get("a")).is_equal_to("A2")
    assert_that(lru.size_bytes).is_equal_to(6)


def test_entry_larger_than_budget_is_returned_but_not_stored() -> None:
    lru = SizedLru(10)
    lru.put("small", "S", 2)

    value = lru.get_or_build("big", lambda: ("BIG", 11))

    assert_that(value).is_equal_to("BIG")
    assert_that(lru.get("big")).is_none()
    assert_that(lru.get("small")).is_equal_to("S")
    assert_that(lru.size_bytes).is_equal_to(2)


def test_get_or_build_builds_once_under_concurrent_callers() -> None:
    lru = SizedLru(100)
    release = threading.Event()
    calls: list[int] = []
    results: list[object] = []

    def build() -> tuple[object, int]:
        calls.append(1)
        release.wait(5)
        return "value", 5

    threads = [threading.Thread(target=lambda: results.append(lru.get_or_build("k", build))) for _ in range(8)]
    for thread in threads:
        thread.start()
    _wait_for_waiters(lru, "k", 7)
    release.set()
    for thread in threads:
        thread.join(5)

    assert_that(calls).is_length(1)
    assert_that(results).is_length(8).contains_only("value")
    assert_that(lru.waiters("k")).is_zero()


def test_waiters_see_the_builders_exception_and_the_next_call_rebuilds() -> None:
    lru = SizedLru(100)
    release = threading.Event()
    errors: list[BaseException] = []

    def failing() -> tuple[object, int]:
        release.wait(5)
        raise RuntimeError("boom")

    def call() -> None:
        try:
            lru.get_or_build("k", failing)
        except RuntimeError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=call) for _ in range(3)]
    for thread in threads:
        thread.start()
    _wait_for_waiters(lru, "k", 2)
    release.set()
    for thread in threads:
        thread.join(5)

    assert_that(errors).is_length(3)
    assert_that(lru.get_or_build("k", lambda: ("ok", 1))).is_equal_to("ok")


def test_builder_exception_propagates_to_the_caller() -> None:
    lru = SizedLru(100)

    def failing() -> tuple[object, int]:
        raise ValueError("bad")

    with pytest.raises(ValueError):
        lru.get_or_build("k", failing)
    assert_that(lru.get("k")).is_none()
