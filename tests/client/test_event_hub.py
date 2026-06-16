"""Tests for decker.client.event_hub — thread safety and singleton behavior."""

import threading

from assertpy import assert_that

from decker.client.event_hub import EventHub
from decker.client.events import ServerConnectedEvent


class TestEventHub:
    def setup_method(self):
        EventHub._instance = None  # pylint: disable=protected-access

    def test_get_returns_same_instance(self):
        assert_that(EventHub.get()).is_same_as(EventHub.get())

    def test_drain_returns_pushed_events_in_order(self):
        hub = EventHub.get()
        hub.push(ServerConnectedEvent(host="a", port=1))
        hub.push(ServerConnectedEvent(host="b", port=2))

        events = hub.drain()

        assert_that(events).is_length(2)
        first, second = events
        assert isinstance(first, ServerConnectedEvent) and isinstance(second, ServerConnectedEvent)
        assert_that(first.host).is_equal_to("a")
        assert_that(second.host).is_equal_to("b")

    def test_drain_empties_the_queue(self):
        hub = EventHub.get()
        hub.push(ServerConnectedEvent(host="a", port=1))
        hub.drain()

        assert_that(hub.drain()).is_empty()

    def test_push_from_worker_thread_is_visible_to_main_thread_drain(self):
        hub = EventHub.get()
        worker = threading.Thread(target=lambda: hub.push(ServerConnectedEvent(host="worker", port=1)))
        worker.start()
        worker.join()

        events = hub.drain()

        assert_that(events).is_length(1)
        assert isinstance(events[0], ServerConnectedEvent)
        assert_that(events[0].host).is_equal_to("worker")
