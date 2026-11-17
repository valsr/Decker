"""Page variables for key templates and the delivery form of settings (expanded text, resolved pages)."""

from collections.abc import Mapping, Sequence
from typing import Any

from decker.common.model import PageInfo
from decker.common.template import expand_template
from decker.plugin.settings_schema import SettingEntry, SettingField

EMPTY_PAGE: dict[str, Any] = {"page_id": "", "name": "", "index": 0}


def page_variables(pages: Sequence[PageInfo], active_page_id: str) -> dict[str, str]:
    """Variables for the page shown on a device; empty when the active page is not among its pages."""
    for position, page in enumerate(pages, start=1):
        if page.page_id == active_page_id:
            return {"page_name": page.name, "page_index": str(position), "page_count": str(len(pages))}
    return {}


def resolve_page(pages: Sequence[PageInfo], page_id: Any) -> dict[str, Any]:
    """The `{page_id, name, index}` a plugin receives for a stored page id; empty values when it is gone."""
    if isinstance(page_id, str):
        for position, page in enumerate(pages, start=1):
            if page.page_id == page_id:
                return {"page_id": page.page_id, "name": page.name, "index": position}
    return dict(EMPTY_PAGE)


def has_dynamic_fields(schema: Sequence[SettingEntry]) -> bool:
    """Whether any field is a template or a page, i.e. its delivered value can change with the pages."""
    return any(isinstance(e, SettingField) and (e.type == "page" or e.extra.get("template")) for e in schema)


def deliver_settings(
    schema: Sequence[SettingEntry], settings: Mapping[str, Any], variables: Mapping[str, str], pages: Sequence[PageInfo]
) -> dict[str, Any]:
    """A copy of `settings` with opted-in text expanded and page ids resolved; the input is left raw."""
    result = {key: dict(value) if isinstance(value, dict) else value for key, value in settings.items()}
    for entry in schema:
        if not isinstance(entry, SettingField) or entry.key not in result:
            continue
        value = result[entry.key]
        if entry.type == "page":
            result[entry.key] = resolve_page(pages, value)
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
