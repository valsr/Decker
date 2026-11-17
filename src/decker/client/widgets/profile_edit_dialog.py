"""Dialog to edit a profile: name, icon, and delete or clone it."""

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from decker.client.widgets.icon_edit import IconEdit
from decker.common.model import ProfileInfo


class ProfileEditDialog(QDialog):  # pylint: disable=too-many-instance-attributes
    """Edit a profile's name and icon; ``outcome`` says how it closed: "save", "delete", "clone" or "" (cancelled)."""

    def __init__(self, profile: ProfileInfo, can_delete: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit profile")
        self.outcome = ""
        self._profile = profile
        self._name = QLineEdit(profile.name)
        self._icon = IconEdit()
        self._icon.set_show_colour(False)
        self._icon.set_value({"ref": profile.icon})
        self._icon.setToolTip("Leave empty to use the Decker icon")
        self._delete_button = QPushButton("Delete…")
        self._delete_button.setEnabled(can_delete)
        self._delete_button.setToolTip("" if can_delete else "A device needs at least one profile")
        self._clone_button = QPushButton("Clone")
        self._save_button = QPushButton("Save")
        self._save_button.setDefault(True)
        cancel_button = QPushButton("Cancel")

        form = QFormLayout()
        form.addRow("Name", self._name)
        form.addRow("Icon", self._icon)
        actions = QHBoxLayout()
        actions.addWidget(self._delete_button)
        actions.addWidget(self._clone_button)
        actions.addStretch()
        buttons = QDialogButtonBox()
        buttons.addButton(self._save_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(actions)
        layout.addWidget(buttons)

        self._save_button.clicked.connect(self._on_save)
        cancel_button.clicked.connect(self.reject)
        self._delete_button.clicked.connect(self._on_delete)
        self._clone_button.clicked.connect(self._on_clone)

    def name(self) -> str:
        """The entered name, trimmed."""
        return self._name.text().strip()

    def icon(self) -> str:
        """The chosen icon ref (empty for the Decker icon)."""
        return str(self._icon.value()["ref"])

    def _on_save(self) -> None:
        if not self.name():
            self._name.setFocus()
            return
        self.outcome = "save"
        self.accept()

    def _on_delete(self) -> None:
        if _confirm_delete_profile(self, self._profile.name):
            self.outcome = "delete"
            self.accept()

    def _on_clone(self) -> None:
        self.outcome = "clone"
        self.accept()


def _confirm_delete_profile(parent: QWidget | None, name: str) -> bool:
    """Ask before deleting a profile: its pages and their keys are deleted with it."""
    answer = QMessageBox.question(
        parent,
        "Delete profile",
        f"Delete profile “{name}”? All of its pages and key assignments will be deleted as well.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    return answer == QMessageBox.StandardButton.Yes
