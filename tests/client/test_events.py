"""Tests for decker.client.events."""

from assertpy import assert_that

from decker.client.events import (
    AppRulesUpdatedEvent,
    DetectionStatusEvent,
    DeviceListUpdatedEvent,
    KeyEvent,
    PluginLoadFailedEvent,
    ServerConnectedEvent,
    ServerDisconnectedEvent,
    WindowFocusedEvent,
    WindowPickedEvent,
)
from decker.common.model import (
    DefaultRule,
    DeviceHardwareInfo,
    DeviceRules,
    WindowInfo,
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
        device = DeviceHardwareInfo(id="abc123", type="Stream Deck", vendor_id=0, product_id=0, num_keys=15)
        event = DeviceListUpdatedEvent(devices=[device])
        assert_that(event.devices).is_equal_to([device])

    def test_key_event_holds_device_id_index_and_pressed_state(self):
        event = KeyEvent(device_id="abc123", key_index=2, pressed=True)
        assert_that(event.device_id).is_equal_to("abc123")
        assert_that(event.key_index).is_equal_to(2)
        assert_that(event.pressed).is_true()

    def test_app_rule_and_window_events_hold_their_data(self):
        rules = DeviceRules("d", [], DefaultRule())
        window = WindowInfo(window_class="a")
        assert_that(AppRulesUpdatedEvent(rules=rules).rules).is_equal_to(rules)
        assert_that(WindowFocusedEvent(window=window).window).is_equal_to(window)
        assert_that(WindowPickedEvent(window=None).window).is_none()
        status = DetectionStatusEvent(state="ok", reason="", backend="x11", supports_pick=True, window=window)
        assert_that(status.backend).is_equal_to("x11")
        assert_that(status.window).is_equal_to(window)
