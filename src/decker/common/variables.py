"""Rules for plugin variable names, name patterns and values."""

import re
from typing import Any

from decker.common.template import TEMPLATE_VARIABLES

MAX_NAME_LENGTH = 64
MAX_VALUE_LENGTH = 1024
MAX_DECLARATIONS = 256
MAX_REGISTERED = 256
CORE_VARIABLE_NAMES: frozenset[str] = frozenset(TEMPLATE_VARIABLES)

_NAME = re.compile(r"[a-z][a-z0-9_]*")
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def is_valid_name(name: str) -> bool:
    """Whether name is a legal variable name."""
    return len(name) <= MAX_NAME_LENGTH and _NAME.fullmatch(name) is not None


def is_valid_pattern(pattern: str) -> bool:
    """Whether pattern is a legal name pattern with unique, separated ``{placeholder}`` parts."""
    found = _PLACEHOLDER.findall(pattern)
    if not found or len(set(found)) != len(found):
        return False
    if "}{" in pattern:
        return False
    return is_valid_name(_PLACEHOLDER.sub("x", pattern))


def match_pattern(pattern: str, name: str) -> dict[str, str] | None:
    """Return the placeholder values when name fits pattern, else None."""
    regex = ""
    last = 0
    for found in _PLACEHOLDER.finditer(pattern):
        regex += re.escape(pattern[last : found.start()]) + f"(?P<{found.group(1)}>[a-z0-9_]+)"
        last = found.end()
    matched = re.fullmatch(regex + re.escape(pattern[last:]), name)
    return matched.groupdict() if matched else None


def pattern_shape(pattern: str) -> str:
    """Return pattern with every placeholder replaced by ``{}``."""
    return _PLACEHOLDER.sub("{}", pattern)


def value_text(value: Any) -> str | None:
    """Convert a plugin-supplied value to variable text; None stays None."""
    if value is None:
        return None
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (str, int, float)):
        text = str(value)
    else:
        raise ValueError(f"unsupported variable value type: {type(value).__name__}")
    if len(text) > MAX_VALUE_LENGTH:
        raise ValueError(f"variable value longer than {MAX_VALUE_LENGTH} characters")
    return text
