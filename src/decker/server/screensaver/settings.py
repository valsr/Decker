"""Validation and JSON (de)serialisation of ScreensaverSettings."""

import json
from dataclasses import asdict, fields
from typing import Any

from decker.common.model import ScreensaverSettings

_INT_RANGES: dict[str, tuple[int, int]] = {
    "brightness": (1, 100),
    "timeout_minutes": (0, 1440),
    "saver_brightness": (0, 100),
    "gallery_minutes": (1, 1440),
}
_FLOAT_RANGES: dict[str, tuple[float, float]] = {"key_mm": (5, 60), "gap_mm": (0, 30)}
_CHOICES: dict[str, tuple[str, ...]] = {
    "content": ("none", "image", "gallery"),
    "scaling": ("center", "stretch"),
    "gallery_mode": ("activation", "interval"),
}
_PATHS = ("image_path", "folder_path")
_MAX_PATH = 1024


def _check_int(name: str, value: Any) -> None:
    low, high = _INT_RANGES[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")


def _check_float(name: str, value: Any) -> None:
    low, high = _FLOAT_RANGES[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")


def _check_field(name: str, value: Any) -> None:
    if name in _INT_RANGES:
        _check_int(name, value)
    elif name in _FLOAT_RANGES:
        _check_float(name, value)
    elif name in _CHOICES:
        if value not in _CHOICES[name]:
            allowed = ", ".join(_CHOICES[name])
            raise ValueError(f"{name} must be one of {allowed}")
    elif name in _PATHS:
        if not isinstance(value, str) or len(value) > _MAX_PATH:
            raise ValueError(f"{name} must be a string of at most {_MAX_PATH} characters")
    elif not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")


def validate(settings: ScreensaverSettings) -> ScreensaverSettings:
    """Return the settings if every field is valid, else raise ValueError naming the field."""
    for name, value in asdict(settings).items():
        _check_field(name, value)
    return settings


def settings_from_json(text: str) -> ScreensaverSettings:
    """Parse and validate settings JSON; unknown keys, wrong types and out-of-range values raise ValueError."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"settings are not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("settings must be a JSON object")
    known = {f.name for f in fields(ScreensaverSettings)}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ValueError("unknown field: " + ", ".join(unknown))
    return validate(ScreensaverSettings(**data))


def settings_to_json(settings: ScreensaverSettings) -> str:
    """Serialise settings to JSON."""
    return json.dumps(asdict(settings))
