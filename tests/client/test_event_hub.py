"""Tests for decker.client.events.event_manager — thread safety, singleton, subscribe/emit."""

import threading

from assertpy import assert_that

from decker.client.events import ServerConnectedEvent, ServerDisconnectedEvent
from decker.client.events.event_manager import EventManager


class TestEventManagerSingleton:
    def setup_method(self):
        EventManager.reset()

    def test_get_returns_same_instance(self):
        assert_that(EventManager.get()).is_same_as(EventManager.get())

    def test_reset_creates_fresh_instance(self):
        first = EventManager.get()
        EventManager.reset()
        assert_that(EventManager.get()).is_not_same_as(first)


class TestPushAndDrain:
    def setup_method(self):
        EventManager.reset()

    def test_drain_returns_pushed_events_in_order(self):
        em = EventManager.get()
        em.push(ServerConnectedEvent(host="a", port=1))
        em.push(ServerConnectedEvent(host="b", port=2))

        events = em.drain()

        assert_that(events).is_length(2)
        first, second = events
        assert isinstance(first, ServerConnectedEvent) and isinstance(second, ServerConnectedEvent)
        assert_that(first.host).is_equal_to("a")
        assert_that(second.host).is_equal_to("b")

    def test_drain_empties_the_queue(self):
        em = EventManager.get()
        em.push(ServerConnectedEvent(host="a", port=1))
        em.drain()

        assert_that(em.drain()).is_empty()

    def test_push_from_worker_thread_is_visible_to_main_thread_drain(self):
        em = EventManager.get()
        worker = threading.Thread(target=lambda: em.push(ServerConnectedEvent(host="worker", port=1)))
        worker.start()
        worker.join()

        events = em.drain()

        assert_that(events).is_length(1)
        assert isinstance(events[0], ServerConnectedEvent)
        assert_that(events[0].host).is_equal_to("worker")


class TestEmitAndSubscribe:
    def setup_method(self):
        EventManager.reset()

    def test_emit_calls_registered_handler(self):
        em = EventManager.get()
        received: list[ServerConnectedEvent] = []

        def collect(e: ServerConnectedEvent) -> None:
            received.append(e)

        em.subscribe(ServerConnectedEvent, collect)
        em.emit(ServerConnectedEvent(host="h", port=1))

        assert_that(received).is_length(1)
        assert_that(received[0].host).is_equal_to("h")

    def test_emit_stops_propagation_when_handler_returns_true(self):
        em = EventManager.get()
        second_called: list[int] = []
        em.subscribe(ServerConnectedEvent, lambda _e: True)

        def second(_e: ServerConnectedEvent) -> None:
            second_called.append(1)

        em.subscribe(ServerConnectedEvent, second)

        result = em.emit(ServerConnectedEvent(host="h", port=1))

        assert_that(result).is_true()
        assert_that(second_called).is_empty()

    def test_emit_continues_when_handler_returns_none(self):
        em = EventManager.get()
        calls: list[int] = []

        def first(_e: ServerConnectedEvent) -> None:
            calls.append(1)

        def second(_e: ServerConnectedEvent) -> None:
            calls.append(2)

        em.subscribe(ServerConnectedEvent, first)
        em.subscribe(ServerConnectedEvent, second)
        em.emit(ServerConnectedEvent(host="h", port=1))

        assert_that(calls).is_equal_to([1, 2])

    def test_emit_returns_false_with_no_subscribers(self):
        em = EventManager.get()
        result = em.emit(ServerConnectedEvent(host="h", port=1))
        assert_that(result).is_false()

    def test_handlers_are_not_called_for_other_event_types(self):
        em = EventManager.get()
        called: list[int] = []

        def handler(_e: ServerConnectedEvent) -> None:
            called.append(1)

        em.subscribe(ServerConnectedEvent, handler)
        em.emit(ServerDisconnectedEvent(reason="gone"))

        assert_that(called).is_empty()

    def test_unsubscribe_removes_handler(self):
        em = EventManager.get()
        called = []

        def handler(_e: ServerConnectedEvent) -> None:
            called.append(1)

        em.subscribe(ServerConnectedEvent, handler)
        em.unsubscribe(ServerConnectedEvent, handler)

        em.emit(ServerConnectedEvent(host="h", port=1))

        assert_that(called).is_empty()

    def test_unsubscribe_unknown_handler_is_noop(self):
        em = EventManager.get()
        em.unsubscribe(ServerConnectedEvent, lambda _e: None)


class TestDrainAndDispatch:
    def setup_method(self):
        EventManager.reset()

    def test_drain_and_dispatch_delivers_queued_events_to_handlers(self):
        em = EventManager.get()
        received: list[ServerConnectedEvent] = []

        def collect(e: ServerConnectedEvent) -> None:
            received.append(e)

        em.subscribe(ServerConnectedEvent, collect)
        em.push(ServerConnectedEvent(host="a", port=1))
        em.push(ServerConnectedEvent(host="b", port=2))
        em.drain_and_dispatch()

        assert_that(received).is_length(2)
        assert_that(received[0].host).is_equal_to("a")
        assert_that(received[1].host).is_equal_to("b")

    def test_drain_and_dispatch_leaves_queue_empty(self):
        em = EventManager.get()
        em.push(ServerConnectedEvent(host="a", port=1))
        em.drain_and_dispatch()

        assert_that(em.drain()).is_empty()
