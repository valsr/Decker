"""Settings → Plugins: configured plugin repositories, update-check schedule and manual check."""

import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from decker.client.connection_manager import to_plain
from decker.client.context import AppContext
from decker.client.events import RepositoriesCheckFinishedEvent, ServerDisconnectedEvent
from decker.client.events.event_manager import EventManager
from decker.client.widgets.plugins_tab import NOT_ALLOWED_TOOLTIP, install_allowed

REPOSITORY_TRUST_WARNING = (
    "A repository can provide any plugin, and plugins run with your user's permissions. "
    "Only add repositories you trust."
)
SCHEDULES = ("Daily", "Weekly", "Monthly", "Manual")
_URL_ROLE = Qt.ItemDataRole.UserRole


def _describe(repo: dict[str, Any]) -> str:
    checked = repo.get("last_checked")
    when = datetime.fromtimestamp(float(checked)).strftime("%Y-%m-%d %H:%M") if checked else "never"
    count = int(repo.get("plugin_count") or 0)
    text = (
        f"{repo.get('name') or repo['url']}\n{repo['url']} · {count} plugin{'' if count == 1 else 's'} · checked {when}"
    )
    if repo.get("error"):
        text += f"\nError: {repo['error']}"
    return text


class RepositoriesSection(QWidget):  # pylint: disable=too-many-instance-attributes
    """Lists plugin repositories and manages them; every RPC runs on a worker thread."""

    _finished = pyqtSignal(object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._list: QListWidget = QListWidget()
        self._add_btn: QPushButton = QPushButton("Add…")
        self._remove_btn: QPushButton = QPushButton("Remove")
        self._check_btn: QPushButton = QPushButton("Check for updates")
        self._schedule: QComboBox = QComboBox()
        self._status: QLabel = QLabel()
        self._worker: threading.Thread | None = None
        self._build()
        em = EventManager.get()
        em.subscribe(RepositoriesCheckFinishedEvent, self._on_check_finished)
        em.subscribe(ServerDisconnectedEvent, self._on_disconnected)

    def refresh(self) -> None:
        """Re-fetch the repositories and the schedule from the server."""
        self._apply_allowed()
        self._run(self._fetch, self._show_state)

    def _build(self) -> None:
        self._schedule.addItems(SCHEDULES)
        self._status.setWordWrap(True)
        self._status.setProperty("role", "muted")
        self._remove_btn.setEnabled(False)
        self._finished.connect(self._deliver)
        self._list.currentItemChanged.connect(lambda *_: self._apply_allowed())
        self._add_btn.clicked.connect(self._on_add)
        self._remove_btn.clicked.connect(self._on_remove)
        self._check_btn.clicked.connect(self._on_check)
        self._schedule.currentIndexChanged.connect(self._on_schedule_changed)

        buttons = QHBoxLayout()
        for widget in (self._add_btn, self._remove_btn, self._check_btn):
            buttons.addWidget(widget)
        buttons.addStretch()
        buttons.addWidget(QLabel("Update check:"))
        buttons.addWidget(self._schedule)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Repositories"))
        layout.addWidget(self._list)
        layout.addLayout(buttons)
        layout.addWidget(self._status)
        self._apply_allowed()

    def _apply_allowed(self) -> None:
        allowed = install_allowed()
        tip = "" if allowed else NOT_ALLOWED_TOOLTIP
        self._add_btn.setEnabled(allowed)
        self._remove_btn.setEnabled(allowed and self._list.currentItem() is not None)
        self._schedule.setEnabled(allowed)
        for widget in (self._add_btn, self._remove_btn, self._schedule):
            widget.setToolTip(tip)

    def _run(self, work: Callable[[Any], Any], done: Callable[[Any], None]) -> None:
        manager = AppContext.get().connection_manager
        if manager is None:
            self._status.setText("Not connected to the server.")
            self._check_btn.setEnabled(True)
            return

        def target() -> None:
            self._finished.emit(done, work(manager))

        self._worker = threading.Thread(target=target, daemon=True)
        self._worker.start()

    def _deliver(self, done: Callable[[Any], None], result: Any) -> None:
        done(result)

    @staticmethod
    def _fetch(manager: Any) -> tuple[Any, Any]:
        return to_plain(manager.call("repositories_list")), manager.call("update_check_schedule")

    def _show_state(self, state: tuple[Any, Any]) -> None:
        repos, schedule = state
        self._list.clear()
        for repo in repos if isinstance(repos, list) else []:
            item = QListWidgetItem(_describe(repo))
            item.setData(_URL_ROLE, repo["url"])
            self._list.addItem(item)
        if isinstance(schedule, str) and schedule.capitalize() in SCHEDULES:
            self._schedule.blockSignals(True)
            self._schedule.setCurrentText(schedule.capitalize())
            self._schedule.blockSignals(False)
        self._apply_allowed()

    def _on_add(self) -> None:
        url, ok = QInputDialog.getText(self, "Add repository", "Repository index URL:")
        url = url.strip()
        if not ok or not url:
            return
        answer = QMessageBox.question(
            self, "Add repository", REPOSITORY_TRUST_WARNING, defaultButton=QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._status.setText(f"Adding {url}…")
        self._run(lambda m: m.call("repository_add", url), lambda error: self._after_mutation(error, "Added."))

    def _on_remove(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        url = str(item.data(_URL_ROLE))
        answer = QMessageBox.question(
            self, "Remove repository", f"Remove {url}?", defaultButton=QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._run(
            lambda m: m.call("repository_remove", url),
            lambda ok: self._after_mutation("" if ok else "Could not remove the repository.", "Removed."),
        )

    def _on_schedule_changed(self, _index: int) -> None:
        name = self._schedule.currentText().lower()
        self._run(
            lambda m: m.call("update_check_set_schedule", name),
            self._after_schedule,
        )

    def _after_schedule(self, ok: Any) -> None:
        if ok:
            self._status.setText("")
            return
        self._status.setText("Could not change the schedule.")
        self.refresh()

    def _on_check(self) -> None:
        self._status.setText("Checking for updates…")
        self._check_btn.setEnabled(False)
        self._run(lambda m: to_plain(m.call("repositories_check")), self._after_check)

    def _after_check(self, result: Any) -> None:
        if not isinstance(result, dict):
            self._status.setText("Could not check for updates.")
            self._check_btn.setEnabled(True)
        elif not result.get("started"):
            self._status.setText(str(result.get("reason") or "Could not start the check."))
            self._check_btn.setEnabled(True)

    def _on_check_finished(self, event: RepositoriesCheckFinishedEvent) -> None:
        self._check_btn.setEnabled(True)
        failed = sum(1 for repo in event.repositories if repo.get("error"))
        self._status.setText(
            "Check finished."
            if not failed
            else f"Check finished; {failed} repositor{'y' if failed == 1 else 'ies'} failed."
        )
        self.refresh()

    def _on_disconnected(self, _event: ServerDisconnectedEvent) -> None:
        self._check_btn.setEnabled(True)

    def _after_mutation(self, error: Any, success: str) -> None:
        if error is None:
            error = "Could not reach the server."
        self._status.setText(str(error) if error else success)
        self.refresh()
