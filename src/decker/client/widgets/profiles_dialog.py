"""Non-modal "Profiles and rules" dialog: manage a device's profiles and its app-profile switching rules."""

import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any, Protocol

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from decker.client.events import DetectionStatusEvent
from decker.client.widgets.icon_edit import IconEdit
from decker.client.widgets.rule_editor import (
    FIELD_NAMES,
    MISSING_PAGE,
    RuleEditor,
    fill_page_combo,
)
from decker.common.model import (
    AppRule,
    DefaultRule,
    DeviceProfiles,
    DeviceRules,
    MatchCondition,
    PageInfo,
    ProfileInfo,
)

_ID_ROLE = Qt.ItemDataRole.UserRole
_PROFILE_DEFAULT = "profile default"  # lower case: it reads inside the "-> Profile / page" summary
# Fields a detection backend never fills in; unlisted backends are not flagged.
_UNSUPPORTED_FIELDS: dict[str, set[str]] = {"x11": {"desktop_file"}, "windows": {"window_type", "desktop_file"}}


class RulesApi(Protocol):
    """The typed rule RPCs of ConnectionManager that the dialog uses."""

    def app_rule_add(self, device_id: str, rule: AppRule) -> AppRule | None:
        """Add a rule; the stored rule, or None when rejected."""
        ...

    def app_rule_update(self, device_id: str, rule: AppRule) -> bool:
        """Replace a rule."""
        ...

    def app_rule_delete(self, device_id: str, rule_id: str) -> bool:
        """Delete a rule."""
        ...

    def app_rule_move(self, device_id: str, rule_id: str, position: int) -> bool:
        """Move a rule to a priority position."""
        ...

    def app_default_rule_set(self, device_id: str, default_rule: DefaultRule) -> bool:
        """Set the default rule."""
        ...


