"""Tests for ConnectionManager's screensaver methods and push events, and their routing in MainWindow."""

# pylint: disable=protected-access,redefined-outer-name

import base64
import json
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that

from decker.client.connection_manager import ConnectionManager
from decker.client.context import AppContext
from decker.client.events import ScreensaverSettingsEvent, ScreensaverStateEvent
from decker.client.events.event_manager import EventManager
from decker.client.ui_state_store import UiStateStore
from decker.client.widgets.screensaver_panel import ScreensaverPanel
from decker.client.window import MainWindow
from decker.common.model import DeviceHardwareInfo, ScreensaverSettings

_SETTINGS = ScreensaverSettings(timeout_minutes=5, content="image", image_path="/a.png", bezel=True)


def _get_payload(**extra: object) -> str:
    return json.dumps({"brightness": 80, "timeout_minutes": 7, "active": True, "last_error": "oops", **extra})


@pytest.fixture
def manager() -> Iterator[ConnectionManager]:
    EventManager.reset()
    AppContext.reset()
    AppContext.get().active_device = DeviceHardwareInfo(
        id="dev1", type="Stream Deck", vendor_id=0, product_id=0, num_keys=15
    )
    mgr = ConnectionManager()
    mgr._conn = MagicMock()
    yield mgr
    mgr._conn = None
    AppContext.reset()


class TestScreensaverCalls:
    def test_get_parses_settings_state_and_ignores_unknown_keys(self, manager):
        manager._conn.root.screensaver_get.return_value = _get_payload(future_field=1)

        status = manager.screensaver_get("dev1")

        assert_that(status).is_not_none()
        assert_that(status.device_id).is_equal_to("dev1")
        assert_that(status.settings.brightness).is_equal_to(80)
        assert_that(status.settings.timeout_minutes).is_equal_to(7)
        assert_that(status.active).is_true()
        assert_that(status.last_error).is_equal_to("oops")

    def test_get_null_is_none(self, manager):
        manager._conn.root.screensaver_get.return_value = "null"
        assert_that(manager.screensaver_get("nope")).is_none()

    def test_get_without_connection_does_not_raise(self, manager):
        manager._conn = None
        assert_that(manager.screensaver_get("dev1")).is_none()

    def test_set_sends_settings_json_and_returns_ok(self, manager):
        manager._conn.root.screensaver_set.return_value = json.dumps({"ok": True, "error": ""})

        assert_that(manager.screensaver_set("dev1", _SETTINGS)).is_equal_to((True, ""))

        sent = json.loads(manager._conn.root.screensaver_set.call_args.args[1])
        assert_that(ScreensaverSettings(**sent)).is_equal_to(_SETTINGS)

    def test_set_returns_false_on_refusal(self, manager):
        manager._conn.root.screensaver_set.return_value = json.dumps({"ok": False, "error": "bad value"})
        assert_that(manager.screensaver_set("dev1", _SETTINGS)).is_equal_to((False, "bad value"))

    def test_set_transport_failure_returns_server_unavailable(self, manager):
        manager._conn.root.screensaver_set.side_effect = EOFError("gone")
        assert_that(manager.screensaver_set("dev1", _SETTINGS)).is_equal_to((False, "server unavailable"))

    def test_activate_and_deactivate_return_the_server_result(self, manager):
        manager._conn.root.screensaver_activate.return_value = "true"
        manager._conn.root.screensaver_deactivate.return_value = "false"
        assert_that(manager.screensaver_activate("dev1")).is_true()
        assert_that(manager.screensaver_deactivate("dev1")).is_false()

    def test_activate_transport_failure_is_false(self, manager):
        manager._conn.root.screensaver_activate.side_effect = EOFError("gone")
        assert_that(manager.screensaver_activate("dev1")).is_false()

    def test_preview_success_returns_png_bytes(self, manager):
        png = b"\x89PNG\r\n"
        manager._conn.root.screensaver_preview.return_value = json.dumps({"png": base64.b64encode(png).decode()})
        assert_that(manager.screensaver_preview("dev1", _SETTINGS)).is_equal_to((png, ""))

    def test_preview_error_returns_message(self, manager):
        manager._conn.root.screensaver_preview.return_value = json.dumps({"error": "no image"})
        assert_that(manager.screensaver_preview("dev1", _SETTINGS)).is_equal_to((None, "no image"))

    def test_preview_transport_failure_returns_server_unavailable(self, manager):
        manager._conn.root.screensaver_preview.side_effect = EOFError("gone")
        assert_that(manager.screensaver_preview("dev1", _SETTINGS)).is_equal_to((None, "server unavailable"))


