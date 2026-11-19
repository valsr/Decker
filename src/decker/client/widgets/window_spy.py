"""Window Spy: shows the focused or picked window's properties and turns them into a rule."""

from collections.abc import Callable

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

    def __init__(
        self,
        call_pick: Callable[[], bool],
        own_pid: int,
        parent: QWidget | None = None,
        tick_ms: int = 1000,
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
        self._copy_buttons: dict[str, QPushButton] = {}
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(tick_ms)
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.setInterval(_CAPTURE_TIMEOUT_MS)
        self._build()
        self._tick_timer.timeout.connect(self._on_tick)
        self._timeout_timer.timeout.connect(self._on_capture_timeout)
        self._render()

    def _build(self) -> None:
        self._pick_button = QPushButton("Pick window")
        self._capture_button = QPushButton("Capture in 3 s")
        self._follow = QCheckBox("Follow")
        self._message = QLabel()
        self._message.setWordWrap(True)
        self._create_button = QPushButton("Create rule from this window")
        grid = QGridLayout()
        for row, (field, name) in enumerate(_FIELDS.items()):
            edit, copy = QLineEdit(), QPushButton("Copy")
            edit.setReadOnly(True)
            copy.clicked.connect(lambda _c=False, f=field: self._copy(f))
            self._values[field], self._copy_buttons[field] = edit, copy
            grid.addWidget(QLabel(name), row, 0)
            grid.addWidget(edit, row, 1)
            grid.addWidget(copy, row, 2)
        grid.setColumnStretch(1, 1)
        layout = QVBoxLayout(self)
        for widget in (self._pick_button, self._capture_button, self._follow):
            layout.addWidget(widget)
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
        self._render()

    def on_focused(self, window: WindowInfo) -> None:
        """A window gained focus; shown while following, or as the end of a capture."""
        if window.pid == self._own_pid or not (self._capturing or self._follow.isChecked()):
            return
        if self._capturing:
            self._end_capture("")
        self._show_window(window)

    def on_picked(self, window: WindowInfo | None) -> None:
        """The pick finished; None means it was cancelled and the previous window stays."""
        self._picking = False
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
        self._message.setText("Click a window to inspect it (Escape cancels).")
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

    def _copy(self, field: str) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None and self._values[field].isEnabled():
            clipboard.setText(self._values[field].text())

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
        if status is not None and not active:
            reason = status.reason or "no reason given"
            self._message.setText(f"Window detection is {status.state}: {reason}")
        self._render_values(unsupported_fields(status.backend) if status is not None else set())
        self._create_button.setEnabled(active and self._window is not None)

    def _render_values(self, unsupported: set[str]) -> None:
        window = self._window
        for field, edit in self._values.items():
            missing = field in unsupported
            text = "" if window is None else str(getattr(window, field))
            edit.setText(_UNAVAILABLE if missing else text)
            edit.setEnabled(not missing)
            self._copy_buttons[field].setEnabled(not missing)
