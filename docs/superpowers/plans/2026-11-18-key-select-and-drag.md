# Key select, play icon and drag-and-drop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking a key selects it for editing, a top-right play-circle icon runs it, and keys can be moved (drag) or copied (Ctrl-drag, green plus-circle badge) within a page.

**Architecture:** Two atomic server RPCs (`key_move`, `key_copy`) over new `KeyAssignmentStore` operations; the client swaps the roles of the key and its hover control and adds drag source/target behaviour to `KeyButtonWidget`, wired through `ButtonGridWidget` to the dashboard.

**Tech Stack:** Python 3.14, SQLite, PyQt6 (offscreen tests), RPyC, pytest + assertpy, poe gates.

**Spec:** `docs/superpowers/specs/2026-11-18-key-select-and-drag-design.md`

## Global Constraints

- Gates after every task: `poe format`, `poe mypy`, `poe pylint` (>= 9.0), `poe test` (coverage >= 85%). Run the task's tests first, the whole suite at task end.
- RPC names/signatures: `key_move(device_id: str, page_id: str, from_index: int, to_index: int) -> bool`, `key_copy(...)` the same. Both return False and change nothing for: no context, unknown page, no source assignment, `from == to`, a non-int or out-of-range index (`0 <= i < device.key_count`), an unopenable device.
- Move keeps the source's `context_id`; copy gets `uuid.uuid4().hex`. Both replace (delete) whatever was on the target. Settings and appearance are carried over unchanged.
- Only the device's active page has live instances: deactivate/activate (and hardware blanking) happen only when `page_id` is the active page; otherwise only rows and cached state change (`device_state_store.delete_key_state`).
- The play-circle control: asset `src/decker/assets/play-circle.svg`, same size/position/visibility rules as the old pencil (30 px button, 21 px drawing, 4 px from the top-right corner, shown on hover or keyboard focus), tooltip "Run this key". `edit.svg` stays in the assets, unused.
- Copy badge: `src/decker/assets/plus-circle.svg` recoloured `#2ecc71`, bottom-left of the key, same recolouring helper as the play icon (`decode_icon`).
- Drag payload mime type `application/x-decker-key`, JSON `{"key_index": <int>}`; the existing `application/x-decker-action` drops are unchanged.
- Commit trailers: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01FG9NRh1jMLQUSqz1T3VCXN`. Explicit-path `git add`. Never push or open PRs without the user's go-ahead.

## Review Focus

- A move/copy while a plugin process is mid-`will_appear` for the source or target: no stale instance stays live at the old index, and the target's old instance is deactivated exactly once.
- Dropping on a key that already holds an action (replace) and dropping on the same key (no-op, no deletion).
- A plain click, or a click with tiny pointer jitter, must select and never start a drag; a drag must not also select/press on release.
- Ctrl pressed or released mid-drag toggles the badge; the badge never stays after leave, drop or a cancelled drag.
- After a failed RPC (false) nothing changes on the client: selection and grid stay as they were.

---

## Task 1: Store operations for move and copy

**Files:**
- Modify: `src/decker/server/key_assignments.py`
- Test: `tests/server/test_key_assignments.py`

**Interfaces:**
- Produces: `KeyAssignmentStore.move(device_id: str, page_id: str, from_index: int, to_index: int) -> bool` (False when the source slot is empty or `from == to`); `KeyAssignmentStore.copy_key(device_id: str, page_id: str, from_index: int, to_index: int, context_id: str) -> KeyAssignment | None` (None when the source is empty or `from == to`). Both delete any row at `to_index` first and are one transaction.

- [ ] **Step 1: Write the failing tests** (class `TestMoveAndCopyKey`, store fixture and `_target` helper as in the file)
  - `test_move_rekeys_the_row_and_keeps_its_context_id`: assign slot 0 (ctx `c0`, settings `{"n": 1}`, appearance set via `update_appearance`), `move("dev1","p1",0,3)` is True; `get(...,3)` has context `c0`, same settings/appearance and `target.key_index == 3`; `get(...,0)` is None.
  - `test_move_replaces_an_occupied_target`: slot 5 occupied by ctx `c5`; after `move(...,0,5)` slot 5 holds `c0` and no row with `c5` remains in `all_for_page`.
  - `test_move_refuses_empty_source_and_same_slot`: both return False and leave rows unchanged.
  - `test_move_is_scoped_to_device_and_page`: same indexes on another device/page are untouched.
  - `test_copy_key_adds_a_row_with_the_new_context_id_and_keeps_the_source`: returns the new `KeyAssignment` (context = the one passed, key_index = target, equal settings/appearance); source row unchanged.
  - `test_copy_key_replaces_an_occupied_target_and_refuses_empty_or_same`.
- [ ] **Step 2: Run** `poetry run pytest tests/server/test_key_assignments.py -q` — Expected: FAIL (missing methods).
- [ ] **Step 3: Implement** both methods in `key_assignments.py` under `self._lock`, using `with self._db:` for the transaction (`DELETE` target; `UPDATE ... SET key_index` for move; `INSERT ... SELECT` with the new context id for copy), reading the row back with `get` for the return value; follow `copy_page`'s style.
- [ ] **Step 4: Run** the file — Expected: PASS; then `poetry run pytest tests/server -q`.
- [ ] **Step 5: Commit** `feat: move and copy a key's assignment in the store`.

