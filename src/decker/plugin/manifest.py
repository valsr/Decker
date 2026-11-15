"""Plugin manifest (format v1) parsing and validation."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from packaging.requirements import InvalidRequirement, Requirement

from decker.plugin.settings_schema import SettingEntry, parse_settings_schema

SUPPORTED_FORMAT = 1
KNOWN_CONTRIBUTION_KINDS = frozenset({"actions", "icon_packs"})
VALID_GESTURES = frozenset({"press", "double_press", "long_press"})
_RUNTIME_TYPES = ("python", "executable")
_UUID_PATTERN = re.compile(r"^[a-z0-9]+(\.[a-z0-9-]+)+$")


class ManifestValidationError(ValueError):
    """A manifest.json failed schema or naming-convention validation."""


@dataclass(frozen=True)
class RuntimeSpec:
    """How a plugin's code is run."""

    type: Literal["python", "executable"]
    entry: str
    python: str | None = None
    requirements: tuple[str, ...] = ()


@dataclass(frozen=True)
class StateSpec:
    """A visual state of an action."""

    image: str | None = None
    title: str | None = None


@dataclass(frozen=True)
class ActionSpec:
    """A key action contributed by a plugin."""

    id: str
    name: str
    tooltip: str = ""
    icon: str | None = None
    gestures: frozenset[str] = frozenset({"press"})
    states: tuple[StateSpec, ...] = ()
    settings: tuple[SettingEntry, ...] = ()
    appearance: dict[str, Any] = field(default_factory=dict, hash=False)


@dataclass(frozen=True)
class IconPackSpec:
    """An icon pack contributed by a plugin."""

    id: str
    name: str
    path: str
    description: str = ""


