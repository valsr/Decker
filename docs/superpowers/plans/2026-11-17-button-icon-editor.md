# Button icon and key editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Per-key icon override, a live key preview, a reworked editor panel with dirty-aware Save, and a highlighted selected key.

**Architecture:** The icon override is a new `icon` appearance field composed by `PluginManager._compose`. A `key_preview` RPC composes drafts server-side. The client panel becomes a preview + rows layout that tracks dirty state and debounces preview calls.

**Tech Stack:** Python 3.12, PyQt6 (offscreen tests), pytest + assertpy, Pillow compose path.

**Spec:** `docs/superpowers/specs/2026-11-17-button-icon-editor-design.md`

## Global Constraints

- Gates before done: `poetry run poe format`, `poe mypy`, `poe pylint` (≥ 9.0), `poe test` (coverage ≥ 85%).
- Methods < 50 lines, ≤ 5 args (existing pylint disables allowed where already used), all code annotated.
- Plugin-set images (`set_image`) always beat the override; no DB migration; keys stay addressed by device + page + index.
- Keep `docs/plugins/` and `CLAUDE.md` in sync if behaviour they describe changes.

## Review Focus

- Override ref pointing at an uninstalled pack: key falls back to the manifest icon, no crash.
- Plugin `set_image` / `set_image(icon=...)` after an override is set still wins.
- `key_preview` on an unassigned key, a non-live key, or invalid JSON returns `""`, persists nothing, and does not touch hardware.
- Server echo of a save (identical values) must not leave Save highlighted; loading a different key must clear it.
- Selection outline cleared on placeholder, page switch and device switch.

---

### Task 1: Icon override in appearance and compose

**Files:**
- Modify: `src/decker/common/appearance_schema.py`, `src/decker/server/plugins.py` (`_compose`)
- Test: `tests/server/test_appearance.py`, `tests/server/test_plugins.py`

**Interfaces:**
- Produces: stored appearance may contain `"icon": {"ref": "pack:<id>/<path>", "color": "#rrggbb[aa]"}`; `resolve_appearance` always yields an `icon` dict (default `{"ref": "", "color": "#ffffff"}`).

- [ ] **Step 1: Failing tests.** `test_appearance`: `resolve_appearance({}, {})["icon"] == {"ref": "", "color": "#ffffff"}` and a stored icon survives; `"icon" in APPEARANCE_KEYS`. `test_plugins` (mirror the existing compose/appearance tests there): a static-icon action with `icon` override composes an image that differs from the no-override one; with a plugin `set_image` the result equals the no-override composition; an override ref to a missing pack equals the no-override composition.
- [ ] **Step 2:** Run `poetry run pytest tests/server/test_appearance.py tests/server/test_plugins.py -q`. Expected: new tests FAIL.
- [ ] **Step 3: Implement.** Add the `icon` entry to `APPEARANCE_SCHEMA`. In `_compose`, read `override = resolve_appearance(spec.appearance, stored).get("icon")`; when `image is None` after the plugin image and plugin icon ref are applied and the override ref is non-empty, set `image = self.icon_packs.read_ref(ref)`, `image_color = override color`, and use `PACK_ICON_SCALE` (only if the read succeeded) — before the `state.image` fallback.
- [ ] **Step 4:** Same pytest command. Expected: PASS. Run the whole suite `poetry run poe test`; fix any panel/schema test broken by the new field.
- [ ] **Step 5: Commit** `feat: per-key icon override replaces the action's default icon`.

### Task 2: `key_preview` RPC

**Files:**
- Modify: `src/decker/server/plugins.py`, `src/decker/server/service.py`; `src/decker/client/` nothing yet.
- Test: `tests/server/test_plugins.py`, `tests/server/test_service.py`

**Interfaces:**
- Produces: `PluginManager.preview_image(target: ActionTarget, stored: dict[str, Any]) -> bytes | None` (None when not live); `DeckerService.key_preview(device_id: str, page_id: str, key_index: int, appearance_json: str) -> str` (`@exposed`, base64 PNG or `""`).

- [ ] **Step 1: Failing tests.** `preview_image` returns PNG bytes for a live key and None otherwise; it does not change `live.appearance`, call the sink, or notify; with a draft title/background the bytes differ from the saved composition. Service: assigned live key → non-empty base64 that decodes to a PNG; unassigned key, inactive page, non-dict or malformed JSON → `""`; nothing persisted (`key_store.get(...).appearance` unchanged).
- [ ] **Step 2:** Run those test files. Expected: FAIL (missing attributes).
- [ ] **Step 3: Implement.** `preview_image` locates the live by `target.context_id`, copies it with `dataclasses.replace(live, appearance=dict(stored))` and returns `self._compose(copy)`. `key_preview` filters keys by `APPEARANCE_KEYS` like `key_update_appearance`, returns `""` on any failure, base64-encodes the bytes.
- [ ] **Step 4:** Tests PASS; full suite green.
- [ ] **Step 5: Commit** `feat: key_preview RPC composes a draft appearance without saving`.

### Task 3: Selected-key outline in the grid

**Files:**
- Modify: `src/decker/client/widgets/button_grid.py`, `src/decker/client/theme.qss`, `src/decker/client/views/dashboard.py`
- Test: `tests/client/widgets/test_button_grid.py`, `tests/client/views/test_dashboard.py`

