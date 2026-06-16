"""Tests for decker.client.events."""

from assertpy import assert_that

from decker.client.events import (
    DeviceListUpdatedEvent,
    KeyEvent,
    ServerConnectedEvent,
    ServerDisconnectedEvent,
)


class TestEvents:
    def test_server_connected_event_holds_host_and_port(self):
        event = ServerConnectedEvent(host="localhost", port=18861)
        assert_that(event.host).is_equal_to("localhost")
        assert_that(event.port).is_equal_to(18861)

    def test_server_disconnected_event_holds_reason(self):
        event = ServerDisconnectedEvent(reason="timeout")
        assert_that(event.reason).is_equal_to("timeout")

    def test_device_list_updated_event_holds_devices(self):
        devices = [{"id": "abc123"}]
        event = DeviceListUpdatedEvent(devices=devices)
        assert_that(event.devices).is_equal_to(devices)

    def test_key_event_holds_device_id_index_and_pressed_state(self):
        event = KeyEvent(device_id="abc123", key_index=2, pressed=True)
        assert_that(event.device_id).is_equal_to("abc123")
        assert_that(event.key_index).is_equal_to(2)
        assert_that(event.pressed).is_true()
