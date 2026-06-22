"""Recursive type coercion for deserializing RPyC responses into typed Python objects."""

import dataclasses
import logging
from typing import Any, Union, get_args, get_origin, get_type_hints


def coerce(target_type: Any, value: Any) -> Any:
    """Recursively convert value to target_type, handling generics and dataclasses.

    Handles list[T], dict[K, V], Optional[T] / X | None, Union[A, B], plain types,
    and dataclasses (from dicts or RPyC netrefs).
    """
    if value is None:
        return None

    origin = get_origin(target_type)
    type_args = get_args(target_type)

    if origin is list:
        items = list(value)
        return [coerce(type_args[0], item) for item in items] if type_args else items

    if origin is dict:
        pairs = dict(value)
        if len(type_args) == 2:
            return {coerce(type_args[0], k): coerce(type_args[1], v) for k, v in pairs.items()}
        return pairs

    if origin is Union:
        non_none = [t for t in type_args if t is not type(None)]
        for t in non_none:
            try:
                return coerce(t, value)
            except Exception:  # pylint: disable=broad-except
                continue
        logging.warning("coerce: value does not match any type in %s, returning as-is", target_type)
        return value

    if origin is not None:
        logging.warning("coerce: unsupported generic origin %s, returning value as-is", origin)
        return value

    if not isinstance(target_type, type):
        return value

    if dataclasses.is_dataclass(target_type):
        if isinstance(value, target_type):
            return value
        if isinstance(value, dict):
            data = value
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            data = dataclasses.asdict(value)
        else:
            # RPyC netref — materialize by reading each field by name
            logging.warning("coerce: value is a netref, materializing fields for %s", target_type)
            data = {f.name: getattr(value, f.name) for f in dataclasses.fields(target_type)}
        try:
            hints = get_type_hints(target_type)
        except Exception:  # pylint: disable=broad-except
            hints = {}
        valid = {f.name for f in dataclasses.fields(target_type)}
        return target_type(**{k: coerce(hints[k], v) if k in hints else v for k, v in data.items() if k in valid})

    if isinstance(value, target_type):
        return value

    return target_type(value)
