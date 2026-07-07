"""Server-side plugin events surfaced to clients via polling RPC."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PluginLoadFailedEvent:
    """A plugin in ~/.decker/plugins/ failed to load and was skipped."""

    plugin_uuid: str
    error: str
