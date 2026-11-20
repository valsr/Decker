"""Identity of one card instance on a key."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CardTarget:
    """Identifies one card instance: which plugin/card it belongs to and where it lives.

    context_id is stable across key moves — settings keyed by it survive reassignment
    of the card to a different physical key.
    """

    plugin_uuid: str
    card_uuid: str
    context_id: str
    device_id: str
    key_index: int
