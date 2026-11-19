# Screensaver and brightness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A per-device screensaver (dark, one image, or an image gallery, optionally laid across the key gaps) with idle timeout, instant RPC trigger, swallowed waking key press, and normal/saver brightness, running in the server with no client.

**Architecture:** A server-side overlay (approach A of the spec). `ScreensaverEngine` tracks idle time per device, and on activation takes a write gate in `DeviceManager`, writes composed per-key slices straight to the deck and dims it; waking releases the gate and re-shows the active page. Settings live in SQLite via `ScreensaverStore`; `ScreensaverController` fronts the RPCs and events; the client adds a "Device" section to `SettingsDialog`.

**Tech Stack:** Python 3.14, Pillow (existing `AssetRenderer`), SQLite, RPyC, PyQt6, pytest + assertpy.

**Spec:** `docs/superpowers/specs/2026-11-19-screensaver-design.md`

## Global Constraints

- Black (line length 120) + isort; annotate everything; methods under 50 lines; at most 5 args per function.
- Docstrings only on public classes and functions, one short line; comments only for a non-obvious why.
- Tests mirror the source layout under `tests/`, use `assertpy`, prefer real components over mocks; **never touch real hardware or the live desktop, and never synthesise input**.
- Coverage stays at or above 85%; `poe format`, `poe mypy`, `poe pylint` (at least 9.0) and `poe test` pass.
- Server stays headless; modules stay decoupled from the client; no new dependencies.
- RPCs use `@api_response` (JSON-string results; bool results are JSON `"true"`/`"false"`, parsed on the client with `_call_json`).
- Event/RPC names are exactly: `screensaver_get`, `screensaver_set`, `screensaver_activate`, `screensaver_deactivate`, `screensaver_preview`; events `screensaver_changed`, `screensaver_settings_changed`.
- Settings ranges: `brightness` 1-100; `timeout_minutes` 0-1440; `saver_brightness` 0-100; `key_mm` 5-60; `gap_mm` 0-30; `gallery_minutes` 1-1440; paths at most 1024 chars; image file at most 20 MiB; decoded pixels at most 64 MP. Out-of-range or unknown values are rejected, never clamped.
- Defaults: brightness 100, timeout 0, saver brightness 10, content `none`, scaling `center`, bezel false, key_mm 16.0, gap_mm 4.0, gallery_mode `activation`, gallery_minutes 5.
- Only loopback clients may set or preview with `image_path` or `folder_path` values.
- Update README platform table, `docs/platform-support.md` and `CLAUDE.md` in the same change.

## Review Focus

- A wake press must not reach pages, plugins or clients, and its release must not either (Task 3).
- A plugin or page write that arrives while the screensaver is active must not reach the hardware, and must show after waking (Task 3).
- Waking during rendering must cancel activation before any slice is written (Task 4).
- A missing or corrupt image or empty folder must give a dark screen and `last_error`, never an exception or a stuck gate (Tasks 2, 4).
- Server shutdown while active must restore normal brightness and the page; a crash cannot (Task 4).
- A reconnected device must come back awake at normal brightness (Tasks 3, 4).

---

### Task 1: Settings model, validation, store

**Files:**
- Modify: `src/decker/common/model.py` (add `ScreensaverSettings`)
- Create: `src/decker/server/screensaver/__init__.py`, `settings.py`, `screensaver_store.py`
- Test: `tests/server/screensaver/test_settings.py`, `tests/server/screensaver/test_screensaver_store.py`

**Interfaces:**
- Produces: `ScreensaverSettings` (frozen dataclass; fields exactly as the spec: `brightness, timeout_minutes, saver_brightness, content, image_path, folder_path, scaling, bezel, key_mm, gap_mm, gallery_mode, gallery_minutes`, defaults per Global Constraints, `content`/`scaling`/`gallery_mode` as `Literal`s).
- Produces: `settings_from_json(text: str) -> ScreensaverSettings` and `settings_to_json(s) -> str` in `settings.py`; `settings_from_json` raises `ValueError` with a field-naming message for unknown keys, wrong types or out-of-range values.
- Produces: `ScreensaverStore(Manager)` with `get(device_id) -> ScreensaverSettings` (defaults when no row) and `set(device_id, settings) -> None`; table `screensaver_settings(device_id TEXT PRIMARY KEY, settings_json TEXT NOT NULL)` in `decker.db`, same create/destroy pattern as `AppRuleStore`.

