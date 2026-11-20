"""Page variables for key templates and the delivery form of settings (expanded text, resolved pages)."""

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from decker.common.icon_ref import DECKER_ICON_REF
from decker.common.model import PageInfo, ProfileInfo
from decker.common.template import expand_template
from decker.plugin.settings_schema import SettingEntry, SettingField

_MISSING = object()
EMPTY_PAGE: dict[str, Any] = {"page_id": "", "name": "", "index": 0, "profile_id": -1}
EMPTY_PROFILE: dict[str, Any] = {"profile_id": -1, "name": "", "index": 0, "icon": ""}
_PROFILE_ID = re.compile(r"[0-9]+\Z")


@dataclass(frozen=True)
class DeviceLayout:
    """A device's profiles and pages as seen by plugins: `pages` are the active profile's, in order."""

    pages: Sequence[PageInfo] = ()
    active_page_id: str = ""
    profiles: Sequence[ProfileInfo] = ()
    active_profile_id: int = 0
    pages_by_profile: Mapping[int, Sequence[PageInfo]] = field(default_factory=lambda: MappingProxyType({}))


def page_variables(layout: DeviceLayout) -> dict[str, str]:
    """Variables for what a device shows; each group is left out when its subject is not in the layout."""
    variables: dict[str, str] = {}
    for position, page in enumerate(layout.pages, start=1):
        if page.page_id == layout.active_page_id:
            variables = {"page_name": page.name, "page_index": str(position), "page_count": str(len(layout.pages))}
    for profile in layout.profiles:
        if profile.profile_id == layout.active_profile_id:
            variables["current_profile"] = profile.name
            variables["profile_id"] = str(profile.profile_id)
    return variables


class VariableChain(Mapping[str, str]):
    """Read-only variables looked up layer by layer, the first layer answering ``get`` winning."""

    def __init__(self, *layers: Mapping[str, str]) -> None:
        self._layers: tuple[Mapping[str, str], ...] = layers

    def __getitem__(self, key: str) -> str:
        value = self.get(key, _MISSING)
        if value is _MISSING:
            raise KeyError(key)
        return str(value)

    def __iter__(self) -> Iterator[str]:
        return iter(dict.fromkeys(key for layer in self._layers for key in layer))

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def get(self, key: str, default: Any = None) -> Any:
        """The first layer's answer for key (a layer's ``get`` may answer names it does not list), else default."""
        for layer in self._layers:
            value = layer.get(key, _MISSING)
            if value is not _MISSING:
                return value
        return default


def resolve_page(layout: DeviceLayout, page_id: Any) -> dict[str, Any]:
    """The `{page_id, name, index, profile_id}` a plugin receives for a stored page id; empty values when it is gone."""
    if isinstance(page_id, str):
        for profile_id, pages in layout.pages_by_profile.items():
            for position, page in enumerate(pages, start=1):
                if page.page_id == page_id:
                    return {"page_id": page.page_id, "name": page.name, "index": position, "profile_id": profile_id}
    return dict(EMPTY_PAGE)


def resolve_profile(layout: DeviceLayout, value: Any) -> dict[str, Any]:
    """The `{profile_id, name, index, icon}` a plugin receives for a stored profile ("" = the active one)."""
    if value == "":
        wanted: int | None = layout.active_profile_id
    else:
        wanted = int(value) if isinstance(value, str) and _PROFILE_ID.match(value) else None
    for position, profile in enumerate(layout.profiles, start=1):
        if profile.profile_id == wanted:
            return {
                "profile_id": profile.profile_id,
                "name": profile.name,
                "index": position,
                "icon": profile.icon or DECKER_ICON_REF,
            }
    return dict(EMPTY_PROFILE)


def has_dynamic_fields(schema: Sequence[SettingEntry]) -> bool:
    """Whether any field is a template or a page, i.e. its delivered value can change with the pages."""
    return any(
        isinstance(e, SettingField) and (e.type in ("page", "profile") or e.extra.get("template")) for e in schema
    )


def templated_texts(schema: Sequence[SettingEntry], settings: Mapping[str, Any]) -> list[str]:
    """The raw texts of the opted-in template fields (`text` and the text of `text_style`)."""
    texts: list[str] = []
    for entry in schema:
        if not isinstance(entry, SettingField) or not entry.extra.get("template"):
            continue
        value = settings.get(entry.key)
        if isinstance(value, dict):  # text_style
            value = value.get("text")
        if isinstance(value, str):
            texts.append(value)
    return texts