## Task 2: `key_move` and `key_copy` RPCs

**Files:**
- Modify: `src/decker/server/devices/manager.py` (`blank_key`), `src/decker/server/service.py`
- Test: `tests/server/test_service.py` (class `TestKeyMoveAndCopy`), `tests/server/test_device_manager.py` (blank_key)

**Interfaces:**
- Consumes: Task 1.
- Produces: `DeviceManager.blank_key(device_id: str, key_index: int) -> None` (clears the slot's cached state via `clear_key_state` and blanks the hardware key with `Device.clear_key_image`; no-op for an unopenable device). `DeckerService.key_move` / `key_copy` as in Global Constraints (both `@exposed`).

- [ ] **Step 1: Write the failing tests.** `blank_key`: with a fake deck (see `tests/server/test_device_drawing.py` / existing manager tests) the key's hardware image is cleared and its state removed; unknown device is a no-op. `TestKeyMoveAndCopy` (service fixture with a real `KeyAssignmentStore`, mocked plugin manager/device manager, `_make_context`; make `device_manager.open_device.return_value.key_count = 15`):
  - `test_move_on_the_active_page_swaps_the_live_instances`: assign slot 0 (ctx `c0`) and slot 4 (ctx `c4`); `key_move(dev, page, 0, 4)` is True; `plugin_manager.deactivate_action` called with the source target and the old target target; `blank_key(dev, 0)` called; `clear_key_state(dev, 4)` called before activation; `activate_action` called with a target whose `context_id == "c0"` and `key_index == 4` and the stored appearance; `store_settings` called with the same target and settings; the store has slot 4 = `c0`, slot 0 empty, `c4` gone.
  - `test_move_on_an_inactive_page_only_changes_rows_and_cached_state`: no plugin calls; `device_state_store.delete_key_state` called for both slots.
  - `test_copy_on_the_active_page_creates_a_new_instance`: source stays live (no deactivate of source); target's old instance deactivated; new `context_id != "c0"`; `activate_action` called with the new target and the source's appearance; settings equal.
  - `test_copy_on_an_inactive_page`; `test_invalid_requests_return_false_and_change_nothing` parametrized over: no context, unknown page, empty source, `from == to`, index `-1`, index `15`, indexes `"1"`, `True`, `None`, `1.5`, device that cannot open (`open_device.return_value = None`).
  - `test_commands_are_listed`: `commands()` contains `key.move`, `key.copy`.
- [ ] **Step 2: Run** the new tests — Expected: FAIL.
- [ ] **Step 3: Implement** `blank_key` in `DeviceManager`, and in `DeckerService` a shared private validator `_slot_move_target(device_id, page_id, from_index, to_index) -> KeyAssignment | None` (type/range/page/source checks) plus the two RPCs following the sequences in the spec's Server section; `key_move` builds the moved target with `dataclasses.replace(assignment.target, key_index=to_index)`; `key_copy` builds `ActionTarget(..., context_id=uuid4().hex, key_index=to_index)`; deactivate/activate only when `_is_active_page`; call `device_manager.open_device(device_id)` before activating like `key_assign`.
- [ ] **Step 4: Run** `poetry run pytest tests/server -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: key_move and key_copy RPCs`.

## Task 3: Click selects, the play-circle icon runs the key

**Files:**
- Modify: `src/decker/client/widgets/button_grid.py`, `src/decker/client/theme.qss` (`QToolButton#keyEditButton` → `QToolButton#keyRunButton`, both rules)
- Test: `tests/client/widgets/test_button_grid.py` (rewrite the pencil tests for the new roles), `tests/client/test_themes.py` if it names the old selector

**Interfaces:**
- Produces (`KeyButtonWidget`): signals `edit_clicked(int)` (emitted by a click on the key and by F2/Menu), `run_clicked(int)` (a click on the play button), `long_pressed(int)` (holding the play button 0.5 s); `_run_button` replaces `_edit_button` (object name `keyRunButton`, tooltip "Run this key", icon from `play-circle.svg`). The key itself no longer starts the long-press timer. `ButtonGridWidget` connects `edit_clicked → key_edit_requested`, `run_clicked → key_pressed`, `long_pressed → key_long_pressed` (grid signal names unchanged, so the dashboard needs no change).

- [ ] **Step 1: Rewrite the failing tests.** Behaviour tests flip: `test_clicking_key_emits_key_edit_requested_only` (no `key_pressed`), `test_clicking_the_play_button_emits_key_pressed_only`, key click emits `edit_clicked` and not `run_clicked`, play press starts the long-press timer and a held press emits `long_pressed` and then no `run_clicked` on release, a key press (mouse on the key) never starts the timer, `test_edit_keys_emit_edit_clicked_and_do_not_press` (F2/Menu) stays, `test_space_selects_the_key` (replaces `test_space_still_presses_the_key`: Space emits `edit_clicked`). Rename the remaining pencil tests (visibility on hover/focus, position, tooltip text "Run this key", drop pass-through, theme/background, glyph fit, svg size/colour/palette follow, fallbacks) to the play button and point the asset checks at `play-circle.svg`; the glyph fallback character becomes "▶".
- [ ] **Step 2: Run** `poetry run pytest tests/client/widgets/test_button_grid.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.** In `button_grid.py` rename `_EDIT_*`/`_edit_*`/pencil identifiers to run/play equivalents; point `_PLAY_ICON` at `assets/play-circle.svg`; the key's `clicked` emits `edit_clicked(index)` (connect in `__init__`); move the long-press timer logic (`mousePressEvent`/`mouseReleaseEvent`/`_on_long_press_fired`) off the key and onto the play button via a small `_RunButton(QToolButton)` subclass that emits `run_clicked`/`long_pressed` with the key index it is given; F2/Menu handling unchanged. Update the QSS selector.
- [ ] **Step 4: Run** `poetry run pytest tests/client -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: clicking a key selects it and the play icon runs it`.

## Task 4: Drag to move, Ctrl-drag to copy, the copy badge, and wiring

**Files:**
- Modify: `src/decker/client/widgets/button_grid.py`, `src/decker/client/views/dashboard.py`
- Test: `tests/client/widgets/test_button_grid.py`, `tests/client/views/test_dashboard.py`

**Interfaces:**
- Consumes: Tasks 2–3.
- Produces: `KeyButtonWidget.set_draggable(draggable: bool) -> None`; signal `key_dropped(int, int, bool)` (`from_index`, `to_index`, `copy`); `ButtonGridWidget.key_moved = pyqtSignal(int, int, bool)` and `ButtonGridWidget.set_draggable_keys(indexes: Collection[int]) -> None` (marks exactly those keys draggable). Badge: a child `QLabel` `_copy_badge` (30 px square, bottom-left, 4 px margin) with the green plus-circle pixmap, shown only while a key drag with Ctrl held is over the key.

- [ ] **Step 1: Write the failing tests.**
  - Drag start: a left-button press then a move beyond `QApplication.startDragDistance()` on a draggable key calls the drag launcher (inject `KeyButtonWidget._start_drag` replacement via a module-level `_exec_drag` function the test monkeypatches) with mime `application/x-decker-key` and payload `{"key_index": index}`; a move shorter than the distance does not; a non-draggable key never starts; after a drag starts, releasing does not emit `edit_clicked` (use `setDown(False)`/ignore the release click: assert no `edit_clicked`); a plain click still emits `edit_clicked`.
  - Drop: `dropEvent` with the key mime emits `key_dropped(from, to, False)`; with `Qt.KeyboardModifier.ControlModifier` set on the event emits `copy=True`; a drop of key N on key N emits nothing; garbage payloads (bad JSON, missing/non-int `key_index`, bool) emit nothing; an `application/x-decker-action` drop still emits `action_dropped`.
  - Badge: `dragEnterEvent`/`dragMoveEvent` with Ctrl shows it, without Ctrl hides it, `dragLeaveEvent` and drop hide it; the badge pixmap is non-null and its dominant colour is green (sample a pixel).
  - `ButtonGridWidget.set_draggable_keys({1, 2})` makes exactly those draggable; `key_dropped` is forwarded as `key_moved`.
  - Dashboard (`TestKeyMoveAndCopy` in `test_dashboard.py`, `_active_dev1` and a mocked connection manager as in `TestPages`): `view._grid.key_moved.emit(0, 3, False)` calls `cm.call("key_move", "dev1", <active page id>, 0, 3)`; with `True` calls `key_copy`; on a True result the target key becomes `_selected_key` and `request_device_refresh` is called; on False or None the selection and slots are untouched and no refresh is requested; without a device, page or connection nothing is called. `_key_slots` changes mark the right keys draggable (assigned keys only) after a refresh.
- [ ] **Step 2: Run** the new tests — Expected: FAIL.
- [ ] **Step 3: Implement** in `button_grid.py`: `_exec_drag(drag)` module function wrapping `QDrag.exec(CopyAction | MoveAction, MoveAction)`; in `KeyButtonWidget` record the press position, start the drag from `mouseMoveEvent` past the drag distance (build the `QDrag`, `QMimeData` with the key payload, the key's pixmap via `self.grab()`), suppress the following click, accept key-mime drags in `dragEnterEvent`/`dragMoveEvent` (compute copy from `event.keyboardModifiers()`), handle them in `dropEvent` as specified, and maintain `_copy_badge` (create lazily with `decode_icon(raw, "#2ecc71")` scaled to 21 px inside a 30 px label, `setAttribute(WA_TransparentForMouseEvents)`). `ButtonGridWidget` forwards `key_dropped` and implements `set_draggable_keys` (called after `build`; remembers the set across rebuilds). In `dashboard.py` connect `self._grid.key_moved` to `_on_key_moved(from_index, to_index, copy)`, which calls the RPC via the same device/page/connection guards as `_page_call`, then on success `_on_key_edit_requested(to_index)` and `cm.request_device_refresh()`; call `self._grid.set_draggable_keys(self._key_slots.keys())` wherever `_key_slots` is rebuilt (display-state updates and `_reset_key_selection`).
- [ ] **Step 4: Run** `poetry run pytest tests/client -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: drag keys to move them and Ctrl-drag to copy`.

## Task 5: Docs and whole-suite gates

**Files:**
- Modify: `CLAUDE.md` (mention the `key_move`/`key_copy` RPCs where RPCs are described and that clicking a key selects it while the play icon runs it), any doc listing RPCs (`grep -rn "key_unassign" docs CLAUDE.md`).
- [ ] **Step 1:** Update the docs. **Step 2:** `poe format`, `poe mypy`, `poe pylint`, `poe test` — Expected: all green, coverage >= 85%. **Step 3: Commit** `docs: key select, play icon and key move/copy`.
