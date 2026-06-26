"""Main application window — view registry, navigation, and event handler registration."""

from typing import Any

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QLabel, QMainWindow, QStackedWidget

from decker.client.assets import ICON_PATH
from decker.client.connection_manager import ConnectionManager
from decker.client.context import AppContext
from decker.client.events import (
    ActionListUpdatedEvent,
    AppEvent,
    DeviceListUpdatedEvent,
    KeyDisplayStatesUpdatedEvent,
    KeyEvent,
    PluginLoadFailedEvent,
    ServerConnectedEvent,
    ServerDisconnectedEvent,
    ViewActivatedEvent,
    ViewDeactivatedEvent,
)
from decker.client.events.event_manager import EventManager
from decker.client.ui_state_store import UiStateStore
from decker.client.view_name import ViewName
from decker.client.views import (
    BaseView,
    ConnectingView,
    DashboardView,
    DeviceView,
    ErrorView,
    SettingsView,
)
from decker.common.model import DeviceHardwareInfo

_WINDOW_GEOMETRY_KEY = "window_geometry"

_DRAIN_INTERVAL_MS = 16
_INITIAL_VIEW_RECHECK_MS = 50
_TOAST_DURATION_MS = 4000


class MainWindow(QMainWindow):
    """Owns the QStackedWidget of registered views and routes AppEvents from the EventManager."""

    def __init__(self, connection_manager: ConnectionManager, ui_state_store: UiStateStore | None = None) -> None:
        super().__init__()
        self._connection_manager: ConnectionManager = connection_manager
        self._ui_state_store: UiStateStore = ui_state_store or UiStateStore()
        self._geometry_restored: bool = False
        self._views: dict[ViewName, BaseView] = {}
        self._active: ViewName | None = None
        self._last_view: ViewName | None = None

        AppContext.get().window = self
        AppContext.get().connection_manager = connection_manager

        self._stack: QStackedWidget = QStackedWidget()
        self._toast: QLabel = QLabel(self)
        self._register_all_views()
        self._build_ui()
        self._register_event_handlers()

        self._drain_timer: QTimer = QTimer(self)
        self._drain_timer.timeout.connect(EventManager.get().drain_and_dispatch)
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
            outgoing = self._active
            self._views[outgoing].on_deactivate()
            EventManager.get().emit(ViewDeactivatedEvent(outgoing))
        self._active = name
        self._stack.setCurrentWidget(self._views[name])
        self._views[name].on_activate()
        EventManager.get().emit(ViewActivatedEvent(name))

    def switch_device(self, device: DeviceHardwareInfo) -> None:
        """Set the active device and navigate to the device view."""
        AppContext.get().active_device = device
        self.switch_to(ViewName.DEVICE)

    def set_active_device(self, device: DeviceHardwareInfo) -> None:
        """Set the active device without changing the active view."""
        AppContext.get().active_device = device

    def dispatch(self, event: AppEvent) -> None:
        """Route an event through the EventManager. Kept for backward compatibility."""
        EventManager.get().emit(event)

    def restart(self) -> None:
        """Stop the connection manager, reset shared state, and re-run the startup sequence."""
        self._connection_manager.stop()
        AppContext.reset()
        AppContext.get().window = self
        AppContext.get().connection_manager = self._connection_manager
        self._last_view = None
        self.switch_to(ViewName.CONNECTING)
        self._connection_manager.start()

    def closeEvent(self, event: Any) -> None:  # pylint: disable=invalid-name
        """Persist window geometry and view state, then stop the connection manager."""
        self._save_geometry()
        for view in self._views.values():
            view.save_state()
        self._connection_manager.stop()
        super().closeEvent(event)

    def showEvent(self, event: Any) -> None:  # pylint: disable=invalid-name
        """Restore window geometry after the first show — required for Wayland compatibility."""
        super().showEvent(event)
        if not self._geometry_restored:
            self._geometry_restored = True
            self._restore_geometry()

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

    def _save_geometry(self) -> None:
        geometry = self.geometry()
        self._ui_state_store.set(
            _WINDOW_GEOMETRY_KEY,
            {"x": geometry.x(), "y": geometry.y(), "w": geometry.width(), "h": geometry.height()},
        )

    def _restore_geometry(self) -> None:
        saved = self._ui_state_store.get(_WINDOW_GEOMETRY_KEY)
        if saved is None:
            return
        self.setGeometry(saved["x"], saved["y"], saved["w"], saved["h"])

    def _register_event_handlers(self) -> None:
        em = EventManager.get()
        em.subscribe(ServerDisconnectedEvent, self._on_server_disconnected)
        em.subscribe(ServerConnectedEvent, self._on_server_connected)
        em.subscribe(PluginLoadFailedEvent, self._on_plugin_load_failed)
        for event_type in (DeviceListUpdatedEvent, ActionListUpdatedEvent, KeyDisplayStatesUpdatedEvent, KeyEvent):
            em.subscribe(event_type, self._forward_to_active_view)

    def _on_server_disconnected(self, _event: ServerDisconnectedEvent) -> bool:
        if self._active != ViewName.CONNECTING:
            self._last_view = self._active
        self.switch_to(ViewName.CONNECTING)
        return True

    def _on_server_connected(self, _event: ServerConnectedEvent) -> bool:
        self.switch_to(self._last_view or ViewName.DASHBOARD)
        self._last_view = None
        return True

    def _on_plugin_load_failed(self, event: PluginLoadFailedEvent) -> bool:
        self._show_toast(f"Plugin '{event.plugin_uuid}' failed to load: {event.error}")
        return True

    def _forward_to_active_view(self, event: Any) -> bool | None:
        if self._active is not None:
            return self._views[self._active].handle_event(event)
        return None

    def _show_toast(self, message: str) -> None:
        self._toast.setText(message)
        self._toast.adjustSize()
        self._toast.move(12, self.height() - self._toast.height() - 12)
        self._toast.show()
        QTimer.singleShot(_TOAST_DURATION_MS, self._toast.hide)

    def _register_all_views(self) -> None:
        self.register_view(ViewName.CONNECTING, ConnectingView())
        self.register_view(ViewName.DASHBOARD, DashboardView())
        self.register_view(ViewName.DEVICE, DeviceView())
        self.register_view(ViewName.SETTINGS, SettingsView())
        self.register_view(ViewName.ERROR, ErrorView())

    def _build_ui(self) -> None:
        self.setWindowTitle("Decker")
        self.setStyleSheet("background-color: #f2f2f7;")
        self.resize(320, 240)
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setCentralWidget(self._stack)
        self._toast.setStyleSheet("background-color: #e8e8ed; color: #c0392b; padding: 6px 10px; border-radius: 4px;")
        self._toast.hide()
