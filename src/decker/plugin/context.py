"""ActionContext — inbound event data and outbound API available to action handlers."""

from dataclasses import dataclass
from typing import Protocol


class HardwareSink(Protocol):
    """Destination for an action's outbound hardware effects.

    Implementations translate these calls into real Stream Deck hardware updates.
    Tests inject a stand-in that records calls instead of touching hardware.
    """

    def set_image(self, device_id: str, key_index: int, image: bytes) -> None:
        """Render image on the given device's key."""

    def set_title(self, device_id: str, key_index: int, title: str) -> None:
        """Overlay a text title on the given device's key."""

    def set_state(self, device_id: str, key_index: int, state: int) -> None:
        """Switch the key to one of its multiple visual states."""

    def show_alert(self, device_id: str, key_index: int) -> None:
        """Briefly flash a warning indicator on the key."""

    def show_ok(self, device_id: str, key_index: int) -> None:
        """Briefly flash a success indicator on the key."""


class SettingsStore(Protocol):
    """Persistence for per-context action settings."""

    def get_settings(self, plugin_uuid: str, action_uuid: str, context_id: str) -> dict:
        """Return the persisted settings for this action instance, or {} if none."""

    def set_settings(self, plugin_uuid: str, action_uuid: str, context_id: str, settings: dict) -> None:
        """Persist settings for this action instance."""


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


class ActionContext:
    """Identifies one instance of an action on a key, and exposes the plugin-facing API."""

    def __init__(self, target: ActionTarget, sink: HardwareSink, settings_store: SettingsStore) -> None:
        self.plugin_uuid = target.plugin_uuid
        self.action_uuid = target.action_uuid
        self.context_id = target.context_id
        self.device_id = target.device_id
        self.key_index = target.key_index
        self._sink = sink
        self._settings_store = settings_store

    def set_image(self, image: bytes) -> None:
        """Render image on this action's key."""
        self._sink.set_image(self.device_id, self.key_index, image)

    def set_title(self, title: str) -> None:
        """Overlay a text title on this action's key."""
        self._sink.set_title(self.device_id, self.key_index, title)

    def set_state(self, state: int) -> None:
        """Switch this action's key to one of its multiple visual states."""
        self._sink.set_state(self.device_id, self.key_index, state)

    def show_alert(self) -> None:
        """Briefly flash a warning indicator on this action's key."""
        self._sink.show_alert(self.device_id, self.key_index)

    def show_ok(self) -> None:
        """Briefly flash a success indicator on this action's key."""
        self._sink.show_ok(self.device_id, self.key_index)

    def set_settings(self, settings: dict) -> None:
        """Persist settings for this action instance, retrievable across restarts."""
        self._settings_store.set_settings(self.plugin_uuid, self.action_uuid, self.context_id, settings)

    def get_settings(self) -> dict:
        """Return this action instance's persisted settings, or {} if none were set."""
        return self._settings_store.get_settings(self.plugin_uuid, self.action_uuid, self.context_id)
