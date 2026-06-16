"""In-memory registry of live action instances, keyed by their context identity."""

from decker.plugin.base import DeckerPlugin

_RegistryKey = tuple[str, str, str]


class ActionRegistry:
    """Maps (plugin_uuid, action_uuid, context_id) to the live action instance on that key."""

    def __init__(self) -> None:
        self._instances: dict[_RegistryKey, DeckerPlugin] = {}

    def register(self, plugin_uuid: str, action_uuid: str, context_id: str, instance: DeckerPlugin) -> None:
        """Record a new action instance as active for this context."""
        self._instances[(plugin_uuid, action_uuid, context_id)] = instance

    def unregister(self, plugin_uuid: str, action_uuid: str, context_id: str) -> None:
        """Remove an action instance. No-op if it was not registered."""
        self._instances.pop((plugin_uuid, action_uuid, context_id), None)

    def get(self, plugin_uuid: str, action_uuid: str, context_id: str) -> DeckerPlugin | None:
        """Return the live instance for this context, or None if not registered."""
        return self._instances.get((plugin_uuid, action_uuid, context_id))

    def instance_count(self, plugin_uuid: str, action_uuid: str) -> int:
        """Return how many live instances currently exist for this action UUID."""
        return sum(1 for (puid, auid, _) in self._instances if puid == plugin_uuid and auid == action_uuid)
