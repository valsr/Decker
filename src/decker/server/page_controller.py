"""Coordinates page changes across the page store, key assignments, plugins and hardware."""

import json
import logging
import threading
from typing import TYPE_CHECKING

from decker.common.manager import Manager
from decker.common.model import DevicePages, PageInfo

if TYPE_CHECKING:
    from decker.server.server_context import ServerContext

PAGES_CHANGED_EVENT = "pages_changed"


class PageController(Manager):
    """Tracks which page each device shows and performs page lifecycle changes.

    Only the active page's actions are live: switching pages deactivates the old page's actions,
    redraws the hardware from the new page's cached images, then activates the new page's actions.
    Every change pushes a pages_changed event so clients refresh. Active pages are held in memory;
    each device starts on its default page.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active: dict[str, str] = {}
        self._context: "ServerContext | None" = None

    def create(self, context: "ServerContext") -> None:
        """Bind the server context."""
        self._context = context

    def destroy(self) -> None:
        """Forget the active pages."""
        with self._lock:
            self._active.clear()

    @property
    def _ctx(self) -> "ServerContext":
        assert self._context is not None, "PageController.create() must be called before use"
        return self._context

    def active_page_id(self, device_id: str) -> str:
        """The page shown on the device; its default page until another is activated.

        Lock-free once a page is recorded: hardware/plugin paths call this while holding their own
        locks, so taking the controller lock here would invert the lock order against page switches.
        """
        recorded = self._active.get(device_id)
        if recorded is not None and self._ctx.page_store.get(device_id, recorded) is not None:
            return recorded
        with self._lock:
            page_id = self._active.get(device_id)
            if page_id is None or self._ctx.page_store.get(device_id, page_id) is None:
                page_id = self._ctx.page_store.default_page_id(device_id)
                self._active[device_id] = page_id
            return page_id

    def device_pages(self, device_id: str) -> DevicePages:
        """Return the device's pages, default page and active page."""
        with self._lock:
            store = self._ctx.page_store
            return DevicePages(
                device_id=device_id,
                pages=store.list_pages(device_id),
                default_page_id=store.default_page_id(device_id),
                active_page_id=self.active_page_id(device_id),
            )

    def restore(self, device_id: str) -> None:
        """Show the device's active page and activate its actions (used at server start)."""
        with self._lock:
            self._show(device_id, self.active_page_id(device_id))

    def activate(self, device_id: str, page_id: str) -> bool:
        """Switch the device to page_id. Returns False for an unknown page."""
        with self._lock:
            if self._ctx.page_store.get(device_id, page_id) is None:
                return False
            current = self.active_page_id(device_id)
            if current != page_id:
                self._hide(device_id, current)
                self._active[device_id] = page_id
                self._show(device_id, page_id)
        self._notify(device_id)
        return True

    def add_page(self, device_id: str, name: str | None = None) -> PageInfo:
        """Append a new empty page; it does not become active."""
        page = self._ctx.page_store.add_page(device_id, name)
        self._notify(device_id)
        return page

    def rename_page(self, device_id: str, page_id: str, name: str) -> bool:
        """Rename a page. Returns False for an unknown page or a blank name."""
        renamed = self._ctx.page_store.rename_page(device_id, page_id, name)
        if renamed:
            self._notify(device_id)
        return renamed

    def set_default_page(self, device_id: str, page_id: str) -> bool:
        """Make page_id the page shown when the server starts. Returns False for an unknown page."""
        updated = self._ctx.page_store.set_default_page(device_id, page_id)
        if updated:
            self._notify(device_id)
        return updated

    def delete_page(self, device_id: str, page_id: str) -> bool:
        """Delete a page with its assignments and cached key state. Refuses the last page.

        Deleting the active page first switches the device to the next page (or the previous one
        if it was the last).
        """
        with self._lock:
            ids = [page.page_id for page in self._ctx.page_store.list_pages(device_id)]
            if page_id not in ids or len(ids) == 1:
                return False
            if self.active_page_id(device_id) == page_id:
                position = ids.index(page_id)
                neighbour = ids[position + 1] if position + 1 < len(ids) else ids[position - 1]
                self._hide(device_id, page_id)
                self._active[device_id] = neighbour
                self._show(device_id, neighbour)
            self._ctx.key_assignment_store.delete_page(device_id, page_id)
            self._ctx.device_state_store.delete_page_state(device_id, page_id)
            self._ctx.page_store.delete_page(device_id, page_id)
        self._notify(device_id)
        return True

    def _hide(self, device_id: str, page_id: str) -> None:
        plugins = self._ctx.plugin_manager
        for _key_index, assignment in self._ctx.key_assignment_store.all_for_page(device_id, page_id):
            plugins.deactivate_action(assignment.target)

    def _show(self, device_id: str, page_id: str) -> None:
        if not self._ctx.device_manager.show_page(device_id, page_id):
            logging.warning("PageController: device %s is not available; page %s not drawn", device_id, page_id)
        plugins = self._ctx.plugin_manager
        for _key_index, assignment in self._ctx.key_assignment_store.all_for_page(device_id, page_id):
            target = assignment.target
            plugins.store_settings(target, assignment.settings)
            plugins.activate_action(target)

    def _notify(self, device_id: str) -> None:
        self._ctx.event_bus.push(PAGES_CHANGED_EVENT, json.dumps({"device_id": device_id}))