- [ ] **Step 1: Write failing tests:** `test_defaults_match_spec`, `test_rejects_out_of_range` (parametrised over each ranged field, both bounds plus one beyond), `test_rejects_unknown_key_and_wrong_type`, `test_json_round_trip`, `test_store_returns_defaults_then_roundtrips`, `test_store_survives_reopen`.
- [ ] **Step 2:** Run `poetry run pytest tests/server/screensaver -q`; expect failures for missing modules.
- [ ] **Step 3: Implement** the dataclass, the validator and the store (mirror `app_rule_store.py` for connection/lock handling).
- [ ] **Step 4:** Run the tests; expect pass.
- [ ] **Step 5: Commit** `feat: screensaver settings model and store`.

### Task 2: Composition (geometry, scaling, image source)

**Files:**
- Create: `src/decker/server/screensaver/compose.py`, `source.py`
- Test: `tests/server/screensaver/test_compose.py`, `tests/server/screensaver/test_source.py`

**Interfaces:**
- Produces: `canvas_layout(rows: int, cols: int, key_px: int, bezel: bool, key_mm: float, gap_mm: float) -> CanvasLayout` with `width`, `height` and `boxes: list[tuple[int, int, int, int]]` (left, top, right, bottom per key, row-major). With bezel: `gap_px = round(key_px * gap_mm / key_mm)`, key `(r, c)` starts at `(c*(key_px+gap_px), r*(key_px+gap_px))`; without: gap 0.
- Produces: `compose(image: Image.Image, layout: CanvasLayout, scaling: str) -> list[Image.Image]` (one `key_px` x `key_px` image per key). `center` scales preserving aspect ratio to cover the canvas and crops the excess equally; `stretch` resizes to the canvas exactly.
- Produces: `preview_image(image, layout, scaling) -> Image.Image`: the canvas with the gaps painted dark.
- Produces: `load_image(path: str, width: int, height: int) -> Image.Image` using `AssetRenderer` (SVG rasterised at the canvas size); raises `ScreensaverImageError` for missing files, files over 20 MiB, over 64 MP, or undecodable data.
- Produces: `GalleryCursor` with `next_path(folder: str) -> str | None`: image files (`.png .jpg .jpeg .svg`, case-insensitive) sorted by name, rescanned each call, wrapping; unreadable entries are skipped by the caller via `ScreensaverImageError`.

- [ ] **Step 1: Write failing tests:** `test_layout_no_bezel_is_contiguous`; `test_layout_bezel_16_4_on_72px` (gap_px 18, canvas width for 5 cols = 5*72+4*18, crop boxes exact); `test_compose_slices_have_key_size`; `test_bezel_slices_skip_gap_pixels` (a synthetic image with a unique colour per pixel column proves skipped columns are absent from every slice); `test_center_crops_wide_image_symmetrically`; `test_stretch_distorts_to_fill`; `test_preview_gaps_are_dark`; `test_load_image_rejects_oversize_and_missing_and_corrupt`; `test_gallery_sorted_wraps_and_rescans` (add a file between calls).
- [ ] **Step 2:** Run; expect failure.
- [ ] **Step 3: Implement** with Pillow only.
- [ ] **Step 4:** Run; expect pass.
- [ ] **Step 5: Commit** `feat: screensaver composition and image source`.

### Task 3: Device brightness, write gate, key swallow

**Files:**
- Modify: `src/decker/server/devices/__init__.py` (`Device.set_brightness`), `src/decker/server/devices/manager.py`
- Test: `tests/server/devices/test_device_brightness.py`, `tests/server/devices/test_manager_overlay.py`

**Interfaces:**
- Produces: `Device.set_brightness(percent: int) -> None` (calls the deck; reopens like other writes).
- Produces on `DeviceManager`: `set_activity_hook(hook: Callable[[str], None] | None)`; `set_overlay(device_id, active: bool) -> None`; `overlay_active(device_id) -> bool`; `set_brightness(device_id, percent) -> None`; `write_overlay(device_id, images: list[bytes] | None) -> bool` (one PNG per key written through the same writer path as `set_image_bytes` but ignoring the gate; `None` blanks every key); `wake_hook` set via `set_wake_hook(hook: Callable[[str], None] | None)` invoked on the first press while the overlay is active.
- Gate behaviour: while `overlay_active`, `set_image_bytes`, `clear_key_image`, `blank_key`, `set_animation`, `show_page` and title writes update cached `DeviceState` as today but are not sent to the hardware. `show_page` called by the engine on wake runs after `set_overlay(device_id, False)`.
- Key behaviour in `_on_hw_key_event`: call the activity hook for every event of a current device; if the overlay is active, on a press call the wake hook, mark that key as "swallow release", and neither call `Device.on_key_event` nor the callback; later the matching release for a swallowed key is dropped too. Presses and releases of other keys during the overlay are swallowed (no wake on release alone).
- Brightness application: `_open_device` does not apply brightness itself; it calls the engine through the activity/wake path in Task 4. The manager only exposes `set_brightness`.

