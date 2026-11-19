"""Editor for one app rule: name, match conditions and the profile/page it activates."""

from collections.abc import Callable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from decker.common.model import AppRule, MatchCondition, PageInfo, ProfileInfo
from decker.common.window_match import validate_condition

FIELD_NAMES: dict[str, str] = {
    "window_class": "Window class",
    "window_type": "Window type",
    "title": "Title",
    "executable": "Executable",
    "desktop_file": "Desktop file",
}
OP_NAMES: dict[str, str] = {
    "equals": "is",
    "contains": "contains",
    "not_contains": "does not contain",
    "regex": "matches regex",
}
_PROFILE_DEFAULT = "Profile default"
_NEW_CONDITION = MatchCondition("window_class", "equals", "")


def _combo(names: dict[str, str]) -> QComboBox:
    combo = QComboBox()
    for key, name in names.items():
        combo.addItem(name, key)
    return combo


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)


class ConditionRow(QWidget):
    """One field / operator / value row with a remove button."""

    changed = pyqtSignal()

    def __init__(self, condition: MatchCondition, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.field = _combo(FIELD_NAMES)
        self.op = _combo(OP_NAMES)
        self.value = QLineEdit(condition.value)
        self.remove = QPushButton("Remove")
        self.field.setCurrentIndex(max(self.field.findData(condition.field), 0))
        self.op.setCurrentIndex(max(self.op.findData(condition.op), 0))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.field)
        layout.addWidget(self.op)
        layout.addWidget(self.value, 1)
        layout.addWidget(self.remove)
        self.field.activated.connect(lambda _i: self.changed.emit())
        self.op.activated.connect(lambda _i: self.changed.emit())
        self.value.editingFinished.connect(self.changed.emit)

    def condition(self) -> MatchCondition:
        """The condition as currently entered."""
        return MatchCondition(str(self.field.currentData()), str(self.op.currentData()), self.value.text())

    def mark_invalid(self, invalid: bool) -> None:
        """Flag the value box as holding an invalid condition."""
        self.value.setProperty("invalid", invalid)
        _repolish(self.value)


class RuleEditor(QWidget):  # pylint: disable=too-many-instance-attributes
    """Edits one rule; ``changed`` fires after a valid user edit (invalid ones show ``error()`` instead)."""

    changed = pyqtSignal()

    def __init__(self, pages_for_profile: Callable[[int], list[PageInfo]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pages_for_profile = pages_for_profile
        self._rule_id = ""
        self._enabled = True
        self._unsupported: set[str] = set()
        self._loading = False
        self._rows: list[ConditionRow] = []
        self._name = QLineEdit()
        self._rows_layout = QVBoxLayout()
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._add_condition_button = QPushButton("Add condition")
        self._profile = QComboBox()
        self._page = QComboBox()
        self._warning = QLabel()
        self._warning.setProperty("role", "error")
        self._warning.setWordWrap(True)
        self._warning.hide()
        self._error = QLabel()
        self._error.setProperty("role", "error")
        self._error.setWordWrap(True)
        self._error.hide()
        self._build_layout()
        self._name.editingFinished.connect(self._on_edited)
        self._add_condition_button.clicked.connect(self._on_add_condition)
        self._profile.activated.connect(self._on_profile_chosen)
        self._page.activated.connect(lambda _i: self._on_edited())

    def _build_layout(self) -> None:
        form = QFormLayout()
        form.addRow("Name", self._name)
        conditions = QVBoxLayout()
        conditions.addLayout(self._rows_layout)
        conditions.addWidget(self._add_condition_button)
        form.addRow("When", conditions)
        form.addRow("Profile", self._profile)
        form.addRow("Page", self._page)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(form)
        layout.addWidget(self._warning)
        layout.addWidget(self._error)

    def set_profiles(self, profiles: list[ProfileInfo]) -> None:
        """Offer these profiles as targets, keeping the chosen target when it still exists."""
        profile_id, page_id = self._target()
        self._loading = True
        self._profile.clear()
        for profile in profiles:
            self._profile.addItem(profile.name, profile.profile_id)
        self._set_target(profile_id, page_id)
        self._loading = False

    def set_rule(self, rule: AppRule) -> None:
        """Show a rule without emitting ``changed``."""
        self._loading = True
        self._rule_id, self._enabled = rule.rule_id, rule.enabled
        self._name.setText(rule.name)
        self._clear_rows()
        for condition in rule.conditions:
            self._append_row(condition)
        self._set_target(rule.profile_id, rule.page_id)
        self._loading = False
        self._refresh_flags()

    def rule(self) -> AppRule:
        """The rule as currently entered."""
        profile_id, page_id = self._target()
        return AppRule(
            self._rule_id,
            self._name.text().strip(),
            self._enabled,
            [r.condition() for r in self._rows],
            profile_id,
            page_id,
        )

    def error(self) -> str:
        """The first validation problem in the entered conditions, or an empty string."""
        for row in self._rows:
            problem = validate_condition(row.condition())
            if problem:
                return problem
        return ""

    def set_unsupported_fields(self, fields: set[str]) -> None:
        """Flag conditions on these fields: the active detection backend does not supply them."""
        self._unsupported = set(fields)
        self._refresh_flags()

    def _target(self) -> tuple[int, str]:
        profile_id = self._profile.currentData()
        page_id = self._page.currentData()
        return (profile_id if isinstance(profile_id, int) else 0), (page_id if isinstance(page_id, str) else "")

    def _set_target(self, profile_id: int, page_id: str) -> None:
        self._profile.setCurrentIndex(max(self._profile.findData(profile_id), 0))
        self._fill_pages(page_id)

    def _fill_pages(self, page_id: str) -> None:
        profile_id = self._profile.currentData()
        pages = self._pages_for_profile(profile_id) if isinstance(profile_id, int) else []
        self._page.clear()
        self._page.addItem(_PROFILE_DEFAULT, "")
        for page in pages:
            self._page.addItem(page.name, page.page_id)
        self._page.setCurrentIndex(max(self._page.findData(page_id), 0))

    def _clear_rows(self) -> None:
        for row in self._rows:
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows = []

    def _append_row(self, condition: MatchCondition) -> None:
        row = ConditionRow(condition)
        row.changed.connect(self._on_edited)
        row.remove.clicked.connect(lambda: self._remove_row(row))
        self._rows.append(row)
        self._rows_layout.addWidget(row)

    def _remove_row(self, row: ConditionRow) -> None:
        self._rows.remove(row)
        self._rows_layout.removeWidget(row)
        row.deleteLater()
        self._on_edited()

    def _on_add_condition(self) -> None:
        self._append_row(_NEW_CONDITION)
        self._on_edited()

    def _on_profile_chosen(self, _index: int) -> None:
        self._fill_pages("")
        self._on_edited()

    def _on_edited(self) -> None:
        if self._loading:
            return
        self._refresh_flags()
        if not self.error():
            self.changed.emit()

    def _refresh_flags(self) -> None:
        problem = self.error()
        self._error.setText(problem)
        self._error.setVisible(bool(problem))
        used: list[str] = []
        for row in self._rows:
            field = str(row.field.currentData())
            missing = field in self._unsupported
            row.mark_invalid(bool(validate_condition(row.condition())))
            row.field.setToolTip(
                "This field is not supplied by the detection backend on this system" if missing else ""
            )
            if missing and field not in used:
                used.append(field)
        names = ", ".join(FIELD_NAMES[f] for f in used)
        self._warning.setText(f"Not supplied by the detection backend on this system: {names}. This rule cannot match.")
        self._warning.setVisible(bool(used))
