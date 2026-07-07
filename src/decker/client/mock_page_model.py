"""In-memory stub page model: two hard-coded pages with empty key slots.

Replaced by the real profile/page data model in a future plan.
"""

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PageData:
    """One page: a stable id, a display name, and key_count empty key slots."""

    page_id: str
    name: str
    key_count: int
    slots: list[None] = field(default_factory=list)


class MockPageModel:
    """Hard-codes two pages ("Page 1", "Page 2") matching the active device's key count."""

    def __init__(self, key_count: int = 15) -> None:
        self._pages = [
            PageData(page_id=str(uuid.uuid4()), name="Page 1", key_count=key_count, slots=[None] * key_count),
            PageData(page_id=str(uuid.uuid4()), name="Page 2", key_count=key_count, slots=[None] * key_count),
        ]

    @property
    def pages(self) -> list[PageData]:
        """Return all pages, in display order."""
        return list(self._pages)