- [ ] **Step 1: Write failing tests** against a fake `StreamDeck` and the real `DeviceManager`: `test_wake_press_and_release_are_swallowed`; `test_other_key_release_during_overlay_swallowed`; `test_normal_events_pass_through_and_call_activity_hook`; `test_writes_during_overlay_update_state_but_not_hardware`; `test_write_overlay_bypasses_gate`; `test_show_page_after_overlay_off_redraws_cached_state`; `test_set_brightness_calls_deck`; `test_stale_device_events_do_not_wake`.
- [ ] **Step 2:** Run; expect failure.
- [ ] **Step 3: Implement.** Keep `_on_hw_key_event` under 50 lines by extracting `_gate_key_event`.
- [ ] **Step 4:** Run; expect pass, then the existing `tests/server/devices` for regressions.
- [ ] **Step 5: Commit** `feat: device brightness, overlay write gate and swallowed wake press`.

### Task 4: Engine (idle, activate, wake, gallery, shutdown)

**Files:**
- Create: `src/decker/server/screensaver/screensaver_engine.py`
- Test: `tests/server/screensaver/test_screensaver_engine.py`

**Interfaces:**
- Consumes: `ScreensaverStore.get`, `DeviceManager` methods from Task 3 (plus `opened_device_ids()`, existing `show_page`, `get_hw_info` rows/cols and key pixel size), `compose`/`source` from Task 2, `PageController.active_page_id`.
- Produces: `ScreensaverEngine(Manager)` with constructor taking the context plus an injectable `clock: Callable[[], float]` (default `time.monotonic`) and `on_change: Callable[[str, bool], None]`; methods `note_activity(device_id)`, `activate(device_id) -> bool`, `deactivate(device_id) -> bool`, `is_active(device_id) -> bool`, `status(device_id) -> ScreensaverStatus(active: bool, last_error: str)`, `apply_settings(device_id)` (re-applies normal brightness when awake and reschedules), `device_opened(device_id)` (applies normal brightness, resets the deadline, treats an active overlay as woken), `tick(now: float | None = None)` (one scheduler pass, for tests; the thread calls it about once per second).
- Behaviour: timeout 0 never activates on idle; `activate` renders off any hardware lock, then re-checks a per-device generation counter so a wake or newer activate during rendering aborts before any write; then `set_overlay(True)`, `stop_animations`, `write_overlay`, `set_brightness(saver_brightness)`, `on_change(id, True)`. A failed load or empty gallery blanks the keys, records `last_error`. `deactivate` does `set_overlay(False)`, normal brightness, `show_page`, `on_change(id, False)`. Gallery: mode `activation` advances the cursor on each activation; mode `interval` re-renders every `gallery_minutes` while active. `destroy()` stops the thread and deactivates every active device.

- [ ] **Step 1: Write failing tests** with a fake clock and a fake manager recording calls: `test_idle_timeout_activates_after_deadline`; `test_timeout_zero_never_activates`; `test_activity_pushes_deadline`; `test_wake_during_render_aborts_without_writes`; `test_missing_image_blanks_and_sets_last_error`; `test_empty_gallery_blanks`; `test_gallery_advances_per_activation`; `test_gallery_interval_advances_while_active`; `test_activate_works_when_timeout_zero`; `test_deactivate_restores_brightness_and_page`; `test_device_opened_while_active_wakes`; `test_destroy_wakes_active_devices`; `test_apply_settings_sets_normal_brightness_when_awake_only`.
- [ ] **Step 2:** Run; expect failure.
- [ ] **Step 3: Implement.** One scheduler thread (daemon) per engine; per-device lock plus generation counter.
- [ ] **Step 4:** Run; expect pass.
- [ ] **Step 5: Commit** `feat: screensaver engine`.

### Task 5: Controller, RPCs, events, server wiring

