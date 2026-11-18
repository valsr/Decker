"""Import dialog: previews how a local image will look as a key icon and imports it into the User icon pack."""

import base64
import binascii
import json
from pathlib import Path
from typing import Any, Protocol

from PyQt6.QtCore import QByteArray, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_PREVIEW_SIZE = 144
_PREVIEW_DELAY_MS = 200
_FITS = {"Center": "center", "Stretch": "stretch"}
_INTERPOLATIONS = {"Nearest": "nearest", "Bilinear": "bilinear", "Lanczos": "lanczos"}


class _RpcCaller(Protocol):  # pylint: disable=too-few-public-methods
    def call(self, method: str, *args: Any) -> Any:  # pylint: disable=missing-function-docstring
        ...


class IconImportDialog(QDialog):  # pylint: disable=too-many-instance-attributes
    """Choose an id and resize options for an image file, then import it through the server."""

    imported = pyqtSignal(str)

    def __init__(self, parent: QWidget | None, connection_manager: _RpcCaller, filename: str, data: bytes) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import icon")
        self._cm = connection_manager
        self._filename = filename
        self._data = data
        self._suggestion = ""

        self._id_edit = QLineEdit(self._call_str("icon_import_suggest", Path(filename).stem) or Path(filename).stem)
        self._fit = QComboBox()
        self._fit.addItems(list(_FITS))
        self._interpolation = QComboBox()
        self._interpolation.addItems(list(_INTERPOLATIONS))
        self._preview = QLabel()
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setFixedSize(_PREVIEW_SIZE, _PREVIEW_SIZE)
        self._error = QLabel()
        self._error.setWordWrap(True)
        self._use_suggestion = QPushButton()
        self._use_suggestion.hide()
        self._use_suggestion.clicked.connect(lambda: self._id_edit.setText(self._suggestion))
        self._import_button = QPushButton("Import")
        self._import_button.setDefault(True)
        self._import_button.clicked.connect(self._import)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_DELAY_MS)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self._fit.currentIndexChanged.connect(lambda _i: self._preview_timer.start())
        self._interpolation.currentIndexChanged.connect(lambda _i: self._preview_timer.start())

        form = QFormLayout()
        form.addRow("Id", self._id_edit)
        form.addRow("Fit", self._fit)
        form.addRow("Interpolation", self._interpolation)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._preview, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._error)
        layout.addWidget(self._use_suggestion)
        layout.addWidget(self._import_button)
        if Path(filename).suffix.lower() == ".svg":
            form.setRowVisible(self._fit, False)
            form.setRowVisible(self._interpolation, False)
        self._refresh_preview()

    def _options_json(self) -> str:
        return json.dumps(
            {"fit": _FITS[self._fit.currentText()], "interpolation": _INTERPOLATIONS[self._interpolation.currentText()]}
        )

    def _call_str(self, method: str, *args: Any) -> str:
        try:
            result = self._cm.call(method, *args)
        except Exception:  # pylint: disable=broad-exception-caught
            return ""
        return result if isinstance(result, str) else ""

    def _refresh_preview(self) -> None:
        raw = self._call_str("icon_import_preview", self._filename, self._data, self._options_json())
        pixmap = QPixmap()
        try:
            loaded = bool(raw) and pixmap.loadFromData(QByteArray(base64.b64decode(raw, validate=True)))
        except (binascii.Error, ValueError):
            loaded = False
        if loaded and not pixmap.isNull():
            self._preview.setPixmap(
                pixmap.scaled(
                    _PREVIEW_SIZE,
                    _PREVIEW_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self._preview.setText("No preview")

    def _import(self) -> None:
        try:
            raw = self._cm.call("icon_import", self._id_edit.text(), self._filename, self._data, self._options_json())
            result = json.loads(raw)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._show_error(f"Import failed: {exc}", "")
            return
        if not isinstance(result, dict):
            self._show_error("Import failed.", "")
        elif result.get("ok"):
            self.imported.emit(str(result.get("file", "")))
            self.accept()
        else:
            self._show_error(str(result.get("error") or "Import failed."), str(result.get("suggestion") or ""))

    def _show_error(self, message: str, suggestion: str) -> None:
        self._error.setText(message)
        self._suggestion = suggestion
        self._use_suggestion.setText(f"Use {suggestion}")
        self._use_suggestion.setVisible(bool(suggestion))
