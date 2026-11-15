"""Plugin manifest parsing and validation."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_UUID_PATTERN = re.compile(r"^[a-z0-9]+(\.[a-z0-9-]+)+$")
_REQUIRED_FIELDS = ("UUID", "Name", "Version", "Author", "Actions")


class ManifestValidationError(ValueError):
    """A manifest.json failed schema or naming-convention validation."""


@dataclass(frozen=True)
class PluginAction:
    """A single action declared in a plugin manifest."""

    uuid: str
    name: str
    icon: str | None = None  # image path relative to the plugin directory, extension optional (Elgato style)


@dataclass(frozen=True)
class PluginManifest:
    """Validated contents of a plugin's manifest.json."""

    uuid: str
    name: str
    version: str
    author: str
    actions: tuple[PluginAction, ...]
    code_path: str | None = None  # entry point script relative to the plugin directory; Elgato plugins only

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PluginManifest":
        """Validate and construct a PluginManifest from parsed JSON. Raises ManifestValidationError."""
        missing = [field for field in _REQUIRED_FIELDS if field not in data]
        if missing:
            missing_str = ", ".join(missing)
            raise ManifestValidationError(f"manifest.json missing required field(s): {missing_str}")

        uuid = data["UUID"]
        if not isinstance(uuid, str) or not _UUID_PATTERN.match(uuid):
            raise ManifestValidationError(f"manifest UUID {uuid!r} is not a valid reverse-domain identifier")

        actions_data = data["Actions"]
        if not isinstance(actions_data, list) or not actions_data:
            raise ManifestValidationError("manifest Actions must be a non-empty list")

        plugin_icon = _optional_str(data.get("Icon"))
        actions = tuple(cls._parse_action(entry, plugin_icon) for entry in actions_data)

        code_path = data.get("CodePath")
        return cls(
            uuid=uuid,
            name=str(data["Name"]),
            version=str(data["Version"]),
            author=str(data["Author"]),
            actions=actions,
            code_path=str(code_path) if code_path is not None else None,
        )

    @staticmethod
    def _parse_action(entry: Any, default_icon: str | None = None) -> PluginAction:
        if not isinstance(entry, dict) or "UUID" not in entry or "Name" not in entry:
            raise ManifestValidationError(f"invalid action entry: {entry!r}")
        action_uuid = entry["UUID"]
        if not isinstance(action_uuid, str) or not _UUID_PATTERN.match(action_uuid):
            raise ManifestValidationError(f"action UUID {action_uuid!r} is not a valid reverse-domain identifier")
        return PluginAction(
            uuid=action_uuid, name=str(entry["Name"]), icon=_optional_str(entry.get("Icon")) or default_icon
        )

    @classmethod
    def load(cls, manifest_path: str | Path) -> "PluginManifest":
        """Read and validate manifest.json at the given path. Raises ManifestValidationError."""
        path = Path(manifest_path)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ManifestValidationError(f"could not read {path}: {exc}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ManifestValidationError(f"malformed JSON in {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ManifestValidationError(f"{path} must contain a JSON object")
        return cls.from_dict(data)


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
