import copy
import json
from typing import Any

import pytest
from assertpy import assert_that

from decker.plugin.manifest import (
    SUPPORTED_FORMAT,
    ManifestValidationError,
    PluginManifest,
)

_COUNTER: dict[str, Any] = {
    "format": 1,
    "id": "com.decker.counter",
    "name": "Counter",
    "version": "1.0.0",
    "author": "Decker",
    "description": "Counts key presses.",
    "homepage": "https://github.com/valsr/Decker",
    "icon": "icons/plugin",
    "category": "Utilities",
    "decker": ">=0.2",
    "runtime": {"type": "python", "entry": "plugin.py", "python": ">=3.12", "requirements": []},
    "permissions": [],
    "global_settings": [],
    "contributes": {
        "icon_packs": [{"id": "com.decker.counter.icons", "name": "Counter icons", "path": "iconpack"}],
        "actions": [
            {
                "id": "com.decker.counter.counter",
                "name": "Counter",
                "tooltip": "Press to count, long press to reset",
                "icon": "icons/counter",
                "gestures": ["press", "long_press"],
                "states": [{"image": "icons/counter"}],
                "settings": [
                    {"section": "Counting"},
                    {"key": "step", "type": "int", "label": "Step", "default": 1, "min": 1, "max": 9999},
                    {
                        "key": "double_step",
                        "type": "int",
                        "label": "Double press step",
                        "optional": True,
                        "placeholder": "None (presses register immediately)",
                    },
                    {
                        "key": "max",
                        "type": "int",
                        "label": "Max count",
                        "default": 0,
                        "min": 0,
                        "special_value": "∞ (no limit)",
                    },
                ],
            }
        ],
    },
}


def _counter(**overrides: Any) -> dict[str, Any]:
    data = copy.deepcopy(_COUNTER)
    data.update(overrides)
    return data


def _with_action(**action: Any) -> dict[str, Any]:
    data = _counter()
    data["contributes"]["actions"][0].update(action)
    return data


def test_counter_manifest_parses() -> None:
    manifest = PluginManifest.from_dict(_counter())
    assert_that(manifest.format).is_equal_to(SUPPORTED_FORMAT)
    assert_that(manifest.actions[0].id).is_equal_to("com.decker.counter.counter")
    assert_that(manifest.actions[0].gestures).is_equal_to({"press", "long_press"})
    assert_that(manifest.actions[0].settings).is_length(4)
    assert_that(manifest.runtime).is_not_none()
    assert manifest.runtime is not None
    assert_that(manifest.runtime.type).is_equal_to("python")
    assert_that(manifest.runtime.entry).is_equal_to("plugin.py")
    assert_that(manifest.icon_packs[0].path).is_equal_to("iconpack")


def test_unknown_format_rejected() -> None:
    with pytest.raises(ManifestValidationError, match="format 2"):
        PluginManifest.from_dict(_counter(format=2))


def test_missing_format_rejected() -> None:
    data = _counter()
    del data["format"]
    with pytest.raises(ManifestValidationError, match="format"):
        PluginManifest.from_dict(data)


def test_unknown_top_level_keys_ignored() -> None:
    manifest = PluginManifest.from_dict(_counter(signature="x", future={"a": 1}))
    assert_that(manifest.id).is_equal_to("com.decker.counter")


@pytest.mark.parametrize("contributes", [{}, [], None])
def test_contributes_required_and_non_empty(contributes: Any) -> None:
    with pytest.raises(ManifestValidationError, match="contributes"):
        PluginManifest.from_dict(_counter(contributes=contributes))


def test_unknown_contribution_kind_rejected() -> None:
    with pytest.raises(ManifestValidationError, match="requires a newer version of Decker"):
        PluginManifest.from_dict(_counter(contributes={"screensavers": []}))


def test_actions_require_runtime() -> None:
    data = _counter()
    del data["runtime"]
    with pytest.raises(ManifestValidationError, match="runtime"):
        PluginManifest.from_dict(data)


def test_icon_pack_only_needs_no_runtime() -> None:
    data = _counter()
    del data["runtime"]
    del data["contributes"]["actions"]
    manifest = PluginManifest.from_dict(data)
    assert_that(manifest.runtime).is_none()
    assert_that(manifest.actions).is_empty()


def test_contribution_id_must_be_prefixed_by_plugin_id() -> None:
    with pytest.raises(ManifestValidationError, match="com.decker.counter."):
        PluginManifest.from_dict(_with_action(id="com.other.x"))
    data = _counter()
    data["contributes"]["icon_packs"][0]["id"] = "com.other.icons"
    with pytest.raises(ManifestValidationError, match="icon pack id"):
        PluginManifest.from_dict(data)


def test_invalid_gesture_rejected() -> None:
    with pytest.raises(ManifestValidationError, match="gestures"):
        PluginManifest.from_dict(_with_action(gestures=["swipe"]))


@pytest.mark.parametrize("req", ["foo @ https://x/y.whl", "git+https://x"])
def test_url_requirement_rejected(req: str) -> None:
    data = _counter()
    data["runtime"]["requirements"] = [req]
    with pytest.raises(ManifestValidationError):
        PluginManifest.from_dict(data)


def test_index_requirement_accepted() -> None:
    data = _counter()
    data["runtime"]["requirements"] = ["requests>=2"]
    manifest = PluginManifest.from_dict(data)
    assert manifest.runtime is not None
    assert_that(manifest.runtime.requirements).is_equal_to(("requests>=2",))


def test_runtime_type_must_be_python_or_executable() -> None:
    data = _counter()
    data["runtime"]["type"] = "java"
    with pytest.raises(ManifestValidationError, match="runtime type"):
        PluginManifest.from_dict(data)


def test_action_gestures_default_to_press() -> None:
    data = _counter()
    del data["contributes"]["actions"][0]["gestures"]
    assert_that(PluginManifest.from_dict(data).actions[0].gestures).is_equal_to({"press"})


def test_invalid_settings_schema_becomes_manifest_error() -> None:
    with pytest.raises(ManifestValidationError, match="settings"):
        PluginManifest.from_dict(_with_action(settings="nope"))
    with pytest.raises(ManifestValidationError, match="global_settings"):
        PluginManifest.from_dict(_counter(global_settings="nope"))


def test_load_valid_file(tmp_path: Any) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_counter()), encoding="utf-8")
    assert_that(PluginManifest.load(path).name).is_equal_to("Counter")


def test_malformed_json_and_non_object_rejected(tmp_path: Any) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ManifestValidationError, match="malformed"):
        PluginManifest.load(bad)
    arr = tmp_path / "arr.json"
    arr.write_text("[]", encoding="utf-8")
    with pytest.raises(ManifestValidationError, match="JSON object"):
        PluginManifest.load(arr)
    with pytest.raises(ManifestValidationError, match="could not read"):
        PluginManifest.load(tmp_path / "missing.json")