@dataclass(frozen=True)
class PluginManifest:
    """Validated contents of a plugin's manifest.json."""

    format: int
    id: str
    name: str
    version: str
    author: str
    description: str
    homepage: str | None
    icon: str | None
    category: str | None
    decker: str | None
    runtime: RuntimeSpec | None
    permissions: tuple[str, ...]
    global_settings: tuple[SettingEntry, ...]
    actions: tuple[ActionSpec, ...]
    icon_packs: tuple[IconPackSpec, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PluginManifest":
        """Validate and construct a PluginManifest from parsed JSON. Raises ManifestValidationError."""
        fmt = data.get("format")
        if fmt is None:
            raise ManifestValidationError("manifest missing required field: format")
        if isinstance(fmt, bool) or fmt != SUPPORTED_FORMAT:
            raise ManifestValidationError(f"unsupported manifest format {fmt!r} (supported: {SUPPORTED_FORMAT})")
        plugin_id = _parse_id(data.get("id"), "manifest id")
        missing = [key for key in ("name", "version", "author") if not _is_nonempty_str(data.get(key))]
        if missing:
            raise ManifestValidationError(f"manifest missing required field(s): {', '.join(missing)}")

        contributes = data.get("contributes")
        if not isinstance(contributes, dict) or not contributes:
            raise ManifestValidationError("manifest contributes must be a non-empty object")
        unknown = sorted(set(contributes) - KNOWN_CONTRIBUTION_KINDS)
        if unknown:
            raise ManifestValidationError(
                f"manifest contributes unknown kind(s) {', '.join(unknown)}: requires a newer version of Decker"
            )

        runtime = _parse_runtime(data.get("runtime")) if data.get("runtime") is not None else None
        actions = tuple(_parse_action(e, plugin_id) for e in _as_list(contributes.get("actions", []), "actions"))
        packs = tuple(_parse_icon_pack(e, plugin_id) for e in _as_list(contributes.get("icon_packs", []), "icon_packs"))
        if actions and runtime is None:
            raise ManifestValidationError("manifest contributes actions but declares no runtime")
        if not actions and not packs:
            raise ManifestValidationError("manifest contributes no actions or icon packs")

        return cls(
            format=SUPPORTED_FORMAT,
            id=plugin_id,
            name=str(data["name"]),
            version=str(data["version"]),
            author=str(data["author"]),
            description=str(data.get("description") or ""),
            homepage=_optional_str(data.get("homepage")),
            icon=_optional_str(data.get("icon")),
            category=_optional_str(data.get("category")),
            decker=_optional_str(data.get("decker")),
            runtime=runtime,
            permissions=tuple(str(p) for p in _as_list(data.get("permissions", []), "permissions")),
            global_settings=_parse_settings(data.get("global_settings", []), "global_settings"),
            actions=actions,
            icon_packs=packs,
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


def _parse_id(value: Any, what: str) -> str:
    if not isinstance(value, str) or not _UUID_PATTERN.match(value):
        raise ManifestValidationError(f"{what} {value!r} is not a valid reverse-domain identifier")
    return value


def _parse_contribution_id(value: Any, plugin_id: str, what: str) -> str:
    cid = _parse_id(value, what)
    if not cid.startswith(plugin_id + "."):
        raise ManifestValidationError(f"{what} {cid!r} must start with the plugin id {plugin_id + '.'!r}")
    return cid


def _as_list(value: Any, what: str) -> list[Any]:
    if not isinstance(value, list):
        raise ManifestValidationError(f"manifest {what} must be a list")
    return value


def _parse_settings(value: Any, where: str) -> tuple[SettingEntry, ...]:
    try:
        return parse_settings_schema(value, where)
    except ValueError as exc:
        raise ManifestValidationError(str(exc)) from exc


def _parse_runtime(data: Any) -> RuntimeSpec:
    if not isinstance(data, dict):
        raise ManifestValidationError("manifest runtime must be an object")
    rtype = data.get("type")
    if rtype not in _RUNTIME_TYPES:
        raise ManifestValidationError(f"runtime type {rtype!r} must be one of {', '.join(_RUNTIME_TYPES)}")
    entry = data.get("entry")
    if not isinstance(entry, str) or not entry.strip():
        raise ManifestValidationError("runtime entry must be a non-empty string")
    requirements = tuple(
        _validate_requirement(r) for r in _as_list(data.get("requirements", []), "runtime requirements")
    )
    return RuntimeSpec(type=rtype, entry=entry, python=_optional_str(data.get("python")), requirements=requirements)


def _validate_requirement(req: Any) -> str:
    if not isinstance(req, str):
        raise ManifestValidationError(f"requirement {req!r} must be a string")
    try:
        parsed = Requirement(req)
    except InvalidRequirement as exc:
        raise ManifestValidationError(f"invalid requirement {req!r}: {exc}") from exc
    if parsed.url:
        raise ManifestValidationError(f"requirement {req!r} must be a package-index requirement, not a URL")
    return req


def _parse_action(entry: Any, plugin_id: str) -> ActionSpec:
    if not isinstance(entry, dict) or "id" not in entry or "name" not in entry:
        raise ManifestValidationError(f"invalid action entry: {entry!r}")
    action_id = _parse_contribution_id(entry["id"], plugin_id, "action id")
    gestures = entry.get("gestures", ["press"])
    if not isinstance(gestures, list) or not gestures or not set(gestures) <= VALID_GESTURES:
        raise ManifestValidationError(
            f"action {action_id} gestures must be a non-empty subset of {sorted(VALID_GESTURES)}"
        )
    appearance = entry.get("appearance", {})
    if not isinstance(appearance, dict):
        raise ManifestValidationError(f"action {action_id} appearance must be an object")
    states = tuple(_parse_state(s, action_id) for s in _as_list(entry.get("states", []), "states"))
    return ActionSpec(
        id=action_id,
        name=str(entry["name"]),
        tooltip=str(entry.get("tooltip") or ""),
        icon=_optional_str(entry.get("icon")),
        gestures=frozenset(gestures),
        states=states,
        settings=_parse_settings(entry.get("settings", []), f"action {action_id} settings"),
        appearance=dict(appearance),
    )


def _parse_state(entry: Any, action_id: str) -> StateSpec:
    if not isinstance(entry, dict):
        raise ManifestValidationError(f"action {action_id} state must be an object")
    return StateSpec(image=_optional_str(entry.get("image")), title=_optional_str(entry.get("title")))


def _parse_icon_pack(entry: Any, plugin_id: str) -> IconPackSpec:
    if not isinstance(entry, dict) or not all(_is_nonempty_str(entry.get(k)) for k in ("id", "name", "path")):
        raise ManifestValidationError(f"invalid icon pack entry: {entry!r}")
    return IconPackSpec(
        id=_parse_contribution_id(entry["id"], plugin_id, "icon pack id"),
        name=entry["name"],
        path=entry["path"],
        description=str(entry.get("description") or ""),
    )


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _optional_str(value: Any) -> str | None:
    return value if _is_nonempty_str(value) else None
