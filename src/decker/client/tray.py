"""System tray icon and menu for the Decker client."""

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMainWindow, QMenu, QSystemTrayIcon

from decker.client.assets import ICON_PATH


class TrayIcon(QSystemTrayIcon):
    """Tray icon mirroring the app icon, with a Show/Hide toggle and Exit."""

    def __init__(self, window: QMainWindow) -> None:
        super().__init__(QIcon(str(ICON_PATH)) if ICON_PATH.exists() else QIcon())
        self._window = window
        self.setToolTip("Decker")

        self._menu = QMenu()
        toggle_action = self._menu.addAction("Hide", self._toggle_window_visibility)
        assert toggle_action is not None
        self._toggle_action = toggle_action
        self._menu.addAction("Exit", self._exit_app)
        self.setContextMenu(self._menu)

        self._menu.aboutToShow.connect(self._update_toggle_label)
        self.activated.connect(self._on_activated)

    def _update_toggle_label(self) -> None:
        self._toggle_action.setText("Hide" if self._window.isVisible() else "Show")

    def _toggle_window_visibility(self) -> None:
        if self._window.isVisible():
            self._window.hide()
        else:
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_window_visibility()

    def _exit_app(self) -> None:
        QApplication.quit()
