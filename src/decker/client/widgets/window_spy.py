"""Window Spy: shows the focused or picked window's properties; Set fills the selected rule, or make a new one."""

from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from decker.client.events import DetectionStatusEvent
from decker.client.widgets.rule_editor import FIELD_NAMES, unsupported_fields
from decker.common.model import AppRule, MatchCondition, WindowInfo

_FIELDS: dict[str, str] = {**FIELD_NAMES, "pid": "Process id"}
_UNAVAILABLE = "not available on this system"
_COUNTDOWN_SECONDS = 3
_CAPTURE_TIMEOUT_MS = 15000
_PICK_TIMEOUT_MS = 75000  # the server gives up after 60 s; this only fires if its result never arrives


def rule_from_window(window: WindowInfo) -> AppRule:
    """A new enabled rule matching the window's class (and its type when not normal)."""
    conditions: list[MatchCondition] = []
    if window.window_class:
        conditions.append(MatchCondition("window_class", "equals", window.window_class))
        if window.window_type and window.window_type != "normal":
            conditions.append(MatchCondition("window_type", "equals", window.window_type))
    return AppRule("", window.window_class or "New rule", True, conditions, 0, "")


class WindowSpyDialog(QDialog):  # pylint: disable=too-many-instance-attributes
    """Non-modal inspector for the window a rule should match."""

    create_rule = pyqtSignal(object)  # WindowInfo
    set_condition = pyqtSignal(str, str)  # field, value: switch that condition on the selected rule to ``is value``

    def __init__(
        self,
        call_pick: Callable[[], bool],
        own_pid: int,
        parent: QWidget | None = None,
        tick_ms: int = 1000,
        pick_timeout_ms: int = _PICK_TIMEOUT_MS,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Window Spy")
        self.setModal(False)
        self._call_pick = call_pick
        self._own_pid = own_pid
        self._status: DetectionStatusEvent | None = None
        self._window: WindowInfo | None = None
        self._picking = False
        self._countdown = 0
        self._capturing = False
        self._values: dict[str, QLineEdit] = {}
        self._set_buttons: dict[str, QPushButton] = {}
        self._can_set = False
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(tick_ms)
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.setInterval(_CAPTURE_TIMEOUT_MS)
        self._pick_timer = QTimer(self)
        self._pick_timer.setSingleShot(True)
        self._pick_timer.setInterval(pick_timeout_ms)
        self._build()
        self._pick_timer.timeout.connect(self._on_pick_timeout)
        self._tick_timer.timeout.connect(self._on_tick)
        self._timeout_timer.timeout.connect(self._on_capture_timeout)
        self._render()

    def _build(self) -> None:
        self._pick_button = QPushButton("Pick window")
        self._capture_button = QPushButton("Capture in 3 s")
        self._follow = QCheckBox("Follow")
        self._message = QLabel()
        self._message.setWordWrap(True)
        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._create_button = QPushButton("Create new rule")
        grid = QGridLayout()
        for row, (field, name) in enumerate(_FIELDS.items()):
            edit = QLineEdit()
            edit.setReadOnly(True)
            self._values[field] = edit
            grid.addWidget(QLabel(name), row, 0)
            grid.addWidget(edit, row, 1)
            if field in FIELD_NAMES:  # the process id is not something a rule can match on
                button = QPushButton("Set")
                button.setToolTip("Set the selected rule's condition to this value and switch it on")
                button.clicked.connect(lambda _c=False, f=field: self._set(f))
                self._set_buttons[field] = button
                grid.addWidget(button, row, 2)
        grid.setColumnStretch(1, 1)
        layout = QVBoxLayout(self)
        for widget in (self._pick_button, self._capture_button, self._follow):
            layout.addWidget(widget)
        layout.addWidget(self._status_label)
        layout.addWidget(self._message)
        layout.addLayout(grid)
        layout.addWidget(self._create_button)
        self._pick_button.clicked.connect(self._on_pick)
        self._capture_button.clicked.connect(self._on_capture)
        self._create_button.clicked.connect(self._on_create)
        self.resize(480, 340)

    # ------------------------------------------------------------------ feeding

    def set_status(self, status: DetectionStatusEvent) -> None:
        """Adopt the detection state: pick vs capture mode, greyed fields, disabled when not active."""
        self._status = status
        if status.state != "active":
            self.reset()
        self._render()

    def reset(self) -> None:
        """Abandon any open pick, capture or countdown (disconnect, detection lost, dialog hidden)."""
        self._picking = False
        self._pick_timer.stop()
        self._end_capture("")

    def hideEvent(self, a0: Any) -> None:  # pylint: disable=invalid-name
        """Closing or hiding the Spy abandons a capture or pick in progress."""
        super().hideEvent(a0)
        self.reset()

    def on_focused(self, window: WindowInfo) -> None:
        """A window gained focus; shown while following, or as the end of a capture."""
        if window.pid == self._own_pid or not (self._capturing or self._follow.isChecked()):
            return
        if self._capturing:
            self._end_capture("")
        self._show_window(window)

    def on_picked(self, window: WindowInfo | None) -> None:
        """The pick finished; None means it was cancelled and the previous window stays."""
        if not self._picking:
            return
        self._picking = False
        self._pick_timer.stop()
        if window is None:
            self._message.setText("Pick cancelled")
        else:
            self._message.setText("")
            self._show_window(window)
        self._render()

    # ------------------------------------------------------------------ actions

    def _on_pick(self) -> None:
        if not self._call_pick():
            self._message.setText("The server could not start a pick (another pick may be open).")
            return
        self._picking = True
        self._pick_timer.start()
        self._message.setText("Click a window to inspect it (Escape cancels).")
        self._render()

    def _on_pick_timeout(self) -> None:
        self._picking = False
        self._message.setText("Pick timed out")
        self._render()

    def _on_capture(self) -> None:
        self._countdown = _COUNTDOWN_SECONDS
        self._message.setText("")
        self._tick_timer.start()
        self._render()

    def _on_tick(self) -> None:
        self._countdown -= 1
        if self._countdown > 0:
            self._render()
            return
        self._tick_timer.stop()
        self._capturing = True
        self._timeout_timer.start()
        self._message.setText("Focus the window to capture.")
        self._render()

    def _on_capture_timeout(self) -> None:
        self._end_capture("Capture timed out")

    def _end_capture(self, message: str) -> None:
        self._capturing = False
        self._countdown = 0
        self._tick_timer.stop()
        self._timeout_timer.stop()
        self._message.setText(message)
        self._render()

    def _on_create(self) -> None:
        if self._window is not None:
            self.create_rule.emit(self._window)
            self.close()

    def _set(self, field: str) -> None:
        edit = self._values[field]
        if self._can_set and edit.isEnabled() and edit.text():
            self.set_condition.emit(field, edit.text())

    def set_rule_selected(self, selected: bool) -> None:
        """Whether a rule is selected in the dialog, i.e. whether Set has something to fill."""
        self._can_set = selected
        self._render()

    # ------------------------------------------------------------------ rendering

    def _show_window(self, window: WindowInfo) -> None:
        self._window = window
        self._render()

    def _render(self) -> None:
        status = self._status
        active = status is not None and status.state == "active"
        pick_mode = status is None or status.supports_pick
        busy = self._picking or self._capturing or self._countdown > 0
        self._pick_button.setVisible(pick_mode)
        self._capture_button.setVisible(not pick_mode)
        self._follow.setVisible(not pick_mode)
        self._pick_button.setEnabled(active and not busy)
        self._capture_button.setEnabled(active and not busy)
        self._capture_button.setText(f"Capture in {self._countdown} s" if self._countdown else "Capture in 3 s")
        self._follow.setEnabled(active)
        reason = (status.reason or "no reason given") if status is not None else ""
        unavailable = status is not None and not active
        self._status_label.setText(f"Window detection is {status.state}: {reason}" if unavailable and status else "")
        self._render_values(unsupported_fields(status.backend) if status is not None else set())
        self._create_button.setEnabled(active and self._window is not None)

    def _render_values(self, unsupported: set[str]) -> None:
        window = self._window
        for field, edit in self._values.items():
            missing = field in unsupported
            text = "" if window is None else str(getattr(window, field) or "")
            edit.setText(_UNAVAILABLE if missing else text)
            edit.setEnabled(not missing)
            button = self._set_buttons.get(field)
            if button is not None:
                button.setEnabled(not missing and self._can_set and bool(text))