def deliver_settings(
    schema: Sequence[SettingEntry],
    settings: Mapping[str, Any],
    layout: DeviceLayout,
    variables: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """A copy of `settings` with opted-in text expanded and page/profile ids resolved; the input is left raw."""
    if variables is None:
        variables = page_variables(layout)
    result = {key: dict(value) if isinstance(value, dict) else value for key, value in settings.items()}
    for entry in schema:
        if not isinstance(entry, SettingField) or entry.key not in result:
            continue
        value = result[entry.key]
        if entry.type == "page":
            result[entry.key] = resolve_page(layout, value)
        elif entry.type == "profile":
            result[entry.key] = resolve_profile(layout, value)
        elif not entry.extra.get("template") or not variables:
            continue
        elif entry.type == "text" and isinstance(value, str):
            result[entry.key] = expand_template(value, variables)
        elif entry.type == "text_style" and isinstance(value, dict) and isinstance(value.get("text"), str):
            result[entry.key] = {**value, "text": expand_template(value["text"], variables)}
    return result


def stored_page_ids(schema: Sequence[SettingEntry], raw: Mapping[str, Any]) -> dict[str, Any]:
    """Turn a resolved page value a plugin echoed back into its page id so storing it keeps the choice."""
    result = dict(raw)
    for entry in schema:
        if isinstance(entry, SettingField) and entry.type == "page":
            value = result.get(entry.key)
            if isinstance(value, dict):
                result[entry.key] = value.get("page_id", "")
    return result


def stored_profile_ids(
    schema: Sequence[SettingEntry], incoming: Mapping[str, Any], delivered: Mapping[str, Any], raw: Mapping[str, Any]
) -> dict[str, Any]:
    """Turn resolved profile values a plugin echoed back into stored ids; an unchanged echo keeps the stored value."""
    result = dict(incoming)
    for entry in schema:
        if not isinstance(entry, SettingField) or entry.type != "profile" or entry.key not in result:
            continue
        value = result[entry.key]
        if not isinstance(value, dict):
            continue
        profile_id = value.get("profile_id")
        if value == delivered.get(entry.key) and isinstance(raw.get(entry.key), str):
            result[entry.key] = raw[entry.key]
        else:
            result[entry.key] = str(profile_id) if isinstance(profile_id, int) and profile_id >= 0 else ""
    return result


_RELATIVE = frozenset({"next", "previous", "first", "last"})


def _relative_target(ids: Sequence[Any], active: Any, payload: Mapping[str, Any]) -> Any | None:
    """The id `to: next|previous|first|last` leads to within `ids`, or None when invalid or it would stay put."""
    direction = payload.get("to")
    if direction not in _RELATIVE or active not in ids or len(ids) < 2:
        return None
    here = ids.index(active)
    wrap = payload.get("wrap") is True
    if direction == "first":
        target = 0
    elif direction == "last":
        target = len(ids) - 1
    else:
        target = here + (1 if direction == "next" else -1)
        if not 0 <= target < len(ids):
            target = target % len(ids) if wrap else here
    return ids[target] if target != here else None


def resolve_switch_target(layout: DeviceLayout, payload: Mapping[str, Any]) -> str | None:
    """The page id a `switch_page` request leads to, or None when it is invalid or would stay put.

    A `page_id` may be any page of the device; relative moves stay inside the active profile.
    """
    if "page_id" in payload:
        wanted = payload["page_id"]
        known = isinstance(wanted, str) and any(
            page.page_id == wanted for pages in layout.pages_by_profile.values() for page in pages
        )
        return wanted if known and wanted != layout.active_page_id else None
    return _relative_target([page.page_id for page in layout.pages], layout.active_page_id, payload)


def resolve_profile_switch_target(layout: DeviceLayout, payload: Mapping[str, Any]) -> int | None:
    """The profile id a `switch_profile` request leads to, or None when it is invalid or would stay put."""
    ids = [profile.profile_id for profile in layout.profiles]
    if "profile_id" in payload:
        wanted = payload["profile_id"]
        valid = isinstance(wanted, int) and not isinstance(wanted, bool) and wanted in ids
        return wanted if valid and wanted != layout.active_profile_id else None
    return _relative_target(ids, layout.active_profile_id, payload)


def keep_raw_templates(
    schema: Sequence[SettingEntry], incoming: Mapping[str, Any], delivered: Mapping[str, Any], raw: Mapping[str, Any]
) -> dict[str, Any]:
    """Undo the expansion of template fields a plugin echoed back unchanged, so the user's template survives."""
    result = dict(incoming)
    for entry in schema:
        if not isinstance(entry, SettingField) or not entry.extra.get("template") or entry.key not in result:
            continue
        value, sent, stored = result[entry.key], delivered.get(entry.key), raw.get(entry.key)
        if entry.type == "text" and value == sent and isinstance(stored, str):
            result[entry.key] = stored
        elif entry.type == "text_style" and isinstance(value, dict) and isinstance(sent, dict):
            if isinstance(stored, dict) and value.get("text") == sent.get("text") and "text" in stored:
                result[entry.key] = {**value, "text": stored["text"]}
    return result
