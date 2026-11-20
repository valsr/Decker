"""Tests for decker.client.widgets.screensaver_panel."""

from typing import Any

import pytest
from assertpy import assert_that
from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QColor, QImage

from decker.client.events import ScreensaverSettingsEvent, ScreensaverStateEvent
from decker.client.widgets.screensaver_panel import ScreensaverPanel, is_loopback_host
from decker.common.model import ScreensaverSettings

# pylint: disable=protected-access,redefined-outer-name

DEVICE = "abcd1234"


def _png() -> bytes:
    image = QImage(4, 4, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return buffer.data().data()


class FakeRpc:
    def __init__(self) -> None:
        self.initial: ScreensaverSettingsEvent | None = ScreensaverSettingsEvent(
            DEVICE, ScreensaverSettings(), False, ""
        )
        self.set_calls: list[ScreensaverSettings] = []
        self.set_result: tuple[bool, str] = (True, "")
        self.preview_result: tuple[bytes | None, str] = (None, "no preview")
        self.calls: list[str] = []
        self.preview_calls = 0
        self.activate_result = True

    def screensaver_get(self, device_id: str) -> ScreensaverSettingsEvent | None:
        return self.initial

    def screensaver_set(self, device_id: str, settings: ScreensaverSettings) -> tuple[bool, str]:
        self.set_calls.append(settings)
        self.calls.append("set")
        return self.set_result

    def screensaver_activate(self, device_id: str) -> bool:
        self.calls.append("activate")
        return self.activate_result

    def screensaver_deactivate(self, device_id: str) -> bool:
        self.calls.append("deactivate")
        return True

    def screensaver_preview(self, device_id: str, settings: ScreensaverSettings) -> tuple[bytes | None, str]:
        self.preview_calls += 1
        return self.preview_result


@pytest.fixture
def rpc() -> FakeRpc:
    return FakeRpc()


def _make(qapp, rpc: FakeRpc, host: str = "127.0.0.1", device: str | None = DEVICE) -> ScreensaverPanel:
    panel = ScreensaverPanel(device_id=lambda: device, rpc=lambda: rpc, host=lambda: host)
    panel.refresh_device()
    return panel


def _event(settings: Any, active: bool = False, last_error: str = "") -> ScreensaverSettingsEvent:
    return ScreensaverSettingsEvent(DEVICE, settings, active, last_error)


def test_controls_reflect_settings_event(qapp, rpc):
    panel = _make(qapp, rpc)
    settings = ScreensaverSettings(
        brightness=60,
        timeout_minutes=15,
        saver_brightness=5,
        content="gallery",
        image_path="/a.png",
        folder_path="/pics",
        scaling="stretch",
        bezel=True,
        key_mm=20.0,
        gap_mm=6.0,
        gallery_mode="interval",
        gallery_minutes=9,
    )

    panel.handle_event(_event(settings))

    assert_that(panel.current_settings()).is_equal_to(settings)
    assert_that(panel._fields["brightness"].value()).is_equal_to(60)
    assert_that(panel._fields["content"].currentData()).is_equal_to("gallery")
    assert_that(panel._fields["folder_path"].text()).is_equal_to("/pics")
    assert_that(panel._apply_timer.isActive()).is_false()


def test_edit_calls_set_with_full_settings(qapp, rpc):
    panel = _make(qapp, rpc)
    panel.handle_event(_event(ScreensaverSettings(timeout_minutes=3, content="image", image_path="/x.png")))

    panel._fields["brightness"].setValue(42)
    assert_that(panel._apply_timer.isActive()).is_true()
    assert_that(rpc.set_calls).is_empty()
    panel.flush()

    assert_that(rpc.set_calls).is_length(1)
    assert_that(rpc.set_calls[0]).is_equal_to(
        ScreensaverSettings(brightness=42, timeout_minutes=3, content="image", image_path="/x.png")
    )
    assert_that(panel._apply_timer.isActive()).is_false()


def test_pickers_disabled_for_remote(qapp, rpc):
    panel = _make(qapp, rpc, host="192.168.1.5")

    assert_that(panel._fields["image_path"].isEnabled()).is_false()
    assert_that(panel._fields["folder_path"].isEnabled()).is_false()
    assert_that(panel._image_browse.isEnabled()).is_false()
    assert_that(panel._folder_browse.isEnabled()).is_false()
    assert_that(panel._hint_label.text()).contains("runs on the server's machine")
    local = _make(qapp, rpc)
    assert_that(local._image_browse.isEnabled()).is_true()
    assert_that(local._hint_label.text()).is_empty()


def test_activate_button_calls_rpc_and_toggles_label(qapp, rpc):
    panel = _make(qapp, rpc)
    assert_that(panel._activate_btn.text()).is_equal_to("Activate now")

    panel._activate_btn.click()
    assert_that(panel._activate_btn.text()).is_equal_to("Wake")
    panel._activate_btn.click()

    assert_that(rpc.calls).is_equal_to(["activate", "deactivate"])
    assert_that(panel._activate_btn.text()).is_equal_to("Activate now")
    panel.handle_event(ScreensaverStateEvent(DEVICE, True))
    assert_that(panel._activate_btn.text()).is_equal_to("Wake")


def test_last_error_shown(qapp, rpc):
    panel = _make(qapp, rpc)

    panel.handle_event(_event(ScreensaverSettings(), last_error="Image missing"))

    assert_that(panel._last_error_label.text()).is_equal_to("Image missing")
    assert_that(panel._last_error_label.isHidden()).is_false()


def test_set_error_message_shown_and_controls_kept(qapp, rpc):
    panel = _make(qapp, rpc)
    rpc.set_result = (False, "image_path too long")

    panel._fields["timeout_minutes"].setValue(77)
    panel.flush()

    assert_that(panel._set_error_label.text()).is_equal_to("image_path too long")
    assert_that(panel._fields["timeout_minutes"].value()).is_equal_to(77)
    rpc.set_result = (True, "")
    panel.flush()
    assert_that(panel._set_error_label.text()).is_empty()


def test_bezel_fields_disabled_when_bezel_off(qapp, rpc):
    panel = _make(qapp, rpc)
    assert_that(panel._fields["key_mm"].isEnabled()).is_false()
    assert_that(panel._fields["gap_mm"].isEnabled()).is_false()
    assert_that(panel._fields["gallery_minutes"].isEnabled()).is_false()

    panel._fields["bezel"].setChecked(True)
    panel._fields["gallery_mode"].setCurrentIndex(1)

    assert_that(panel._fields["key_mm"].isEnabled()).is_true()
    assert_that(panel._fields["gap_mm"].isEnabled()).is_true()
    assert_that(panel._fields["gallery_minutes"].isEnabled()).is_true()


def test_focused_control_not_overwritten_by_event(qapp, rpc):
    panel = _make(qapp, rpc)
    panel._fields["brightness"].setValue(30)  # pending, unsent
    panel._fields["saver_brightness"].setValue(7)
    panel.flush()
    panel._fields["timeout_minutes"].setValue(12)  # pending again

    panel.handle_event(_event(ScreensaverSettings(brightness=90, timeout_minutes=99, saver_brightness=50)))

    assert_that(panel._fields["timeout_minutes"].value()).is_equal_to(12)
    assert_that(panel._fields["brightness"].value()).is_equal_to(90)
    assert_that(panel._fields["saver_brightness"].value()).is_equal_to(50)


def test_truly_focused_widget_is_skipped(qapp, rpc, monkeypatch):
    panel = _make(qapp, rpc)
    focused = panel._fields["gap_mm"]
    monkeypatch.setattr(type(focused), "hasFocus", lambda self: self is focused)

    panel.handle_event(_event(ScreensaverSettings(gap_mm=9.0, key_mm=30.0)))

    assert_that(focused.value()).is_equal_to(ScreensaverSettings().gap_mm)
    assert_that(panel._fields["key_mm"].value()).is_equal_to(30.0)


def test_disabled_without_device(qapp, rpc):
    panel = _make(qapp, rpc, device=None)

    assert_that(panel._form_host.isEnabled()).is_false()
    assert_that(panel._activate_btn.isEnabled()).is_false()
    assert_that(panel._hint_label.text()).contains("Connect a device")
    panel.handle_event(_event(ScreensaverSettings()))
    panel.flush()
    assert_that(rpc.set_calls).is_empty()


def test_loopback_detection():
    assert_that(is_loopback_host("localhost")).is_true()
    assert_that(is_loopback_host("127.0.0.1")).is_true()
    assert_that(is_loopback_host("127.5.4.3")).is_true()
    assert_that(is_loopback_host("::1")).is_true()
    assert_that(is_loopback_host("192.168.1.5")).is_false()
    assert_that(is_loopback_host("")).is_false()
    assert_that(is_loopback_host("no-such-host.invalid")).is_false()


def test_unexpected_event_types_do_not_raise(qapp, rpc):
    panel = _make(qapp, rpc)

    class Weird:  # pylint: disable=too-few-public-methods
        brightness: Any = "bright"
        timeout_minutes: Any = None
        saver_brightness: Any = 1e99
        content: Any = 5
        image_path: Any = 12
        folder_path: Any = None
        scaling: Any = "weird"
        bezel: Any = "yes"
        key_mm: Any = float("nan")
        gap_mm: Any = [1]
        gallery_mode: Any = {}
        gallery_minutes: Any = -4

    panel.handle_event(_event(Weird(), active="truthy", last_error=None))  # type: ignore[arg-type]
    settings = panel.current_settings()
    panel.handle_event(_event(object()))
    panel.handle_event(ScreensaverStateEvent("other-device", True))

    assert_that(settings.brightness).is_equal_to(ScreensaverSettings().brightness)
    assert_that(settings.saver_brightness).is_equal_to(100)
    assert_that(settings.content).is_equal_to("none")
    assert_that(settings.gallery_minutes).is_equal_to(1)


def test_preview_shows_image_or_error(qapp, rpc):
    panel = _make(qapp, rpc)
    panel.refresh_preview()
    assert_that(panel._preview.text()).is_equal_to("no preview")

    rpc.preview_result = (_png(), "")
    panel.refresh_preview()

    assert_that(panel._preview.pixmap().isNull()).is_false()


def test_failed_fetch_keeps_panel_disabled_then_retries(qapp, rpc):
    rpc.initial = None
    panel = ScreensaverPanel(device_id=lambda: DEVICE, rpc=lambda: rpc, host=lambda: "127.0.0.1")
    panel.refresh_device()

    assert_that(panel._form_host.isEnabled()).is_false()
    assert_that(panel._hint_label.text()).contains("Could not load")
    panel._fields["brightness"].setValue(5)
    panel.flush()
    assert_that(rpc.set_calls).is_empty()

    rpc.initial = _event(ScreensaverSettings(brightness=77))
    panel.refresh_device()

    assert_that(panel._form_host.isEnabled()).is_true()
    assert_that(panel._fields["brightness"].value()).is_equal_to(77)
    assert_that(panel._hint_label.text()).is_empty()


def test_loopback_result_cached_per_host(qapp, rpc, monkeypatch):
    lookups: list[str] = []
    from decker.client.widgets import screensaver_panel as module  # pylint: disable=import-outside-toplevel

    def fake(host: str) -> bool:
        lookups.append(host)
        return True

    monkeypatch.setattr(module, "is_loopback_host", fake)
    panel = _make(qapp, rpc, host="server.example")
    for value in range(5):
        panel._fields["brightness"].setValue(10 + value)

    assert_that(lookups).is_equal_to(["server.example"])


def test_preview_only_when_visible_and_not_on_own_echo(qapp, rpc):
    panel = _make(qapp, rpc)
    panel.handle_event(_event(ScreensaverSettings(brightness=20)))
    assert_that(panel._preview_timer.isActive()).is_false()

    panel.show()
    assert_that(panel._preview_timer.isActive()).is_true()
    panel.refresh_preview()
    assert_that(rpc.preview_calls).is_equal_to(1)

    panel._fields["brightness"].setValue(30)
    panel.flush()
    panel._preview_timer.stop()
    panel.handle_event(_event(ScreensaverSettings(brightness=30)))
    assert_that(panel._preview_timer.isActive()).is_false()

    panel.handle_event(_event(ScreensaverSettings(brightness=55)))
    assert_that(panel._preview_timer.isActive()).is_true()
    panel.hide()


def test_activate_flushes_pending_edit_first(qapp, rpc):
    panel = _make(qapp, rpc)
    panel._fields["brightness"].setValue(33)

    panel._activate_btn.click()

    assert_that(rpc.calls).is_equal_to(["set", "activate"])
    assert_that(rpc.set_calls[0].brightness).is_equal_to(33)

    other = _make(qapp, rpc)
    rpc.calls.clear()
    rpc.set_result = (False, "bad value")
    other._fields["brightness"].setValue(34)
    other._activate_btn.click()
    assert_that(rpc.calls).is_equal_to(["set"])
    assert_that(other._set_error_label.text()).is_equal_to("bad value")


def test_refused_activate_shows_message(qapp, rpc):
    panel = _make(qapp, rpc)
    rpc.activate_result = False

    panel._activate_btn.click()

    assert_that(panel._set_error_label.text()).contains("could not activate")
    assert_that(panel._activate_btn.text()).is_equal_to("Activate now")
