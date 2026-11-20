import io
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from assertpy import assert_that
from PIL import Image

from decker.plugin.loader import InstalledPlugin
from decker.plugin.manifest import PluginManifest
from decker.plugin.target import ActionTarget
from tests.server.animation_fixture import (
    WriteLog,
    make_gif,
    opened_deck_manager,
    stateful_deck,
    wait_until,
)
from tests.server.test_plugins import _STATIC_ACTION, Env, _page_controller

_PACK_ID = "com.t.bg.icons"
_ACTION = "com.t.static"


def _png(color: str, size: int = 32) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buf, format="PNG")
    return buf.getvalue()


_FILES = {"blue.png": _png("#0000ff"), "bg.gif": make_gif(3), "icon.gif": make_gif(2), "dot.png": _png("#00ff00", 8)}


def _ref(name: str) -> str:
    return f"pack:{_PACK_ID}/{name}"


def _bg(name: str) -> dict[str, Any]:
    return {"background": {"type": "image", "image": {"ref": _ref(name)}}}


def _install(env: Env, root: Path) -> InstalledPlugin:
    (root / "pack").mkdir(parents=True)
    for name, data in _FILES.items():
        (root / "pack" / name).write_bytes(data)
    manifest = PluginManifest.from_dict(
        {
            "format": 1,
            "id": "com.t.bg",
            "name": "BG",
            "version": "1.0.0",
            "author": "a",
            "description": "d",
            "contributes": {"icon_packs": [{"id": _PACK_ID, "name": "BG", "path": "pack"}]},
        }
    )
    plugin = InstalledPlugin(manifest, root)
    env.manager.icon_packs.register(plugin)
    return plugin


def _pixel(png: bytes | None, x: int, y: int) -> tuple[int, ...]:
    assert png is not None
    return Image.open(io.BytesIO(png)).convert("RGB").getpixel((x, y))  # type: ignore[return-value]


@pytest.fixture(name="env")
def env_fixture(tmp_path):
    environment = Env(tmp_path)
    _install(environment, tmp_path / "bg")
    yield environment
    environment.manager.destroy()


@pytest.fixture(name="deck_env")
def deck_env_fixture(tmp_path):
    with opened_deck_manager(tmp_path / "state") as (dm, device_id, log):
        environment = Env(tmp_path, device_manager=dm)
        plugin = _install(environment, tmp_path / "bg")
        try:
            yield environment, device_id, plugin
        finally:
            environment.manager.destroy()


def _target(device_id: str = "dev", key: int = 2) -> ActionTarget:
    return ActionTarget("com.t.static", _STATIC_ACTION, f"ctx-bg-{key}", device_id, key)


def _animation(env: Env, device_id: str, key: int) -> Any:
    state = env.dm.get_device_state(device_id)
    assert state is not None
    return state.get_key_animation(key)


def test_image_background_from_a_library_ref_appears_in_the_composed_png(env):
    target = _target(key=0)
    env.manager.activate_action(target, _bg("blue.png"))

    assert_that(_pixel(env.image(), 5, 5)).is_equal_to((0, 0, 255))
    assert_that(_pixel(env.image(), 138, 138)).is_equal_to((0, 0, 255))


def test_ref_to_uninstalled_pack_falls_back_to_black(env):
    target = _target(key=0)
    env.manager.activate_action(target, _bg("blue.png"))

    env.manager.remove_plugin("com.t.bg")

    assert_that(_pixel(env.image(), 5, 5)).is_equal_to((0, 0, 0))
    assert_that(env.image()).is_not_none()


def test_empty_or_bad_ref_falls_back_to_black_and_other_modes_skip_the_read(env):
    target = _target(key=0)
    env.manager.activate_action(target, {"background": {"type": "image", "image": {"ref": ""}}})
    assert_that(_pixel(env.image(), 5, 5)).is_equal_to((0, 0, 0))

    env.manager.set_appearance(target, {"background": {"type": "image", "image": {"ref": _ref("missing.png")}}})
    assert_that(_pixel(env.image(), 5, 5)).is_equal_to((0, 0, 0))

    env.manager.set_appearance(target, {"background": {"type": "color", "color": "#ff0000", **_bg("blue.png")}})
    assert_that(_pixel(env.image(), 5, 5)).is_equal_to((255, 0, 0))


def test_preview_image_with_draft_background_matches_the_applied_result(env):
    target = _target(key=0)
    env.manager.activate_action(target, {})
    draft = _bg("blue.png")

    preview = env.manager.preview_image(target, draft)
    env.manager.set_appearance(target, draft)

    assert_that(preview).is_equal_to(env.image())
    assert_that(_pixel(preview, 5, 5)).is_equal_to((0, 0, 255))


def test_changed_library_image_is_picked_up_on_the_next_recompose(env, tmp_path):
    target = _target(key=0)
    env.manager.activate_action(target, _bg("blue.png"))
    (tmp_path / "bg" / "pack" / "blue.png").write_bytes(_png("#ff00ff"))

    env.manager.set_appearance(target, _bg("blue.png"))

    assert_that(_pixel(env.image(), 5, 5)).is_equal_to((255, 0, 255))


def test_legacy_string_background_in_stored_appearance_still_renders(env):
    env.manager.activate_action(_target(key=0), {"background": "#ff0000"})

    assert_that(_pixel(env.image(), 5, 5)).is_equal_to((255, 0, 0))


def test_gif_background_with_static_icon_registers_an_animation(deck_env):
    env, device_id, _plugin = deck_env

    env.manager.activate_action(_target(device_id), _bg("bg.gif"))

    spec = _animation(env, device_id, 2)
    assert spec is not None
    assert_that(spec.layer).is_equal_to("background")
    assert_that(spec.gif).is_equal_to(_FILES["bg.gif"])


def test_animated_icon_override_wins_over_gif_background(deck_env):
    env, device_id, _plugin = deck_env
    appearance = {**_bg("bg.gif"), "icon": {"ref": _ref("icon.gif")}}

    env.manager.activate_action(_target(device_id), appearance)

    spec = _animation(env, device_id, 2)
    assert spec is not None
    assert_that(spec.layer).is_not_equal_to("background")
    assert_that(spec.gif).is_equal_to(_FILES["icon.gif"])


def test_animated_background_resumes_when_the_device_reopens(deck_env):
    env, device_id, _plugin = deck_env
    controller = _page_controller(env, _target(device_id), _bg("bg.gif"))
    controller.restore(device_id)
    assert_that(wait_until(lambda: env.dm.playing_animation_id(device_id, 2) is not None)).is_true()
    env.dm.close_device(device_id)
    deck, log = stateful_deck(), WriteLog()
    deck.set_key_image.side_effect = log

    with patch("decker.server.devices.manager._HardwareDeviceManager") as hardware:
        hardware.return_value.enumerate.return_value = [deck]
        controller.restore(device_id)

    assert_that(env.dm.playing_animation_id(device_id, 2)).is_not_none()
    assert_that(_animation(env, device_id, 2).layer).is_equal_to("background")
    assert_that(wait_until(lambda: len({w[1] for w in log.for_key(2)}) >= 2)).is_true()
