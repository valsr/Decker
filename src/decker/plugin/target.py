"""Identity of one action instance on a key."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionTarget:
    """Identifies one action instance: which plugin/action it belongs to and where it lives.

    context_id is stable across key moves — settings keyed by it survive reassignment
    of the action to a different physical key.
    """

    plugin_uuid: str
    action_uuid: str
    context_id: str
    device_id: str
    key_index: int
