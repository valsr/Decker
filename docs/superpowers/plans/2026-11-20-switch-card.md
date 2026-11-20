# Switch Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A built-in Switch card whose Display, Press, Double Press and Long Press slots hold cards or actions; a gesture runs the slot's action or swaps the card the key shows.

**Architecture:** The Switch is a headless card in Core (`"behavior": "switch"`). Its `slots` setting (new settings type `slots`) embeds the child cards and actions. A pure `SwitchController` decides what a gesture does and remembers the shown slot in memory; `PluginManager` hosts the shown child as a second `_Live` on the same key. The client gets a `SlotsEdit` field with drop-target faux buttons and a per-slot configuration area.

**Tech Stack:** Python 3.12, PyQt6, RPyC, pytest + assertpy, black (120), mypy, pylint.

**Spec:** `docs/superpowers/specs/2026-11-20-switch-card-design.md`

## Global Constraints

- Quality gates before done: `poe format`, `poe mypy`, `poe pylint` (≥ 9.0), `poe test` (coverage ≥ 85%).
- Annotate everything; methods under 50 lines; max 5 args; docstrings on public items only, one short line.
- Tests use pytest + assertpy, mirror the source layout under `tests/`, prefer real components over mocks.
- Slot names are exactly `display`, `press`, `double_press`, `long_press`. Display holds cards only.
- The shown card is in-memory state only, keyed by the Switch's context id; nothing is written to stored page, key or profile.
- The Switch keeps all gesture handling; the shown child never receives key events. Only gestures with a filled slot are registered.
- No nested Switches in v1. No protocol (stdin/stdout) changes.
- Server and client stay decoupled; the client never talks to hardware.
- Update `docs/plugins/settings-schema.md`, `docs/plugins/package-and-manifest.md`, `CLAUDE.md`, `README.md` in the same change.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- A Switch with every slot empty draws its own face and a key press does nothing and does not raise.
- A slot referencing an uninstalled plugin/card/action does nothing when triggered, shows an empty-looking faux button, and is still in the stored value afterwards.
- The shown slot's card is later removed (plugin uninstalled) or the slot is cleared: the key falls back to Display / Press / own face.
- A Switch pasted or dragged into one of its own slots is rejected.
- `key_copy`/`key_move` of a Switch carries its slots; a copy starts from its own fresh shown state (Display).

---

### Task 1: `slots` value, manifest `behavior`, Core Switch card

**Files:**
- Create: `src/decker/common/slots.py`
- Modify: `src/decker/plugin/settings_schema.py` (add `"slots"` to `FIELD_TYPES`, `_ZERO_VALUES`, `_OBJECT_NORMALIZERS`)
- Modify: `src/decker/plugin/manifest.py` (`CardSpec.switch`, `headless`, `_parse_card`)
- Modify: `src/decker/builtin_plugins/com.decker.core/manifest.json`
- Test: `tests/common/test_slots.py`, `tests/plugin/test_settings_schema.py`, `tests/plugin/test_manifest.py`, `tests/server/test_builtin_plugins.py`

**Interfaces:**
- Produces (`decker.common.slots`):
  - `SLOT_NAMES: tuple[str, ...] = ("display", "press", "double_press", "long_press")`
  - `SWITCH_CARD_ID: str = "com.decker.core.switch"`
  - `normalize_slots(value: Any, default: Any = None) -> dict[str, dict[str, Any] | None]` — always returns all four keys. A slot is kept only if it is `{"kind": "card", "plugin": str, "card": str, "settings": dict, "appearance": dict}` (missing `settings`/`appearance` become `{}`) or `{"kind": "action", "action": str, "settings": dict}`; anything else becomes `None`. `display` with `kind: "action"` becomes `None`. A card slot whose `plugin`/`card` is `SWITCH_CARD_ID`'s plugin/card becomes `None` (no nesting). The signature mirrors the other `normalize_*` functions in `_OBJECT_NORMALIZERS`.
- Produces: `CardSpec.switch: bool` (field, default `False`), `CardSpec.headless` is true for a switch card; manifest card key `"behavior": "switch"` sets it (any other `behavior` value raises `ManifestValidationError`; a switch card may not also be `static` or a preset).

