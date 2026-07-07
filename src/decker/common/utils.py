"""Utilities for API serialization."""

import dataclasses
import functools
import json
from enum import Enum
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def _to_wire(obj: Any) -> Any:
    """Recursively convert a value to JSON-serializable plain Python types.

    Brine uses exact type matching, so StrEnum members (and other Enum subclasses)
    cannot be serialized directly — they must be reduced to their .value first.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _to_wire(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, list):
        return [_to_wire(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _to_wire(v) for k, v in obj.items()}
    return obj


def api_response(func: F) -> F:
    """Decorator that serializes the return value to a JSON string via _to_wire."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        return json.dumps(_to_wire(func(*args, **kwargs)))

    return wrapper  # type: ignore[return-value]
