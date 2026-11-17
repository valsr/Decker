# Key Edit Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate selecting a key for editing from pressing it: a hover pencil in the key's top-right corner selects it; clicking the key only performs the action.

**Architecture:** `KeyButtonWidget` owns a child pencil `QToolButton` shown on hover and emits `edit_clicked(index)`. `ButtonGridWidget` re-exposes `key_pressed(int)` (key `clicked`) and `key_edit_requested(int)` (pencil). `DashboardView` splits today's `_on_key_selected` into a press-only and a select-only handler.

**Tech Stack:** Python 3.14, PyQt6, pytest + assertpy, poetry/poe.

**Spec:** `docs/superpowers/specs/2026-11-17-key-edit-button-design.md`

## Global Constraints

- Pencil: child `QToolButton`, 20 px, 4 px from the top-right corner, tooltip `"Edit this key"`, themed icon `document-edit` with a `"✎"` glyph fallback; hidden until the pointer enters the key; shown on every key.
- Clicking the pencil selects the key and never presses it; clicking the key presses it and never changes the selection. Long press and drag-and-drop assignment are unchanged.
- `ButtonGridWidget.key_selected` is removed; new signals `key_pressed = pyqtSignal(int)` and `key_edit_requested = pyqtSignal(int)`.
- Decker conventions: black 120, full annotations, <= 50-line methods, <= 5 args, mypy, pylint >= 9.0 (pre-existing warnings stay), coverage >= 85%; run `poe format` first. Branch `feat/key-edit-button` from `main`.
- Never push or open a PR without asking.

## Review Focus

- The pointer moving from the key onto the pencil (and back) must not hide or flicker the pencil; it hides only when the pointer is outside both. (Task 1)
- A press on the pencil must not start the key's long-press timer or emit `clicked`/`long_pressed`; holding the pencil must not fire a long press. (Task 1)
- Dropping an action onto the pencil's area still assigns the action to that key. (Task 1)
- `build()` rebuilding the grid while a key is hovered leaves no stale pencil and does not crash. (Task 2)
- A long press on the key body still performs the long-press action and does not select the key. (Task 2)

---

### Task 1: Pencil on `KeyButtonWidget`

**Files:**
- Modify: `src/decker/client/widgets/button_grid.py` (`KeyButtonWidget`)
- Test: `tests/client/widgets/test_button_grid.py`

**Interfaces:**
- Produces on `KeyButtonWidget`: `edit_clicked = pyqtSignal(int)` (the key index); private `_edit_button: QToolButton` (child, hidden initially, objectName `"keyEditButton"`); `enterEvent`/`leaveEvent` overrides that show/hide it; the pencil is repositioned in `resizeEvent`/construction to the top-right corner. It stays visible while `self.underMouse()` is true (a child under the pointer counts), so moving onto the pencil does not hide it.

- [ ] **Step 1: Branch** `git switch -c feat/key-edit-button main` (design doc `docs/superpowers/specs/2026-11-17-key-edit-button-design.md` and this plan are committed first: `git add docs/superpowers/specs/2026-11-17-key-edit-button-design.md docs/superpowers/plans/2026-11-17-key-edit-button.md && git commit -m "docs: key edit button design and plan"`).
- [ ] **Step 2: Failing tests** in `TestKeyButtonWidget`: `test_pencil_is_hidden_until_the_pointer_enters`, `test_pencil_shows_on_enter_and_hides_on_leave` (call `enterEvent(QEnterEvent(...))`/`leaveEvent(QEvent(QEvent.Type.Leave))` or post real events with `QTest`), `test_pencil_sits_in_the_top_right_corner` (after `show()`: its geometry's right edge is 4 px inside the key's right edge and its top is 4 px from the top; size 20x20), `test_pencil_has_tooltip_and_an_icon_or_glyph`, `test_pencil_click_emits_edit_clicked_with_the_index_and_not_clicked` (`button = KeyButtonWidget(7, key)`; connect to `edit_clicked` and `clicked`; `_edit_button.click()` → `[7]` and no `clicked`), `test_key_click_emits_clicked_and_not_edit_clicked`, `test_pencil_press_does_not_start_the_long_press_timer` (mouse press on the pencil via `QTest.mousePress` leaves `_long_press_timer.isActive()` false and emits no `long_pressed`), `test_pencil_stays_visible_while_the_pointer_is_over_it` (simulate enter on the key, then enter on the pencil and leave on the key: `isVisible()` still true; fully leaving hides it), `test_drop_onto_the_pencil_area_still_emits_action_dropped` (send a `QDropEvent`/call `dropEvent` path through the key with the pencil under the point; the key emits `action_dropped(index, data)`).
- [ ] **Step 3: Run** `poetry run pytest tests/client/widgets/test_button_grid.py -q` — Expected: FAIL.
- [ ] **Step 4: Implement** in `KeyButtonWidget.__init__` (build the pencil in a private `_build_edit_button() -> QToolButton` helper) plus `enterEvent`, `leaveEvent`, `resizeEvent`. `leaveEvent` hides the pencil only when `not self.underMouse()`. The pencil's `clicked` emits `edit_clicked(self.index)`. Give the pencil `setFocusPolicy(Qt.FocusPolicy.NoFocus)` so it never steals key focus; `setAutoRaise(True)`.
- [ ] **Step 5: Run** the same command — Expected: PASS.
- [ ] **Step 6: Commit** `feat(client): hover edit pencil on key buttons`.