- [ ] **Step 1: Write failing tests** — `test_slots.py`: `test_normalize_slots_fills_all_four_keys`, `test_normalize_slots_drops_malformed_slots`, `test_display_slot_rejects_action`, `test_switch_card_cannot_nest` (assert the four keys are always present and invalid entries are `None`). `test_settings_schema.py`: a field `{"key": "slots", "type": "slots"}` parses and `apply_schema` returns the normalized four-key dict for `{}` input. `test_manifest.py`: `"behavior": "switch"` gives `switch is True` and `headless is True`; `"behavior": "nope"` raises. `test_builtin_plugins.py`: Core lists a card `com.decker.core.switch` with `switch` true.
- [ ] **Step 2: Run** `poe test -- tests/common/test_slots.py tests/plugin tests/server/test_builtin_plugins.py` — expect FAIL (missing module/field).
- [ ] **Step 3: Implement** `normalize_slots` and `SLOT_NAMES`/`SWITCH_CARD_ID` in `decker/common/slots.py`; register `slots` in `settings_schema.py` (zero value is the all-`None` four-key dict, object-normalized like `background`); add `switch` to `CardSpec` and `behavior` parsing in `_parse_card`.
- [ ] **Step 4: Add the card to Core's manifest:** id `com.decker.core.switch`, name "Switch", tooltip "Runs actions or swaps the shown card on press, double press and long press", `"behavior": "switch"`, `"gestures": ["press"]` (placeholder; the real set is computed at runtime), appearance `{ "background": "#000000" }`, one setting `{ "key": "slots", "type": "slots", "label": "Slots" }`.
- [ ] **Step 5: Run** the Step 2 command — expect PASS.
- [ ] **Step 6: Commit** `feat: slots setting type, switch card behaviour and Core Switch card`.

### Task 2: `SwitchController`

**Files:**
- Create: `src/decker/server/switch.py`
- Test: `tests/server/test_switch.py`

**Interfaces:**
- Consumes: `normalize_slots` output (Task 1), `Gesture` from `decker.plugin.gestures`.
- Produces:
  - `@dataclass(frozen=True) class SwitchOutcome: action: tuple[str, dict[str, Any]] | None = None; show: str | None = None` (`show` is the slot name to show; `None` means no change)
  - `class SwitchController:`
    - `gestures(slots: Mapping[str, Any]) -> frozenset[Gesture]` — `PRESS`/`DOUBLE_PRESS`/`LONG_PRESS` for each of `press`/`double_press`/`long_press` that is non-`None`.
    - `shown_slot(context_id: str, slots: Mapping[str, Any]) -> str | None` — the remembered slot if it still holds a card; else `display` if a card; else `press` if a card; else `None`.
    - `handle(context_id: str, slots: Mapping[str, Any], gesture: Gesture) -> SwitchOutcome` — an action slot returns `action=(id, settings)`; a card slot returns `show=<slot name>` and remembers it, unless that card (equal slot value) is already the shown one, then no-op; an empty slot returns an empty outcome.
    - `forget(context_id: str) -> None`

- [ ] **Step 1: Write failing tests**: `test_gestures_follow_filled_slots`; `test_shown_slot_prefers_remembered_then_display_then_press_card`; `test_shown_slot_none_when_press_is_action_and_no_display`; `test_handle_action_returns_action_without_changing_shown`; `test_handle_card_remembers_and_shows`; `test_handle_same_card_is_noop`; `test_remembered_slot_cleared_falls_back_to_display`; `test_forget_resets_to_display`; `test_all_empty_slots_do_nothing`.
- [ ] **Step 2: Run** `poe test -- tests/server/test_switch.py` — expect FAIL.
- [ ] **Step 3: Implement** the controller; state is a `dict[str, str]` of context id → slot name guarded by a `threading.Lock` (gestures arrive on timer threads).
- [ ] **Step 4: Run** — expect PASS.
- [ ] **Step 5: Commit** `feat: SwitchController decides slot gestures and the shown card`.

### Task 3: Hosting the Switch and its shown child in `PluginManager`

**Files:**
- Modify: `src/decker/server/plugins.py` (`_Live.parent`, activation, dispatch, gesture emitter, child routing, deactivation, `preview_image`)
- Modify: `src/decker/server/server_context.py` / wherever `PluginManager` is constructed, only if the `SwitchController` needs wiring (it can be created inside `PluginManager.__init__`)
- Test: `tests/server/test_plugins_switch.py` (follow the fixtures in `tests/server/test_plugins.py`)

**Interfaces:**
- Consumes: Task 1 `CardSpec.switch`, Task 2 `SwitchController`/`SwitchOutcome`.
- Produces:
  - `_Live.parent: str | None = None` — the Switch's context id for a hosted child.
  - Child context id is `f"{switch_context_id}:{slot}"`; child target has the Switch's `device_id`/`key_index` and the slot's plugin/card.
  - `PluginManager` behaviour (no new public methods): activating a switch card creates its `_Live` (gestures from `SwitchController.gestures`, recomputed on settings change) and activates the child for `shown_slot`; the Switch draws its own face when `shown_slot` is `None`.

