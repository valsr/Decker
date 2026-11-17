"""Settings control for a page: a dropdown of the selected key's device pages, stored as the page id."""

import json
import logging
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QStandardItemModel
from PyQt6.QtWidgets import QComboBox, QWidget

from decker.client.context import AppContext
from decker.client.icon_picker import RpcCaller

_NO_PAGE = "(no page)"
_DELETED = "(deleted page)"
_NO_DEVICE_HINT = "Select a key on a device first"


def _app_device_id() -> str | None:
    return AppContext.get().active_device_id


def _app_rpc() -> RpcCaller | None:
    return AppContext.get().connection_manager


class PageEdit(QComboBox):
    """Pick one of the device's pages; ``value()`` is its page id (``""`` for none)."""

    value_changed = pyqtSignal()

    def __init__(
        self,
        device_id: Callable[[], str | None] | None = None,
        rpc: Callable[[], RpcCaller | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._device_id = device_id or _app_device_id
        self._rpc = rpc or _app_rpc
        self._value = ""
        self._profile = ""  # a profile id as text; blank lists the pages of the current profile
        self._pages: list[tuple[str, str]] = []
        self.activated.connect(self._on_activated)
        self.reload()

    def value(self) -> str:
        """The chosen page id, or an empty string."""
        return self._value

    def set_value(self, value: Any) -> None:
        """Show ``value`` (any non-string means no page) without emitting ``value_changed``."""
        self._value = value if isinstance(value, str) else ""
        self._rebuild()

    def set_profile(self, profile: Any, clear_missing: bool = False) -> None:
        """List the pages of this profile id (blank or invalid: the current profile) instead.

        With ``clear_missing`` (the user changed the profile) a chosen page that is not in the new list is dropped
        and ``value_changed`` is emitted; otherwise the stored page stays and shows as deleted if it is not listed.
        """
        self._profile = profile if isinstance(profile, str) and profile.isascii() and profile.isdigit() else ""
        self.reload()
        if clear_missing and self._value and self._value not in {page_id for page_id, _name in self._pages}:
            self._value = ""
            self._rebuild()
            self.value_changed.emit()

    def reload(self) -> None:
        """Re-read the device's pages from the server."""
        self._pages = self._fetch_pages()
        self._rebuild()

    def _fetch_pages(self) -> list[tuple[str, str]]:
        device_id, rpc = self._device_id(), self._rpc()
        if not device_id or rpc is None:
            return []
        try:
            extra = (int(self._profile),) if self._profile else ()
            data = json.loads(rpc.call("pages_list", device_id, *extra) or "null")
            return [(str(p["page_id"]), str(p["name"])) for p in data["pages"]]
        except Exception as exc:  # pylint: disable=broad-except
            logging.warning("Could not list pages for %s: %s", device_id, exc)
            return []

    def _rebuild(self) -> None:
        self.blockSignals(True)
        self.clear()
        self.addItem(_NO_PAGE, "")
        for page_id, name in self._pages:
            self.addItem(name, page_id)
        known = {page_id for page_id, _name in self._pages}
        if self._value and self._pages and self._value not in known:
            self.addItem(_DELETED, self._value)
            model = self.model()
            item = model.item(self.count() - 1) if isinstance(model, QStandardItemModel) else None
            if item is not None:
                item.setEnabled(False)
        index = self.findData(self._value)
        self.setCurrentIndex(max(index, 0))
        self.setToolTip("" if self._pages else _NO_DEVICE_HINT)
        self.blockSignals(False)

    def _on_activated(self, index: int) -> None:
        data = self.itemData(index)
        self._value = data if isinstance(data, str) else ""
        self.value_changed.emit()
