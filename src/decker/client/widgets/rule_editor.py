"""Editor for one app rule: name, match conditions and the profile/page it activates."""

from collections.abc import Callable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from decker.client.widgets.profile_selector import IconProvider, profile_qicon
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
# Fields a detection backend never fills in; unlisted backends are not flagged.
_UNSUPPORTED_FIELDS: dict[str, set[str]] = {"x11": {"desktop_file"}, "windows": {"window_type", "desktop_file"}}
PROFILE_DEFAULT = "Profile default"
MISSING_PAGE = "(missing page)"


def unsupported_fields(backend: str) -> set[str]:
    """The match fields the named detection backend never supplies."""
    return set(_UNSUPPORTED_FIELDS.get(backend, set()))


def _combo(names: dict[str, str]) -> QComboBox:
    combo = QComboBox()
    for key, name in names.items():
        combo.addItem(name, key)
    return combo


def fill_page_combo(combo: QComboBox, pages: list[PageInfo], page_id: str) -> None:
    """List "Profile default" plus pages; a page_id not among them is kept as a "(missing page)" entry."""
    combo.clear()
    combo.addItem(PROFILE_DEFAULT, "")
    for page in pages:
        combo.addItem(page.name, page.page_id)
    if page_id and combo.findData(page_id) < 0:
        combo.addItem(MISSING_PAGE, page_id)
    combo.setCurrentIndex(max(combo.findData(page_id), 0))


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)


