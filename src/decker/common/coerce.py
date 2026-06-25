"""Typed deserialization for JSON-decoded plain Python data into dataclasses."""

import dataclasses
from typing import Any, Union, get_args, get_origin, get_type_hints


def from_dict(target_type: Any, value: Any) -> Any:  # pylint: disable=too-many-return-statements
    """Recursively convert a JSON-decoded value to target_type.

    Handles list[T], X | None (Optional), dataclasses from dicts, enums from
    strings, and plain primitives. Designed for post-json.loads() data only —
    no RPyC netref traversal.
    """
    if value is None:
        return None

    origin = get_origin(target_type)
    type_args = get_args(target_type)

    if origin is list:
        item_type = type_args[0] if type_args else Any
        return [from_dict(item_type, item) for item in value]

    if origin is Union:
        non_none = [t for t in type_args if t is not type(None)]
        if len(non_none) == 1:
            return from_dict(non_none[0], value)
        return value

    if not isinstance(target_type, type):
        return value

    if dataclasses.is_dataclass(target_type):
        if isinstance(value, target_type):
            return value
        if not isinstance(value, dict):
            return value
        hints = get_type_hints(target_type)
        valid = {f.name for f in dataclasses.fields(target_type)}
        kwargs = {}
        for k, v in value.items():
            if k in valid:
                field_type: Any = hints.get(k)
                kwargs[k] = from_dict(field_type, v)
        return target_type(**kwargs)

    if isinstance(value, target_type):
        return value

    return target_type(value)