**Interfaces:**
- Produces: `ButtonGridWidget.set_selected(index: int | None) -> None` sets dynamic property `selected` (bool) on exactly that key and re-polishes it.

- [ ] **Step 1: Failing tests.** `set_selected(2)` → only key 2 has `property("selected") is True`; `set_selected(None)` clears all; rebuilding the grid leaves none selected. Dashboard: editing a key selects it in the grid; showing the placeholder, switching page and switching device clears it (see where `_selected_key = None` at dashboard.py ~259).
- [ ] **Step 2:** Run both files. Expected: FAIL.
- [ ] **Step 3: Implement.** Property + `style().unpolish/polish`; QSS rule `KeyButtonWidget[selected="true"] { border: 2px solid $accent_line; }` (use the existing token naming in `theme.qss`; check the QPushButton border box so the key size is unchanged). Dashboard calls `set_selected` wherever `_selected_key` changes.
- [ ] **Step 4:** Tests PASS; full suite green.
- [ ] **Step 5: Commit** `feat: outline the key being edited`.

### Task 4: `KeyPreview` widget

**Files:**
- Create: `src/decker/client/widgets/key_preview.py`
- Test: `tests/client/widgets/test_key_preview.py`

**Interfaces:**
- Produces: `class KeyPreview(QLabel)` with `set_image(image_b64: str | None) -> None`, signals `set_icon_requested = pyqtSignal()`, `clear_icon_requested = pyqtSignal()`, `set_has_icon(has: bool) -> None` (enables/disables the Clear action). Fixed key-sized square (`72x72` unless the key info is known — keep a constructor `size: int = 72`). Context menu actions "Set icon…" and "Clear icon"; double click emits `set_icon_requested`.

- [ ] **Step 1: Failing tests** (offscreen): setting a PNG shows a non-null pixmap, `None` clears it; double click emits `set_icon_requested`; triggering the menu's "Set icon…" / "Clear icon" actions emit the matching signals (build the menu in a testable `_build_menu() -> QMenu` method); Clear is disabled when `set_has_icon(False)`.
- [ ] **Step 2:** Run. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the widget.
- [ ] **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: key preview widget with icon context menu`.

### Task 5: Reworked `ActionConfigPanel`

**Files:**
- Modify: `src/decker/client/widgets/action_config_panel.py`, `src/decker/client/widgets/schema_form.py` and `icon_edit.py` only if needed for a compact icon row (thumbnail + colour + `[x]`; the Browse button stays reachable via the preview), `src/decker/client/views/dashboard.py`, `src/decker/client/theme.qss`
- Test: `tests/client/widgets/test_action_config_panel.py`, `tests/client/views/test_dashboard.py`

**Interfaces:**
- Consumes: `KeyPreview` (Task 4), `key_preview` RPC (Task 2), `IconEdit`.
- Produces: `ActionConfigPanel.show_action_config(..., title: str = "")` shows `title` as the header; `ActionConfigPanel.set_preview_provider(provider: Callable[[dict[str, Any]], str | None] | None)`; `ActionConfigPanel.set_preview_image(image_b64: str | None)`; read-only `is_dirty -> bool`; the Save button has dynamic property `dirty`.
- Layout: header; `[KeyPreview] | Title row / Icon row + Background row / Save`; then the action settings form.

- [ ] **Step 1: Failing tests.** Header text equals `title`; no key ID anywhere. `is_dirty` is False after load, True after changing the title text, background, icon or any action setting, False again after editing back to the loaded value and after Save; re-sending identical values (server echo) after Save leaves it False; loading a different key (`forget_loaded`) clears it. Save's `dirty` property mirrors `is_dirty`. A change calls the preview provider once after the 150 ms debounce (use `qtbot`/event-loop wait or call the timer's timeout directly) with the draft appearance dict, and the returned base64 reaches the preview; a provider returning `None`/`""` keeps the last image. Preview's Set icon opens the picker path: expose `IconEdit.browse()` publicly and assert the panel invokes it (monkeypatch); Clear icon sets the icon value to empty and marks dirty. Dashboard: `show_action_config` receives the action's name and a provider that calls `key_preview` through the connection manager with the active device/page/index.
- [ ] **Step 2:** Run the two test files. Expected: FAIL.
- [ ] **Step 3: Implement.** Replace the generic appearance form with explicit rows built from `TextStyleEdit`, `IconEdit` and the background `ColorButton` (reuse the existing widgets and their `values()`/`set_value` shapes so `_on_save` keeps producing the same appearance dict, now including `icon`; omit values equal to defaults as before). Dirty = current `(settings, resolved appearance)` != `self._loaded` baseline. Debounce with a single-shot `QTimer(150)` restarted on every `value_changed`. QSS: `QPushButton[dirty="true"]` uses accent background/text tokens.
- [ ] **Step 4:** Tests PASS; full suite green.
- [ ] **Step 5: Commit** `feat: key editor with live preview, icon override and dirty Save`.

### Task 6: Docs and gates

**Files:**
- Modify: `CLAUDE.md` (one sentence: per-key icon override and `key_preview`), `docs/plugins/` page that documents appearance/key images (note the override only replaces static default icons).

- [ ] **Step 1:** Update docs.
- [ ] **Step 2:** `poetry run poe format && poetry run poe mypy && poetry run poe pylint && poetry run poe test`. Expected: all pass, coverage ≥ 85%.
- [ ] **Step 3: Commit** `docs: per-key icon override and key preview`.
