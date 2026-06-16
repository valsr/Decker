"""Connect view — shown when the client cannot reach the server."""

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from decker.client.assets import APP_VERSION, ICON_PATH
from decker.client.view.base import View

_RETRY_MS = 5_000


def _parse_address(text: str, default_port: int) -> tuple[str, int]:
    """Parse 'host' or 'host:port' into (host, port), falling back to default_port."""
    if ":" in text:
        parts = text.rsplit(":", 1)
        try:
            return parts[0].strip(), int(parts[1].strip())
        except ValueError:
            pass
    return text.strip(), default_port


class ConnectView(View):
    """Displays the server address form and retries the connection automatically every 5 s."""

    connect_requested = pyqtSignal(str, int)

    def __init__(self, host: str, port: int) -> None:
        super().__init__()
        self._default_port = port
        self._error_label = QLabel()
        self._error_label.setStyleSheet("color: #f38ba8;")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        self._address_input = QLineEdit(f"{host}:{port}")
        self._address_input.setStyleSheet(
            "background: #313244; color: #cdd6f4; border: 1px solid #585b70;"
            " border-radius: 6px; padding: 6px 8px; font-size: 13px;"
        )
        self._address_input.setPlaceholderText("localhost:18861")
        self._retry_timer = QTimer(self)
        self._retry_timer.timeout.connect(self._on_retry_tick)
        self.setMinimumWidth(300)
        self._build_ui()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_show(self) -> None:
        if not self._retry_timer.isActive():
            self._retry_timer.start(_RETRY_MS)

    def on_hide(self) -> None:
        self._retry_timer.stop()
        self.clear_error()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_error(self, message: str) -> None:
        """Display an error message above the connect form."""
        self._error_label.setText(message)
        self._error_label.setVisible(True)

    def clear_error(self) -> None:
        """Hide the current error message."""
        self._error_label.setVisible(False)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(10)
        root.addLayout(self._build_header())
        root.addWidget(self._error_label)

        addr_label = QLabel("Server address")
        addr_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        root.addWidget(addr_label)
        root.addWidget(self._address_input)

        root.addWidget(self._build_connect_button())
        root.addStretch()

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(10)
        header.setContentsMargins(0, 0, 0, 4)

        icon_label = QLabel()
        if ICON_PATH.exists():
            icon_label.setPixmap(QIcon(str(ICON_PATH)).pixmap(32, 32))
        header.addWidget(icon_label)

        name_label = QLabel("DECKER")
        name_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #cdd6f4; letter-spacing: 1px;")
        header.addWidget(name_label)

        ver_label = QLabel(f"|  {APP_VERSION}")
        ver_label.setStyleSheet("font-size: 16px; color: #585b70;")
        header.addWidget(ver_label)

        header.addStretch()
        return header

    def _build_connect_button(self) -> QPushButton:
        btn = QPushButton("Connect")
        btn.setStyleSheet(
            "QPushButton { background: #89b4fa; color: #1e1e2e; border-radius: 6px;"
            " padding: 8px; font-weight: bold; font-size: 13px; border: none; }"
            " QPushButton:hover { background: #b4d0fa; }"
            " QPushButton:pressed { background: #6090da; }"
        )
        btn.clicked.connect(self._on_connect_clicked)
        return btn

    def _on_connect_clicked(self) -> None:
        host, port = _parse_address(self._address_input.text(), self._default_port)
        self.connect_requested.emit(host, port)

    def _on_retry_tick(self) -> None:
        host, port = _parse_address(self._address_input.text(), self._default_port)
        self.connect_requested.emit(host, port)