- [ ] **Step 1: Write failing tests** with a real Core plugin plus a headless static/preset card as child (no process needed): `test_activating_switch_shows_display_card_face`; `test_press_on_card_slot_swaps_child_and_deactivates_old` (old child's context gone from `_live`, new present); `test_press_on_action_slot_runs_action_and_keeps_face` (register a built-in action that records its call); `test_shown_card_survives_deactivate_and_reactivate` (page switch); `test_new_manager_starts_from_display` (restart); `test_child_receives_no_key_events` (a process-less child can't assert this directly — assert `dispatch_key_down` on the Switch never calls `_send_context` for the child); `test_empty_switch_draws_own_face_and_press_is_noop`; `test_uninstalled_slot_card_is_noop_and_stays_stored`; `test_double_press_slot_delays_press_but_press_only_does_not` (gestures registered only for filled slots); `test_child_set_settings_writes_back_into_slot`; `test_deactivating_switch_deactivates_child`; `test_settings_changed_rebuilds_gestures_and_child`.
- [ ] **Step 2: Run** `poe test -- tests/server/test_plugins_switch.py` — expect FAIL.
- [ ] **Step 3: Implement** in `plugins.py`: `activate_card` builds a switch `_Live` and calls a private `_show_child(live: _Live) -> None` that activates/deactivates the child `_Live` (settings and appearance from the slot value, not `settings_store`; reuse the existing recompose/supervisor acquire logic); `_gesture_emitter` for a switch calls `SwitchController.handle`, runs `outcome.action` via `run_action`, and calls `_show_child` for `outcome.show`; `dispatch_key_down/up` feed the Switch's recognizer only; `deactivate_card` also deactivates the child; `_on_set_settings` for a `parent` live updates `parent.settings["slots"][slot]["settings"]` and persists via `store_settings` and `settings_persister` on the parent target; `dispatch_settings_changed` for a switch refreshes gestures and the child. Slots with an uninstalled plugin/card resolve as empty at trigger time but are never rewritten.
- [ ] **Step 4: Check the paths that iterate `self._live`** (`get_key_display_states`, `live_targets`, `_on_ready`, `unregister_cards`, `refresh_page_dependent`, `_refresh_live`) behave for hosted children: `get_key_display_states` must report one entry per key (the Switch's key, not a duplicate for the child); `live_targets` includes children so uninstalling the child's plugin deactivates it, after which the Switch re-resolves its shown slot. Add a test for each of the two behaviours.
- [ ] **Step 5: Run** the Step 2 command and the full `tests/server` — expect PASS.
- [ ] **Step 6: Commit** `feat: Switch card hosts and swaps child cards, runs slot actions`.

### Task 4: Preview and key copy

**Files:**
- Modify: `src/decker/server/plugins.py` (`preview_image` for a switch), `src/decker/server/key_assignments.py` only if copy does not already carry settings verbatim
- Test: `tests/server/test_plugins_switch.py`, `tests/server/test_key_assignments*.py` (the existing file for `key_copy`)

**Interfaces:**
- Consumes: Task 3 behaviour. Produces: `preview_image(target, stored)` for a switch card returns the face of the slot `SwitchController.shown_slot` would pick for a fresh context (Display, else Press-card, else the Switch's own face).

- [ ] **Step 1: Write failing tests**: `test_preview_of_switch_shows_display_card_face`; `test_key_copy_carries_slots_and_starts_at_display` (copy a Switch whose shown slot is Press; the copy's context id has no remembered slot).
- [ ] **Step 2: Run** those tests — expect FAIL.
- [ ] **Step 3: Implement** the preview branch; confirm `key_copy` copies the stored `slots` value (settings JSON) and gets a new context id.
- [ ] **Step 4: Run** `poe test -- tests/server` — expect PASS.
- [ ] **Step 5: Commit** `feat: Switch preview and key copy`.

### Task 5: `SlotsEdit` — faux buttons with drop

**Files:**
- Create: `src/decker/client/widgets/slots_edit.py`
- Modify: `src/decker/client/widgets/schema_form.py` (`_slots_field`, register `"slots"` in `_BUILDERS`)
- Test: `tests/client/widgets/test_slots_edit.py`, `tests/client/widgets/test_schema_form.py`

**Interfaces:**
- Consumes: `normalize_slots`, `SLOT_NAMES` (Task 1); the drag payload `application/x-decker-card` with fields `plugin_uuid`, `card_uuid`, `plugin_name`, `card_name`, `preset_action` (`sidebar.py`).
- Produces:
  - `class SlotsEdit(QWidget)` with `value() -> dict[str, Any]`, `set_value(value: Any) -> None`, signal `changed`, signal `selected_changed(str)` (slot name or `""`), `selected_slot() -> str | None`, `slot_value(name: str) -> dict[str, Any] | None`, `set_slot_value(name: str, value: dict[str, Any] | None) -> None`.
  - Drop rules: a payload with `preset_action` becomes `{"kind": "action", "action": <id>, "settings": {}}`; otherwise `{"kind": "card", "plugin": plugin_uuid, "card": card_uuid, "settings": {}, "appearance": {}}`. Display rejects actions (`dragEnterEvent` ignores them). A payload for the Switch card itself is rejected.
  - Each faux button shows the held item's icon and name (looked up from the client's cards/actions lists, the same source the sidebar uses), an empty state, a clear badge, and a click selects it.

- [ ] **Step 1: Write failing tests** (pytest-qt, follow `test_button_grid.py` for synthesizing drops): `test_drop_card_fills_slot_and_emits_changed`; `test_drop_preset_action_fills_action_slot`; `test_display_rejects_action_drop`; `test_switch_card_drop_rejected`; `test_clear_badge_empties_slot`; `test_click_selects_slot_and_emits_selected_changed`; `test_value_round_trip_through_schema_form`.
- [ ] **Step 2: Run** `poe test -- tests/client/widgets/test_slots_edit.py tests/client/widgets/test_schema_form.py` — expect FAIL.
- [ ] **Step 3: Implement** `SlotsEdit` and hook it into `schema_form._BUILDERS` (a `_slots_field` returning `_Field(edit, edit.value, edit.set_value)` and `_watch` wired to `changed`).
- [ ] **Step 4: Run** the Step 2 command — expect PASS.
- [ ] **Step 5: Commit** `feat: slots field with drop-target faux buttons`.

### Task 6: Per-slot configuration area

**Files:**
- Modify: `src/decker/client/widgets/slots_edit.py` (a configuration area below the faux buttons)
- Modify: `src/decker/client/widgets/schema_form.py` (reuse `SchemaForm`, `AppearanceForm`, `ActionParamsEdit`)
- Test: `tests/client/widgets/test_slots_edit.py`

**Interfaces:**
- Consumes: Task 5 `SlotsEdit` and its `selected_changed` signal; `SchemaForm.set_schema(schema, values)`/`values()` and `AppearanceForm` (same classes `CardConfigPanel` uses); card and action schemas from the client's lists (`settings_schema` is in the card/action listing dicts).
- Produces: selecting a card slot shows that card's settings form and appearance form; selecting an action slot shows the action's settings form; editing writes back through `set_slot_value` and emits `changed`, so the normal card Save persists it. Nothing selected shows nothing.

- [ ] **Step 1: Write failing tests**: `test_selecting_card_slot_shows_its_settings_form`; `test_editing_card_slot_settings_updates_slot_value`; `test_selecting_action_slot_shows_action_settings`; `test_selecting_empty_slot_shows_nothing`; `test_clearing_selected_slot_hides_its_form`.
- [ ] **Step 2: Run** `poe test -- tests/client/widgets/test_slots_edit.py` — expect FAIL.
- [ ] **Step 3: Implement** the configuration area as a private helper widget inside `slots_edit.py`; keep each method under 50 lines.
- [ ] **Step 4: Run** the Step 2 command, then `poe test -- tests/client` — expect PASS.
- [ ] **Step 5: Commit** `feat: configure the selected Switch slot below the faux buttons`.

### Task 7: Docs and quality gates

**Files:**
- Modify: `docs/plugins/settings-schema.md` (`slots` row), `docs/plugins/package-and-manifest.md` (`behavior`), `CLAUDE.md` (Switch in the plugins paragraph), `README.md` (feature list)
- Modify: `/work/decker/admin/todo.user.md` — only if the user asks; do not edit it by default.

- [ ] **Step 1: Update the docs** with the exact slot value shape from Task 1 and the `behavior: "switch"` manifest key, noting the Switch is built-in only in v1.
- [ ] **Step 2: Run** `poe format && poe mypy && poe pylint && poe test` — expect all green, pylint ≥ 9.0, coverage ≥ 85%.
- [ ] **Step 3: Run the app** (`run` skill: `poe server`, `poe client`), place a Switch, fill Display and Press with cards and Long Press with an action, confirm behaviour on a key.
- [ ] **Step 4: Commit** `docs: Switch card in the plugin docs, CLAUDE.md and README`.