**Files:**
- Create: `src/decker/server/screensaver/screensaver_controller.py`
- Modify: `server_context.py` (fields `screensaver_store`, `screensaver_controller`, `screensaver_engine`), `server.py` (build, `create`, hook the manager's activity/wake hooks and `device_opened`, `destroy`), `service.py` (five RPCs, loopback gate), `devices/manager.py` (call `device_opened` hook after `_open_device` and reopen)
- Test: `tests/server/screensaver/test_screensaver_controller.py`, `tests/server/test_service_screensaver.py` (real RPyC socket, as the app-rule service tests do)

**Interfaces:**
- Produces: `ScreensaverController` with `get(device_id) -> dict` (settings plus `active`, `last_error`), `set(device_id, settings_json, *, loopback: bool) -> None`, `activate(device_id)`, `deactivate(device_id)`, `preview(device_id, settings_json, *, loopback: bool) -> bytes` (PNG). `set` and `preview` raise `PermissionError` when `loopback` is false and `image_path`/`folder_path` differ from the stored values (preview: when either is non-empty). `set` stores, calls `engine.apply_settings`, emits `screensaver_settings_changed`. Engine `on_change` emits `screensaver_changed`.
- Events payloads (JSON): `screensaver_changed` `{"device_id": str, "active": bool}`; `screensaver_settings_changed` `{"device_id": str}`. `last_error` text is sent only in `screensaver_get`, never in events.
- Unknown device ids are rejected with a clear error.

- [ ] **Step 1: Write failing tests:** controller validation and gating (`test_remote_cannot_change_paths`, `test_remote_can_change_other_fields`, `test_unknown_device_rejected`, `test_set_never_activates`); events emitted through the real `EventBus`; over a real RPyC socket from a non-loopback-flagged connection, `test_remote_set_with_path_refused`; `test_preview_returns_png`; `test_activate_and_deactivate_rpcs_flip_status`.
- [ ] **Step 2:** Run; expect failure.
- [ ] **Step 3: Implement** and wire. Keep new RPC methods thin; mirror the app-rule RPC style.
- [ ] **Step 4:** Run the new tests, then `poe test` for regressions.
- [ ] **Step 5: Commit** `feat: screensaver controller, RPCs and server wiring`.

### Task 6: Client plumbing

**Files:**
- Modify: `src/decker/client/events/__init__.py`, `connection_manager.py`, `window.py`, `views/dashboard.py` (forward only if the dialog is owned there; otherwise `MainWindow`)
- Test: `tests/client/test_connection_manager_screensaver.py`

**Interfaces:**
- Produces: `ScreensaverSettingsEvent(device_id: str, settings: ScreensaverSettings, active: bool, last_error: str)` and `ScreensaverStateEvent(device_id: str, active: bool)`; `ConnectionManager.screensaver_get(device_id)`, `screensaver_set(device_id, settings) -> bool`, `screensaver_activate(device_id) -> bool`, `screensaver_deactivate(device_id) -> bool`, `screensaver_preview(device_id, settings) -> bytes | None`; push-events `screensaver_changed` and `screensaver_settings_changed` become the events above. Add the events to the event routing tables used for the app-rule events.

- [ ] **Step 1: Write failing tests:** parse a `screensaver_get` response; event forwarding through the real `MainWindow` routing (as the app-rule events are tested); `test_set_returns_false_on_refusal`.
- [ ] **Step 2:** Run; expect failure.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run; expect pass.
- [ ] **Step 5: Commit** `feat: client screensaver plumbing`.

### Task 7: Settings dialog "Device" section

**Files:**
- Create: `src/decker/client/widgets/screensaver_panel.py`
- Modify: `src/decker/client/widgets/settings_dialog.py`
- Test: `tests/client/widgets/test_screensaver_panel.py`

**Interfaces:**
- Consumes: Task 6 methods and events; the active device id from the existing selector.
- Produces: `ScreensaverPanel(QWidget)` with controls for every `ScreensaverSettings` field (brightness slider, timeout spin with "0 = never", saver brightness slider, content combo, image/folder pickers, scaling combo, bezel check with key/gap mm spins, gallery mode and minutes), a live preview pane (debounced calls to `screensaver_preview`), an "Activate now" button (toggles to "Wake"), a `last_error` label, and path pickers disabled with a hint when the connection is not loopback. Apply on change with a short debounce, resync on `ScreensaverSettingsEvent`, never overwrite a control the user is editing.

- [ ] **Step 1: Write failing offscreen tests:** `test_controls_reflect_settings_event`; `test_edit_calls_set_with_full_settings`; `test_pickers_disabled_for_remote`; `test_activate_button_calls_rpc_and_toggles_label`; `test_last_error_shown`; `test_bezel_fields_disabled_when_bezel_off`; `test_focused_control_not_overwritten_by_event`.
- [ ] **Step 2:** Run; expect failure.
- [ ] **Step 3: Implement** and embed the panel in `SettingsDialog`.
- [ ] **Step 4:** Run; expect pass.
- [ ] **Step 5: Commit** `feat: screensaver settings panel`.

### Task 8: Docs and final gates

**Files:**
- Create: `docs/screensaver.md`
- Modify: `README.md` (platform row, footnote), `docs/platform-support.md`, `CLAUDE.md` (server and client bullets, one architecture constraint: waking never fires an action and the screensaver never mutates stored state)

- [ ] **Step 1:** Write the docs: settings table, RPC and event reference, bezel geometry with a worked 72 px example, limits, hot-plug and shutdown behaviour (a crashed server leaves the deck on the screensaver until a server restarts), the loopback rule.
- [ ] **Step 2:** Run `poe format`, `poe mypy`, `poe pylint`, `poe test`; all pass.
- [ ] **Step 3: Commit** `docs: screensaver`.