class TestScreensaverPushEvents:
    def test_changed_event_becomes_a_state_event(self, manager):
        manager._on_server_event("screensaver_changed", json.dumps({"device_id": "dev1", "active": True}))

        assert_that(EventManager.get().drain()).is_equal_to([ScreensaverStateEvent("dev1", True)])

    def test_settings_changed_refreshes_through_the_worker_pass(self, manager):
        manager._conn.root.screensaver_get.return_value = _get_payload()

        manager._on_server_event("screensaver_settings_changed", json.dumps({"device_id": "other"}))
        assert_that(EventManager.get().drain()).is_empty()  # deferred to the connection thread
        assert_that(manager._wake_event.is_set()).is_true()

        manager._refresh_requested_screensavers()

        events = [e for e in EventManager.get().drain() if isinstance(e, ScreensaverSettingsEvent)]
        assert_that(events).is_length(1)
        assert_that(events[0].device_id).is_equal_to("other")
        assert_that(events[0].active).is_true()
        manager._conn.root.screensaver_get.assert_called_once_with("other")

    def test_changed_event_also_refetches_last_error(self, manager):
        manager._conn.root.screensaver_get.return_value = _get_payload(last_error="image not found: a.png")

        manager._on_server_event("screensaver_changed", json.dumps({"device_id": "dev1", "active": True}))
        assert_that(EventManager.get().drain()).is_equal_to([ScreensaverStateEvent("dev1", True)])
        manager._refresh_requested_screensavers()

        events = [e for e in EventManager.get().drain() if isinstance(e, ScreensaverSettingsEvent)]
        assert_that([e.last_error for e in events]).is_equal_to(["image not found: a.png"])

    def test_active_device_refresh_pushes_settings(self, manager):
        manager._conn.root.screensaver_get.return_value = _get_payload()
        manager._conn.root.profiles_list.return_value = "null"
        manager._conn.root.pages_list.return_value = "null"
        manager._conn.root.app_rules_list.return_value = "null"
        manager._conn.root.key_get_states.return_value = "[]"

        manager._refresh_active_device()

        pushed = [e for e in EventManager.get().drain() if isinstance(e, ScreensaverSettingsEvent)]
        assert_that(pushed).is_length(1)


class TestScreensaverEventsReachTheSettingsDialog:
    def test_events_are_forwarded_through_the_real_window_routing(
        self, qapp, tmp_path
    ):  # pylint: disable=unused-argument
        AppContext._instance = None
        EventManager.reset()
        win = MainWindow(MagicMock(is_connected=False), ui_state_store=UiStateStore(tmp_path / "config.db"))
        received: list[object] = []
        win._settings_dialog.add_screensaver_listener(received.append)
        settings_event = ScreensaverSettingsEvent("dev1", ScreensaverSettings(), False, "")
        state_event = ScreensaverStateEvent("dev1", True)

        EventManager.get().push(settings_event)
        EventManager.get().push(state_event)
        EventManager.get().drain_and_dispatch()

        assert_that(received).is_equal_to([settings_event, state_event])
        win.close()


class TestScreensaverPanelOverTheConnection:
    def test_activation_error_reaches_the_panel_after_screensaver_changed(self, qapp, manager):
        root = manager._conn.root
        root.screensaver_get.return_value = json.dumps({"active": False, "last_error": ""})
        panel = ScreensaverPanel(device_id=lambda: "dev1", rpc=lambda: manager, host=lambda: "127.0.0.1")
        panel.refresh_device()
        root.screensaver_get.return_value = json.dumps({"active": True, "last_error": "image not found: a.png"})

        manager._on_server_event("screensaver_changed", json.dumps({"device_id": "dev1", "active": True}))
        manager._refresh_requested_screensavers()  # the connection thread's next pass
        for event in EventManager.get().drain():
            if isinstance(event, (ScreensaverSettingsEvent, ScreensaverStateEvent)):
                panel.handle_event(event)

        assert_that(panel._last_error_label.text()).is_equal_to("image not found: a.png")
        panel.deleteLater()