class ProfilesDialog(QDialog):  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """Profiles on the left, app rules and the fixed default rule on the right; every edit saves immediately."""

    spy_requested = pyqtSignal()

    def __init__(
        self,
        call: Callable[..., Any],
        rules_api: RulesApi,
        pages_for_profile: Callable[[int], list[PageInfo] | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Profiles and rules")
        self.setModal(False)
        self._call = call
        self._api = rules_api
        self._pages_for_profile = pages_for_profile  # None means the lookup failed
        self._known_pages: dict[int, list[PageInfo]] = {}  # last successful lookup per profile
        self._editor_base: AppRule | None = None  # the server rule the editor last synced to
        self._summaries: dict[str, str] = {}  # rule id -> "-> Profile / Page"
        self._device_id = ""
        self._profiles: list[ProfileInfo] = []
        self._rules: DeviceRules | None = None
        self._status: DetectionStatusEvent | None = None
        self._select_profile_id: int | None = None
        self._select_rule_id = ""
        self._build_widgets()
        outer = QVBoxLayout(self)
        panes = QHBoxLayout()
        panes.addLayout(self._build_profile_pane(), 1)
        panes.addLayout(self._build_rules_pane(), 2)
        outer.addLayout(panes, 1)
        outer.addLayout(self._build_status_strip())
        self._connect_signals()
        self.resize(900, 560)

    # ------------------------------------------------------------------ construction

    def _build_widgets(self) -> None:
        self._profile_list = QListWidget()
        self._name_edit = QLineEdit()
        self._icon = IconEdit()
        self._icon.set_show_colour(False)
        self._icon.setToolTip("Leave empty to use the Decker icon")
        self._add_profile_button = QPushButton("+ Add profile")
        self._delete_profile_button = QPushButton("Delete…")
        self._clone_button = QPushButton("Clone")
        self._rule_list = QListWidget()
        self._add_rule_button = QPushButton("+ Add rule")
        self._delete_rule_button = QPushButton("Delete rule")
        self._up_button = QPushButton("Move up")
        self._down_button = QPushButton("Move down")
        self._editor = RuleEditor(self._pages)
        self._editor.setEnabled(False)
        self._default_enable = QCheckBox("When no rule matches")
        self._default_profile = QComboBox()
        self._default_page = QComboBox()
        self._status_label = QLabel()
        self._spy_button = QPushButton("Window Spy")
        self._close_button = QPushButton("Close")

    def _build_profile_pane(self) -> QVBoxLayout:
        form = QFormLayout()
        form.addRow("Name", self._name_edit)
        form.addRow("Icon", self._icon)
        actions = QHBoxLayout()
        actions.addWidget(self._delete_profile_button)
        actions.addWidget(self._clone_button)
        actions.addStretch()
        pane = QVBoxLayout()
        pane.addWidget(QLabel("Profiles"))
        pane.addWidget(self._profile_list, 1)
        pane.addWidget(self._add_profile_button)
        pane.addLayout(form)
        pane.addLayout(actions)
        return pane

    def _build_rules_pane(self) -> QVBoxLayout:
        buttons = QHBoxLayout()
        for button in (self._add_rule_button, self._delete_rule_button, self._up_button, self._down_button):
            buttons.addWidget(button)
        buttons.addStretch()
        default_row = QHBoxLayout()
        default_row.addWidget(self._default_enable)
        default_row.addWidget(QLabel("->"))
        default_row.addWidget(self._default_profile, 1)
        default_row.addWidget(self._default_page, 1)
        pane = QVBoxLayout()
        pane.addWidget(QLabel("Rules (first match wins)"))
        pane.addWidget(self._rule_list, 1)
        pane.addLayout(buttons)
        pane.addLayout(default_row)
        pane.addWidget(self._editor)
        return pane

    def _build_status_strip(self) -> QHBoxLayout:
        strip = QHBoxLayout()
        strip.addWidget(self._status_label, 1)
        strip.addWidget(self._spy_button)
        strip.addWidget(self._close_button)
        return strip

    def _connect_signals(self) -> None:
        self._profile_list.currentRowChanged.connect(self._on_profile_row)
        self._name_edit.editingFinished.connect(self._on_rename)
        self._icon.value_changed.connect(self._on_icon)
        self._add_profile_button.clicked.connect(self._on_add_profile)
        self._delete_profile_button.clicked.connect(self._on_delete_profile)
        self._clone_button.clicked.connect(lambda: self._profile_call("profile_clone"))
        self._rule_list.currentRowChanged.connect(self._on_rule_row)
        self._rule_list.itemChanged.connect(self._on_item_changed)
        self._add_rule_button.clicked.connect(self._on_add_rule)
        self._delete_rule_button.clicked.connect(self._on_delete_rule)
        self._up_button.clicked.connect(lambda: self._move_selected(-1))
        self._down_button.clicked.connect(lambda: self._move_selected(1))
        self._editor.changed.connect(self._on_editor_changed)
        self._editor.focus_left.connect(self._resync_editor)
        self._default_enable.toggled.connect(lambda _on: self._save_default())
        self._default_profile.activated.connect(self._on_default_profile)
        self._default_page.activated.connect(lambda _i: self._save_default())
        self._spy_button.clicked.connect(self.spy_requested.emit)
        self._close_button.clicked.connect(self.close)

    # ------------------------------------------------------------------ feeding from the server

    def set_profiles(self, profiles: DeviceProfiles) -> None:
        """Show the device's profiles, keeping the selected one."""
        keep = self._selected_profile_id()
        self._device_id = profiles.device_id
        self._profiles = list(profiles.profiles)
        self._profile_list.blockSignals(True)
        self._profile_list.clear()
        for profile in self._profiles:
            item = QListWidgetItem(profile.name)
            item.setData(_ID_ROLE, profile.profile_id)
            self._profile_list.addItem(item)
        self._profile_list.blockSignals(False)
        wanted = self._select_profile_id if self._select_profile_id is not None else keep
        self._select_profile_id = None
        self.select_profile(wanted if wanted is not None else profiles.active_profile_id)
        self._delete_profile_button.setEnabled(len(self._profiles) > 1)
        self._render_rules()

    def set_rules(self, rules: DeviceRules) -> None:
        """Show the device's rules and default rule, keeping the selected rule."""
        self._device_id = rules.device_id
        self._rules = rules
        self._render_rules()

    def set_status(self, status: DetectionStatusEvent) -> None:
        """Show the detection state and flag rules that use fields the backend does not supply."""
        self._status = status
        reason = f": {status.reason}" if status.reason else ""
        self._status_label.setText(f"Window detection: {status.state} ({status.backend}){reason}")
        self._editor.set_unsupported_fields(self._unsupported())
        self._refresh_warnings()

    def refresh(self) -> None:
        """Re-read page lists (the server's pages changed) and redraw."""
        if self.isVisible():
            self._render_rules()
            self._editor.reload_pages()

    def showEvent(self, a0: Any) -> None:  # pylint: disable=invalid-name
        """Render the rules once the dialog becomes visible (hidden dialogs skip server lookups)."""
        super().showEvent(a0)
        self._render_rules()
        self._editor.reload_pages()

    def select_profile(self, profile_id: int) -> None:
        """Select a profile in the list."""
        for row in range(self._profile_list.count()):
            item = self._profile_list.item(row)
            if item is not None and item.data(_ID_ROLE) == profile_id:
                self._profile_list.setCurrentRow(row)
                self._on_profile_row(row)
                return
        if self._profile_list.count() and self._profile_list.currentRow() < 0:
            self._profile_list.setCurrentRow(0)
        self._on_profile_row(self._profile_list.currentRow())

    # ------------------------------------------------------------------ profiles

    def _selected_profile_id(self) -> int | None:
        item = self._profile_list.currentItem()
        data = item.data(_ID_ROLE) if item is not None else None
        return data if isinstance(data, int) else None

    def _selected_profile(self) -> ProfileInfo | None:
        profile_id = self._selected_profile_id()
        return next((p for p in self._profiles if p.profile_id == profile_id), None)

    def _on_profile_row(self, _row: int) -> None:
        profile = self._selected_profile()
        for widget in (self._name_edit, self._icon, self._clone_button):
            widget.setEnabled(profile is not None)
        self._name_edit.setText(profile.name if profile else "")
        self._icon.blockSignals(True)
        self._icon.set_value({"ref": profile.icon if profile else ""})
        self._icon.blockSignals(False)

    def _profile_call(self, method: str, *args: Any) -> Any:
        profile_id = self._selected_profile_id()
        return self._call(method, profile_id, *args) if profile_id is not None else None

    def _on_rename(self) -> None:
        profile, name = self._selected_profile(), self._name_edit.text().strip()
        if profile is None or not name or name == profile.name:
            return
        self._profile_call("profile_rename", name)

    def _on_icon(self) -> None:
        profile, ref = self._selected_profile(), str(self._icon.value()["ref"])
        if profile is not None and ref != profile.icon:
            self._profile_call("profile_set_icon", ref)

    def _on_add_profile(self) -> None:
        raw = self._call("profile_add")
        try:
            created = json.loads(raw)["profile_id"] if isinstance(raw, str) else None
        except (ValueError, TypeError, KeyError):
            created = None
        if isinstance(created, int):
            self._select_profile_id = created

    def _on_delete_profile(self) -> None:
        profile = self._selected_profile()
        if profile is not None and _confirm_delete_profile(self, profile.name):
            self._profile_call("profile_delete")

    # ------------------------------------------------------------------ rules

    def _unsupported(self) -> set[str]:
        return set(_UNSUPPORTED_FIELDS.get(self._status.backend, set())) if self._status is not None else set()

    def _pages(self, profile_id: int) -> list[PageInfo]:
        pages = self._pages_for_profile(profile_id)
        if pages is None:
            return self._known_pages.get(profile_id, [])
        self._known_pages[profile_id] = pages
        return pages

    def _selected_rule_id(self) -> str:
        item = self._rule_list.currentItem()
        rule_id = item.data(_ID_ROLE) if item is not None else None
        return rule_id if isinstance(rule_id, str) else ""

    def _selected_rule(self) -> AppRule | None:
        return self._rule_by_id(self._selected_rule_id())

    def _rule_by_id(self, rule_id: str) -> AppRule | None:
        return next((r for r in self._rules.rules if r.rule_id == rule_id), None) if self._rules else None

    def _render_rules(self) -> None:
        if not self.isVisible():
            return
        self._refill_default_profiles()
        self._editor.set_profiles(self._profiles)
        rules = self._rules.rules if self._rules else []
        previous = self._selected_rule_id()
        keep = self._select_rule_id or previous
        self._select_rule_id = ""
        names = {p.profile_id: p.name for p in self._profiles}
        page_names: dict[int, dict[str, str]] = {}
        self._summaries = {r.rule_id: self._summary(r, names, page_names) for r in rules}
        self._rule_list.blockSignals(True)
        self._rule_list.clear()
        for rule in rules:
            self._rule_list.addItem(self._rule_item(rule))
        row = next((i for i, r in enumerate(rules) if r.rule_id == keep), -1)
        self._rule_list.setCurrentRow(row)
        self._rule_list.blockSignals(False)
        selected = self._selected_rule()
        self._update_buttons(row, selected)
        self._sync_editor(selected, same_selection=bool(keep) and keep == previous)
        self._render_default()

    def _summary(self, rule: AppRule, names: dict[int, str], page_names: dict[int, dict[str, str]]) -> str:
        if rule.profile_id not in page_names:
            page_names[rule.profile_id] = {p.page_id: p.name for p in self._pages(rule.profile_id)}
        profile = names.get(rule.profile_id, "(deleted profile)")
        page = page_names[rule.profile_id].get(rule.page_id, MISSING_PAGE) if rule.page_id else _PROFILE_DEFAULT
        return f"-> {profile} / {page}"

    def _rule_item(self, rule: AppRule) -> QListWidgetItem:
        item = QListWidgetItem()
        item.setData(_ID_ROLE, rule.rule_id)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if rule.enabled else Qt.CheckState.Unchecked)
        self._decorate(item, rule)
        return item

    def _decorate(self, item: QListWidgetItem, rule: AppRule) -> None:
        missing = sorted({c.field for c in rule.conditions} & self._unsupported())
        warn = "⚠ " if missing else ""
        summary = self._summaries.get(rule.rule_id, "")
        item.setText(f"{warn}{rule.name}   {summary}")
        fields = ", ".join(FIELD_NAMES[f] for f in missing)
        item.setToolTip(f"Not supplied by the detection backend on this system: {fields}" if missing else "")

    def _refresh_warnings(self) -> None:
        self._rule_list.blockSignals(True)
        for row in range(self._rule_list.count()):
            item = self._rule_list.item(row)
            rule = self._rule_by_id(str(item.data(_ID_ROLE))) if item is not None else None
            if item is not None and rule is not None:
                self._decorate(item, rule)
        self._rule_list.blockSignals(False)

    def _update_buttons(self, row: int, rule: AppRule | None) -> None:
        self._delete_rule_button.setEnabled(rule is not None)
        self._up_button.setEnabled(rule is not None and row > 0)
        self._down_button.setEnabled(rule is not None and row < self._rule_list.count() - 1)

    def _sync_editor(self, rule: AppRule | None, same_selection: bool) -> None:
        self._editor.setEnabled(rule is not None)
        if rule is None:
            return
        # The user's own edit comes back as an update: do not rebuild the editor under their typing.
        echo = self._same_content(rule)
        if not same_selection or not (echo or self._editor.has_focus()):
            self._load_editor(rule)
        elif echo:
            self._editor_base = rule
        self._editor.set_unsupported_fields(self._unsupported())

    def _load_editor(self, rule: AppRule) -> None:
        self._editor.set_rule(rule)
        self._editor_base = rule

    def _same_content(self, rule: AppRule) -> bool:
        return replace(self._editor.rule(), enabled=rule.enabled) == rule

    def _resync_editor(self) -> None:
        """Focus left the editor: show the latest server rule unless the user changed what was loaded."""
        rule, base = self._selected_rule(), self._editor_base
        if rule is None or base is None or rule.rule_id != self._editor.rule().rule_id:
            return
        if not self._same_content(rule) and self._same_content(base):
            self._load_editor(rule)

    def _on_rule_row(self, row: int) -> None:
        rule = self._selected_rule()
        self._update_buttons(row, rule)
        self._sync_editor(rule, same_selection=False)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        rule = self._rule_by_id(str(item.data(_ID_ROLE)))
        enabled = item.checkState() == Qt.CheckState.Checked
        if rule is not None and rule.enabled != enabled:
            self._api.app_rule_update(self._device_id, replace(rule, enabled=enabled))

    def _on_add_rule(self) -> None:
        profile_id = self._selected_profile_id() or 0
        starter = AppRule("", "New rule", True, [MatchCondition("window_class", "equals", "")], profile_id)
        stored = self._api.app_rule_add(self._device_id, starter)
        if stored is not None:
            self._select_rule_id = stored.rule_id

    def _on_delete_rule(self) -> None:
        rule = self._selected_rule()
        if rule is not None:
            self._api.app_rule_delete(self._device_id, rule.rule_id)

    def _move_selected(self, step: int) -> None:
        rule = self._selected_rule()
        if rule is not None:
            self._api.app_rule_move(self._device_id, rule.rule_id, self._rule_list.currentRow() + step)

    def _on_editor_changed(self) -> None:
        rule, item = self._editor.rule(), self._rule_list.currentItem()
        if item is not None:  # the checkbox may have been toggled since the editor loaded the rule
            rule = replace(rule, enabled=item.checkState() == Qt.CheckState.Checked)
        self._api.app_rule_update(self._device_id, rule)

    # ------------------------------------------------------------------ default rule

    def _refill_default_profiles(self) -> None:
        current = self._default_profile.currentData()
        self._default_profile.blockSignals(True)
        self._default_profile.clear()
        for profile in self._profiles:
            self._default_profile.addItem(profile.name, profile.profile_id)
        self._default_profile.setCurrentIndex(max(self._default_profile.findData(current), 0))
        self._default_profile.blockSignals(False)

    def _render_default(self) -> None:
        default = self._rules.default_rule if self._rules else DefaultRule()
        widgets = (self._default_enable, self._default_profile, self._default_page)
        for widget in widgets:
            widget.blockSignals(True)
        self._default_enable.setChecked(default.enabled)
        self._default_profile.setCurrentIndex(max(self._default_profile.findData(default.profile_id), 0))
        self._fill_default_pages(default.page_id)
        for widget in widgets:
            widget.blockSignals(False)

    def _fill_default_pages(self, page_id: str) -> None:
        profile_id = self._default_profile.currentData()
        fill_page_combo(self._default_page, self._pages(profile_id) if isinstance(profile_id, int) else [], page_id)

    def _on_default_profile(self, _index: int) -> None:
        self._fill_default_pages("")
        self._save_default()

    def _save_default(self) -> None:
        profile_id, page_id = self._default_profile.currentData(), self._default_page.currentData()
        default = DefaultRule(
            self._default_enable.isChecked(),
            profile_id if isinstance(profile_id, int) else 0,
            page_id if isinstance(page_id, str) else "",
        )
        self._api.app_default_rule_set(self._device_id, default)


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