class ConditionRow(QWidget):
    """One condition category: operator and value, with an on/off toggle at the end of the row."""

    changed = pyqtSignal()

    def __init__(self, field: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.field_name = field
        self.op = _combo(OP_NAMES)
        self.value = QLineEdit()
        self.toggle = QPushButton("Off")
        self.toggle.setCheckable(True)
        self.toggle.setToolTip(f"Match on the {FIELD_NAMES[field].lower()}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.op)
        layout.addWidget(self.value, 1)
        layout.addWidget(self.toggle)
        self.op.activated.connect(lambda _i: self.changed.emit())
        self.value.editingFinished.connect(self._on_value_edited)
        self.toggle.toggled.connect(self._on_toggled)
        self._sync_toggle()

    @property
    def enabled(self) -> bool:
        """Whether the rule uses this condition."""
        return self.toggle.isChecked()

    def set_condition(self, condition: MatchCondition | None) -> None:
        """Show a condition (on) or an unused row (off, ``is``, empty) without emitting ``changed``."""
        self.blockSignals(True)
        self.toggle.blockSignals(True)
        self.op.setCurrentIndex(max(self.op.findData(condition.op if condition else "equals"), 0))
        self.value.setText(condition.value if condition else "")
        self.toggle.setChecked(condition is not None)
        self.toggle.blockSignals(False)
        self.blockSignals(False)
        self._sync_toggle()

    def condition(self) -> MatchCondition:
        """The condition as currently entered (whether or not it is switched on)."""
        return MatchCondition(self.field_name, str(self.op.currentData()), self.value.text())

    def mark_invalid(self, invalid: bool) -> None:
        """Flag the value box as holding an invalid condition."""
        self.value.setProperty("invalid", invalid)
        _repolish(self.value)

    def _on_toggled(self, _checked: bool) -> None:
        self._sync_toggle()
        self.changed.emit()

    def _on_value_edited(self) -> None:
        if self.enabled:
            self.changed.emit()

    def _sync_toggle(self) -> None:
        self.toggle.setText("On" if self.enabled else "Off")
        self.op.setEnabled(self.enabled)
        self.value.setEnabled(self.enabled)


class RuleEditor(QWidget):  # pylint: disable=too-many-instance-attributes
    """Edits one rule; ``changed`` fires after a valid user edit (invalid ones show ``error()`` instead)."""

    changed = pyqtSignal()
    focus_left = pyqtSignal()  # keyboard focus moved from a field of the editor to something outside it

    def __init__(
        self,
        pages_for_profile: Callable[[int], list[PageInfo]],
        parent: QWidget | None = None,
        icon_for: IconProvider | None = None,
    ) -> None:
        super().__init__(parent)
        self._pages_for_profile = pages_for_profile
        self._icon_for = icon_for
        self._rule_id = ""
        self._enabled = True
        self._unsupported: set[str] = set()
        self._loading = False
        self._rows: dict[str, ConditionRow] = {field: ConditionRow(field) for field in FIELD_NAMES}
        self._extra: list[MatchCondition] = []  # further conditions on a category that has a row; kept as they are
        self._profile_infos: list[ProfileInfo] = []
        self._name = QLineEdit()
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
        for row in self._rows.values():
            row.changed.connect(self._on_edited)
        self._profile.activated.connect(self._on_profile_chosen)
        self._page.activated.connect(lambda _i: self._on_edited())
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.focusChanged.connect(self._on_focus_changed)

    def _build_layout(self) -> None:
        form = QFormLayout()
        form.addRow("Name", self._name)
        for field, row in self._rows.items():
            form.addRow(FIELD_NAMES[field], row)
        self.switch_row = QWidget()  # placed by the owner (the dialog lines it up with the profile's own controls)
        switch = QHBoxLayout(self.switch_row)
        switch.setContentsMargins(0, 0, 0, 0)
        switch.addWidget(QLabel("Switch to"))
        switch.addWidget(self._profile, 1)
        switch.addWidget(self._page, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(form)
        layout.addWidget(self._warning)
        layout.addWidget(self._error)

    def setEnabled(self, a0: bool) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Enable or disable the editor together with its Switch to row."""
        super().setEnabled(a0)
        self.switch_row.setEnabled(a0)

    def set_profiles(self, profiles: list[ProfileInfo]) -> None:
        """Offer these profiles as targets, keeping the chosen target when it still exists."""
        if profiles == self._profile_infos:
            return
        self._profile_infos = list(profiles)
        profile_id, page_id = self._target()
        self._loading = True
        fill_profile_combo(self._profile, profiles, self._icon_for)
        self._set_target(profile_id, page_id)
        self._loading = False

    def set_rule(self, rule: AppRule) -> None:
        """Show a rule without emitting ``changed``."""
        self._loading = True
        self._rule_id, self._enabled = rule.rule_id, rule.enabled
        self._name.setText(rule.name)
        self._extra = []
        taken: set[str] = set()
        for field, row in self._rows.items():
            first = next((c for c in rule.conditions if c.field == field), None)
            row.set_condition(first)
            if first is not None:
                taken.add(field)
        seen: set[str] = set()
        for condition in rule.conditions:
            if condition.field in seen and condition.field in taken:
                self._extra.append(condition)
            seen.add(condition.field)
        self._set_target(rule.profile_id, rule.page_id)
        self._loading = False
        self._refresh_flags()

    def clear(self) -> None:
        """Show no rule: empty fields, every condition off and no complaints (the dialog disables the editor)."""
        self._loading = True
        self._rule_id, self._enabled = "", True
        self._name.setText("")
        self._extra = []
        for row in self._rows.values():
            row.set_condition(None)
        self._loading = False
        self._refresh_flags()

    def set_condition(self, field: str, value: str) -> None:
        """Switch a category on with ``is value`` (the Window Spy's Set) and save the rule."""
        row = self._rows.get(field)
        if row is None:
            return
        row.toggle.blockSignals(True)
        row.toggle.setChecked(True)
        row.toggle.blockSignals(False)
        row.op.setCurrentIndex(max(row.op.findData("equals"), 0))
        row.value.setText(value)
        row._sync_toggle()  # pylint: disable=protected-access
        self._on_edited()

    def rule(self) -> AppRule:
        """The rule as currently entered."""
        profile_id, page_id = self._target()
        conditions = [row.condition() for row in self._rows.values() if row.enabled] + self._extra
        return AppRule(self._rule_id, self._name.text().strip(), self._enabled, conditions, profile_id, page_id)

    def reload_pages(self) -> None:
        """Re-read the page list of the chosen profile, keeping the chosen page."""
        page_id = self._page.currentData()
        self._fill_pages(page_id if isinstance(page_id, str) else "")

    def has_focus(self) -> bool:
        """Whether one of the editor's fields holds the keyboard focus right now."""
        return self._inside(QApplication.focusWidget())

    def _inside(self, widget: QWidget | None) -> bool:
        return widget is not None and (self.isAncestorOf(widget) or self.switch_row.isAncestorOf(widget))

    def _on_focus_changed(self, old: QWidget | None, new: QWidget | None) -> None:
        if self._inside(old) and not self._inside(new):
            self.focus_left.emit()

    def error(self) -> str:
        """The first validation problem (blank name, then switched-on conditions), or an empty string."""
        if not self._name.text().strip():
            return "A name is required"
        for row in self._rows.values():
            problem = validate_condition(row.condition()) if row.enabled else ""
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
        fill_page_combo(self._page, pages, page_id)

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
        idle = not self._rule_id and not self._name.text() and not any(r.enabled for r in self._rows.values())
        problem = "" if idle else self.error()  # an editor showing no rule has nothing to complain about
        self._name.setProperty("invalid", bool(problem) and not self._name.text().strip())
        _repolish(self._name)
        self._error.setText(problem)
        self._error.setVisible(bool(problem))
        used: list[str] = []
        for field, row in self._rows.items():
            missing = row.enabled and field in self._unsupported
            row.mark_invalid(row.enabled and bool(validate_condition(row.condition())))
            row.setToolTip("This field is not supplied by the detection backend on this system" if missing else "")
            if missing:
                used.append(field)
        names = ", ".join(FIELD_NAMES[f] for f in used)
        self._warning.setText(f"Not supplied by the detection backend on this system: {names}. This rule cannot match.")
        self._warning.setVisible(bool(used))


def fill_profile_combo(combo: QComboBox, profiles: list[ProfileInfo], icon_for: IconProvider | None) -> None:
    """List profiles with their icons (the Decker icon when a profile has none)."""
    combo.clear()
    fallback = QIcon()
    for profile in profiles:
        icon = profile_qicon(profile.icon, icon_for, fallback if icon_for is None else None)
        combo.addItem(icon, profile.name, profile.profile_id)