### Task 2: Grid signals and dashboard handlers

**Files:**
- Modify: `src/decker/client/widgets/button_grid.py` (`ButtonGridWidget.build`, signals), `src/decker/client/views/dashboard.py` (`_on_key_selected` → split)
- Modify tests: `tests/client/widgets/test_button_grid.py`, `tests/client/views/test_dashboard.py` (cases at the former `_on_key_selected` call sites)
- Test: same files

**Interfaces:**
- Consumes: `KeyButtonWidget.edit_clicked` (Task 1).
- Produces:
  - `ButtonGridWidget.key_pressed = pyqtSignal(int)` (from each key's `clicked`) and `key_edit_requested = pyqtSignal(int)` (from each pencil); `key_selected` removed.
  - `DashboardView._on_key_pressed(self, index: int) -> None` — only `key_simulate_press` (when the key has a slot and a connection exists).
  - `DashboardView._on_key_edit_requested(self, index: int) -> None` — today's selection logic (`forget_loaded` when the index changed, set `_selected_key`, `_refresh_config_panel()`), without any press.

- [ ] **Step 1: Failing tests** — grid: replace `test_clicking_key_emits_key_selected` with `test_clicking_key_emits_key_pressed_only` and add `test_clicking_the_pencil_emits_key_edit_requested_only`, `test_rebuilding_while_hovered_leaves_no_stale_pencil` (hover key 2, `build()` again with 4 keys: the new buttons' pencils are all hidden and the old widget is gone/deleted, no exception), `test_every_key_gets_a_pencil`. Dashboard: `test_pencil_selects_the_key_without_pressing` (`_on_key_edit_requested(3)` → config panel refreshed for 3, `cm.call` not called with `key_simulate_press`), `test_key_press_does_not_change_the_selection` (`_on_key_pressed(3)` → `key_simulate_press` called once with `("dev1", 3)` and `_selected_key` unchanged), `test_press_on_a_key_without_a_slot_calls_nothing`, `test_long_press_still_simulates_a_long_press_and_does_not_select` (`_on_key_long_pressed(3)`), `test_selecting_a_different_key_forgets_loaded_edits` (the old `forget_loaded` behaviour on the pencil path). Rename the existing `_on_key_selected` call sites in `test_dashboard.py` to `_on_key_edit_requested` where they test selection, and to `_on_key_pressed` where they assert `key_simulate_press`.
- [ ] **Step 2: Run** `poetry run pytest tests/client/widgets/test_button_grid.py tests/client/views/test_dashboard.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the grid signals/connections (`button.clicked` → `key_pressed`, `button.edit_clicked` → `key_edit_requested`) and the two dashboard handlers; connect them in `DashboardView.__init__` replacing the old `key_selected` connection. Delete `_on_key_selected`.
- [ ] **Step 4: Run** `poetry run pytest tests/client -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(client): the pencil selects a key, clicking the key only presses it`.

### Task 3: Gates and check

**Files:** none new.

- [ ] **Step 1: Run** `poetry run poe format`, `poe mypy`, `poe pylint`, `poe test` (re-run only if a failure is not in a file this plan touched). Expected: mypy clean, pylint no new warnings, coverage >= 85%, all green.
- [ ] **Step 2: Offscreen check** — render the dashboard grid with one key hovered (post an `Enter` event to it) to a PNG, view it, and confirm the pencil sits in the top-right corner of that key only. Report what was and was not observed (a real pointer on the desktop is the user's to try).
- [ ] **Step 3: Commit** any formatting fixes: `chore: format`.
