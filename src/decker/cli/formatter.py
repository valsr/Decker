"""Format RPyC command results as human-readable text."""

from typing import Any


def format_result(value: Any) -> str:
    """Format a command result as human-readable text."""
    if isinstance(value, bool):
        return "ok" if value else "failed"
    if isinstance(value, dict):
        return _format_dict(value)
    if value is None:
        return "(no output)"
    return str(value)


def _format_dict(data: dict[str, Any]) -> str:
    lines = []
    for key, val in data.items():
        if isinstance(val, float):
            formatted = f"{val:.3f}"
        elif val is True:
            formatted = "yes"
        elif val is False:
            formatted = "no"
        else:
            formatted = str(val)
        lines.append(f"  {key}: {formatted}")
    return "\n".join(lines)
