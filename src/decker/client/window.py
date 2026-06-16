"""Main application window — view registry, navigation, and event dispatch."""

from typing import Any

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMainWindow, QStackedWidget

from decker.client.assets import ICON_PATH
from decker.client.connection_manager import ConnectionManager
from decker.client.context import AppContext
from decker.client.event_hub import EventHub
from decker.client.events import AppEvent, ServerConnectedEvent, ServerDisconnectedEvent
from decker.client.view_name import ViewName
from decker.client.views import (
    BaseView,
    ConnectingView,
    DashboardView,
    DeviceView,
    ErrorView,
    SettingsView,
)

_DRAIN_INTERVAL_MS = 16
_INITIAL_VIEW_RECHECK_MS = 50


class MainWindow(QMainWindow):
    """Owns the QStackedWidget of registered views and routes AppEvents to them."""

    def __init__(self, connection_manager: ConnectionManager) -> None:
        super().__init__()
        self._connection_manager: ConnectionManager = connection_manager
        self._views: dict[ViewName, BaseView] = {}
        self._active: ViewName | None = None
        self._last_view: ViewName | None = None

        AppContext.get().window = self

        self._stack: QStackedWidget = QStackedWidget()
        self._register_all_views()
        self._build_ui()

        self._drain_timer: QTimer = QTimer(self)
        self._drain_timer.timeout.connect(self._drain_events)
        self._drain_timer.start(_DRAIN_INTERVAL_MS)

    def register_view(self, name: ViewName, view: BaseView) -> None:
        """Add a view to the stack and the navigation registry."""
        self._stack.addWidget(view)
        self._views[name] = view

    def switch_to(self, name: ViewName) -> None:
        """Deactivate the current view (if any) and activate the named view."""
        if self._active == name:
            return
        if self._active is not None:
            self._views[self._active].on_deactivate()
        self._active = name
        self._stack.setCurrentWidget(self._views[name])
        self._views[name].on_activate()

    def switch_device(self, serial: str) -> None:
        """Set the active device and navigate to the device view."""
        AppContext.get().active_device = serial
        self.switch_to(ViewName.DEVICE)

    def dispatch(self, event: AppEvent) -> None:
        """Route a drained AppEvent to connection-state handling or the active view."""
        if isinstance(event, ServerDisconnectedEvent):
            if self._active != ViewName.CONNECTING:
                self._last_view = self._active
            self.switch_to(ViewName.CONNECTING)
            return
        if isinstance(event, ServerConnectedEvent):
            self.switch_to(self._last_view or ViewName.DASHBOARD)
            self._last_view = None
            return
        if self._active is not None:
            self._views[self._active].handle_event(event)

    def restart(self) -> None:
        """Stop the connection manager, reset shared state, and re-run the startup sequence."""
        self._connection_manager.stop()
        AppContext.reset()
        AppContext.get().window = self
        self._last_view = None
        self.switch_to(ViewName.CONNECTING)
        self._connection_manager.start()

    def closeEvent(self, event: Any) -> None:  # pylint: disable=invalid-name
        """Stop the connection manager's worker thread before the window closes."""
        self._connection_manager.stop()
        super().closeEvent(event)

    def check_initial_view(self) -> None:
        """Land on DashboardView if already connected, otherwise wait briefly and recheck.

        Calls show() once the initial view is active, never before — avoids a blank frame.
        """
        if self._connection_manager.connected:
            self.switch_to(ViewName.DASHBOARD)
            self.show()
        else:
            QTimer.singleShot(_INITIAL_VIEW_RECHECK_MS, self._apply_initial_view)

    def _apply_initial_view(self) -> None:
        if self._connection_manager.connected:
            self.switch_to(ViewName.DASHBOARD)
        else:
            self.switch_to(ViewName.CONNECTING)
        self.show()

    def _drain_events(self) -> None:
        for event in EventHub.get().drain():
            self.dispatch(event)

    def _register_all_views(self) -> None:
        self.register_view(ViewName.CONNECTING, ConnectingView())
        self.register_view(ViewName.DASHBOARD, DashboardView())
        self.register_view(ViewName.DEVICE, DeviceView())
        self.register_view(ViewName.SETTINGS, SettingsView())
        self.register_view(ViewName.ERROR, ErrorView())

    def _build_ui(self) -> None:
        self.setWindowTitle("Decker")
        self.setStyleSheet("background-color: #1e1e2e;")
        self.resize(320, 240)
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setCentralWidget(self._stack)
