"""Native Decker plugin API.

# TODO: [SDK] Extract into standalone decker-sdk package before any third-party native plugin support
"""

from decker.plugin.base import DeckerPlugin, action
from decker.plugin.context import ActionContext

__all__ = ["DeckerPlugin", "action", "ActionContext"]
