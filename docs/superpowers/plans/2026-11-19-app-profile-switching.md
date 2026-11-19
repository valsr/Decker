# App Profile Switching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Decker server detects the focused window with no client running and switches each device's profile (and optionally page) through an ordered, per-device list of match rules, with one editable-target default rule, a combined "Profiles and rules" dialog and a Window Spy.

**Architecture:** A `WindowBackend` per platform (Plasma/KWin, X11, Windows; others report `unsupported`) feeds a `WindowWatcher` (debounce, status, events) that calls an `AppRuleEngine`. The engine evaluates each device's rules from `AppRuleStore` and switches through the existing `PageController`. Rule edits go through `AppRuleController` and RPCs; the client gets a `ProfilesDialog` (replacing `ProfileEditDialog`) and a `WindowSpyDialog`.

**Tech Stack:** Python 3.14, SQLite (`decker.db`), RPyC, PyQt6, `jeepney` (D-Bus), `python-xlib` (X11), `ctypes` (Windows), `regex` (timeout-bounded matching), pytest + assertpy.

**Spec:** `docs/superpowers/specs/2026-11-19-app-profile-switching-design.md`

## Global Constraints

- Branch `feat/app-profile-switching`; commits end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Quality gates before done: `poe format`, `poe mypy`, `poe pylint` (>= 9.0), `poe test` (coverage >= 85%). Run `format` first.
- black line length 120; annotate every parameter, return and attribute; methods < 50 lines; max 5 arguments; docstrings on public classes/functions only (one short line); comments only for a non-obvious why.
- Tests live in `tests/` mirroring `src/`; pytest + `assertpy`; do not mock the database or the page store (integration style); fake only the window backend and hardware.
- Do not add a `start` RPC; the server is started only through the monitor (`poe server`).
- Platform tiers: Plasma/Wayland (v1), X11 (v1), Windows (v1); GNOME and macOS report `unsupported` ("not yet" in the README table). Update `README.md` platform table and `docs/platform-support.md` in the same change.
- Match fields: `window_class`, `window_type`, `title`, `executable`, `desktop_file`; ops: `equals`, `contains`, `not_contains`, `regex`; all case-insensitive; conditions AND-ed, no OR; first enabled matching rule wins; default rule is last, can only be enabled/disabled (target editable).
- Window titles go over RPC and events only to loopback clients (remote clients get `""`); titles are never logged above debug.
- Rule edits never switch the deck; they take effect at the next focus change. Start/connect evaluates the current window.
- New runtime dependencies are allowed (`jeepney`, `python-xlib` Linux-only via markers; `regex`); backend modules import their library lazily so the package imports on every platform.

## Review Focus

- Pathological user regex (`(a+)+$`) on a long title must not stall detection: matching uses `regex` with a timeout and treats a timeout as "no match" (Task 2).
- Rapid focus flicker (alt-tab through five windows in 100 ms) must produce one evaluation, for the last window (Task 5).
- A backend callback that raises must not kill the watcher: status becomes `unavailable`, it is retried with backoff (Task 5).
- A rule pointing at a profile or page deleted a moment earlier, or at an unplugged device, must not raise from the focus path (Task 6).
- Server started with no desktop session: detection reports `unavailable: no desktop session`, rule RPCs still work, nothing crashes (Tasks 5, 7).
- A remote (non-loopback) client must never receive a window title, via status, `window_focused` or `window_picked` (Task 7).
- Empty `contains`/`regex` value would match every window: rejected at save (Tasks 2, 4).

---

### Task 1: Plasma spike (prove KWin script and `queryWindowInfo`)

Manual, on a real Plasma 6 Wayland session. Deliverable is evidence and fixtures, not product code.

**Files:**
- Create: `src/decker/server/windows/kwin_script.js` (the working KWin script)
- Create: `tests/server/windows/fixtures/kwin_focus.json`, `tests/server/windows/fixtures/kwin_pick.json` (captured payloads)
- Create: `docs/superpowers/notes/2026-11-19-kwin-spike.md` (findings)

**Interfaces:**
- Produces: the script's callback contract (D-Bus bus name `org.decker.WindowWatcher`, path `/WindowWatcher`, method `Focused(s json)` with keys `resourceClass`, `windowType`, `caption`, `pid`, `desktopFileName`), the script name `decker-window-watcher`, and the exact `org.kde.KWin /KWin queryWindowInfo` return keys with the mapping to `WindowInfo`.

- [ ] **Step 1:** In a scratch script, load the KWin script over `org.kde.KWin /Scripting loadScript(path, name)` + `start`, have it call the method above on `workspace.windowActivated`; capture three real payloads (a native Wayland app, an XWayland app, a dialog) into `kwin_focus.json`.
- [ ] **Step 2:** Call `org.kde.KWin /KWin queryWindowInfo`, click a window, save the returned dict to `kwin_pick.json`; record the cancel behaviour (Escape) and the error returned when the picker is already open.
- [ ] **Step 3:** Prove stale-script handling: kill the scratch process, run `unloadScript(name)` before `loadScript` again and confirm only one script fires. Record whether `isScriptLoaded(name)` exists.
- [ ] **Step 4:** Write the findings note (what worked, key names, KWin version, anything that contradicts the spec) and commit. If `queryWindowInfo` does not exist, stop and report to the user before Task 8.

### Task 2: Models and rule matching

**Files:**
- Modify: `src/decker/common/model.py` (add dataclasses)
- Create: `src/decker/common/window_match.py`
- Modify: `pyproject.toml` (add `regex`)
- Test: `tests/common/test_window_match.py`

**Interfaces:**
- Produces in `model.py` (all `frozen=True`): `WindowInfo(window_class: str = "", window_type: str = "", title: str = "", executable: str = "", desktop_file: str = "", pid: int = 0)`; `MATCH_FIELDS: tuple[str, ...]`, `MATCH_OPS: tuple[str, ...]`; `MatchCondition(field: str, op: str, value: str)`; `AppRule(rule_id: str, name: str, enabled: bool, conditions: list[MatchCondition], profile_id: int, page_id: str = "")`; `DefaultRule(enabled: bool = False, profile_id: int = 0, page_id: str = "")`; `DeviceRules(device_id: str, rules: list[AppRule], default_rule: DefaultRule)`; `RuleTarget(profile_id: int, page_id: str)`.
- Produces in `window_match.py`: `condition_matches(condition: MatchCondition, window: WindowInfo) -> bool`; `rule_matches(rule: AppRule, window: WindowInfo) -> bool`; `resolve_target(rules: DeviceRules, window: WindowInfo) -> RuleTarget | None`; `validate_condition(condition: MatchCondition) -> str | None` (error text, `None` = valid).

- [ ] **Step 1: Write failing tests** in `tests/common/test_window_match.py`: `test_equals_is_case_insensitive`, `test_contains_and_not_contains`, `test_not_contains_true_on_empty_field_others_false` (`contains`/`regex` on `""` are False, `not_contains` True, `equals ""` on `""` True), `test_regex_uses_search` (`^org\.kde\.` vs `org.kde.dolphin`), `test_rule_requires_all_conditions`, `test_rule_without_conditions_never_matches`, `test_resolve_target_first_enabled_match_wins`, `test_resolve_target_skips_disabled_rule`, `test_resolve_target_falls_back_to_enabled_default_rule`, `test_resolve_target_none_when_default_disabled`, `test_validate_rejects_unknown_field_op_bad_regex_and_empty_contains_or_regex` (empty `equals` accepted), `test_pathological_regex_times_out_as_no_match` (`(a+)+$` against `"a"*40 + "!"` returns False in under 1 s).
- [ ] **Step 2:** Run `pytest tests/common/test_window_match.py -v`; expect FAIL on import.
- [ ] **Step 3:** Add the dataclasses and implement the functions. Use `regex.search(..., flags=regex.IGNORECASE, timeout=0.1)`; catch `TimeoutError` and log at debug; `contains` etc. compare lower-cased strings.
- [ ] **Step 4:** Run the tests; expect PASS. Commit `feat: window match models and rule matching`.

### Task 3: Rule store

**Files:**
- Create: `src/decker/server/app_rule_store.py`
- Test: `tests/server/test_app_rule_store.py`

**Interfaces:**
- Consumes: model dataclasses (Task 2); follow `PageStore`'s constructor and `Manager` lifecycle (`PageStore(db_path=...)`, `create(ctx)`, `destroy()`).
- Produces: `AppRuleStore(Manager)` with `list_rules(device_id: str) -> DeviceRules` (no rows = no rules, default rule `DefaultRule()`); `add_rule(device_id: str, rule: AppRule) -> AppRule` (generates `rule_id` = uuid hex, appends at the end, returns the stored rule); `update_rule(device_id: str, rule: AppRule) -> bool`; `delete_rule(device_id: str, rule_id: str) -> bool`; `move_rule(device_id: str, rule_id: str, position: int) -> bool` (clamped); `set_default_rule(device_id: str, default_rule: DefaultRule) -> None`; `profile_deleted(device_id: str, profile_id: int) -> bool` and `page_deleted(device_id: str, page_id: str) -> bool` (cascades, return whether anything changed).

- [ ] **Step 1: Write failing tests** (real SQLite in `tmp_path`): `test_round_trip_preserves_order_and_conditions`, `test_add_assigns_unique_ids`, `test_move_rule_reorders_and_clamps`, `test_update_and_delete_unknown_rule_return_false`, `test_fresh_device_has_disabled_default_rule_for_profile_zero`, `test_profile_deleted_removes_its_rules_and_resets_default_rule` (default rule disabled, target reset to profile `0`), `test_page_deleted_clears_page_id_on_rules_and_default_rule`, `test_data_survives_reopen`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement with tables `app_rules(device_id, rule_id, position, name, enabled, conditions_json, profile_id, page_id, PRIMARY KEY (device_id, rule_id))` and `default_rules(device_id PRIMARY KEY, enabled, profile_id, page_id)` created idempotently in `create`; a lock around the connection like `PageStore`.
- [ ] **Step 4:** Run; expect PASS. Commit `feat: app rule store`.

### Task 4: Rule controller and page/profile cascade

**Files:**
- Create: `src/decker/server/app_rule_controller.py`
- Modify: `src/decker/server/server_context.py` (optional fields), `src/decker/server/page_controller.py` (`delete_profile`, `delete_page`)
- Test: `tests/server/test_app_rule_controller.py`, extend `tests/server/test_page_controller.py`

**Interfaces:**
- Consumes: `AppRuleStore` (Task 3), `validate_condition` (Task 2), `PageStore.get_profile`, `.profile_of_page`, `EventBus.push`.
- Produces: `APP_RULES_CHANGED_EVENT = "app_rules_changed"`; `ServerContext` gains `app_rule_store: AppRuleStore | None = None`, `app_rule_controller: AppRuleController | None = None`, `app_rule_engine: "AppRuleEngine | None" = None`, `window_watcher: "WindowWatcher | None" = None`; `AppRuleController(Manager)` with `rules(device_id: str) -> DeviceRules`, `add_rule(device_id: str, rule: AppRule) -> AppRule | None`, `update_rule(device_id: str, rule: AppRule) -> bool`, `delete_rule(device_id: str, rule_id: str) -> bool`, `move_rule(device_id: str, rule_id: str, position: int) -> bool`, `set_default_rule(device_id: str, default_rule: DefaultRule) -> bool`. Each validates (known profile; `page_id` empty or a page of that profile; every condition valid; non-blank name), stores, pushes `app_rules_changed` `{"device_id"}`; invalid input returns `None`/`False`.

- [ ] **Step 1: Write failing tests**: `test_add_rule_rejects_unknown_profile`, `test_add_rule_rejects_page_of_another_profile`, `test_add_rule_rejects_empty_contains_value`, `test_valid_edit_pushes_app_rules_changed`, `test_set_default_rule_validates_target`; in `test_page_controller.py` `test_delete_profile_removes_rules_and_pushes_app_rules_changed` and `test_delete_page_clears_rule_page_ids` (real `AppRuleStore` in the fixture context; and one test that deleting works when `app_rule_store` is `None`).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement the controller. In `PageController`, after the store deletes, call `app_rule_store.profile_deleted/page_deleted` when the field is not `None` and push `app_rules_changed` if it returned `True`.
- [ ] **Step 4:** Run these plus `tests/server/test_page_controller.py`; expect PASS. Commit `feat: app rule controller with page and profile cascade`.

### Task 5: Backend interface, selection and watcher

**Files:**
- Create: `src/decker/server/windows/__init__.py`, `backend.py`, `select.py`, `unsupported.py`, `src/decker/server/window_watcher.py`
- Test: `tests/server/windows/test_select.py`, `tests/server/test_window_watcher.py`

**Interfaces:**
- Produces in `backend.py`: `BackendStatus(state: str, reason: str = "")` with `state` one of `"active"`, `"unavailable"`, `"unsupported"`; `WindowBackend(Protocol)` with `name: str`, `supports_pick: bool`, `available() -> BackendStatus`, `start(on_change: Callable[[WindowInfo], None]) -> None`, `stop() -> None`, `pick(on_result: Callable[[WindowInfo | None], None]) -> None`.
- Produces: `select_backend(env: Mapping[str, str], platform: str) -> WindowBackend` (`platform` is `sys.platform`; Plasma = `XDG_CURRENT_DESKTOP` contains `KDE` and `WAYLAND_DISPLAY`; X11 = `DISPLAY` set and not Plasma-Wayland; `win32` -> Windows; otherwise `UnsupportedBackend` with the reason; modules are imported lazily inside the branch, and a missing session returns an `unavailable` stub whose reason is `"no desktop session"`).
- Produces: `WindowWatcher(backend: WindowBackend, on_window: Callable[[WindowInfo], None], push: Callable[[str, WindowInfo], None], on_status: Callable[[], None], debounce: float = 0.15)` with `start()`, `stop()`, `status() -> dict[str, Any]` (keys `state`, `reason`, `backend`, `supports_pick`, `window`), `last_window() -> WindowInfo | None`, `pick(on_result: Callable[[WindowInfo | None], None]) -> bool` (False when unsupported/not active or a pick is open; 60 s timeout calls `on_result(None)`).

- [ ] **Step 1: Write failing tests**: `test_select_plasma_wayland`, `test_select_x11`, `test_select_windows`, `test_select_no_session_is_unavailable`, `test_select_gnome_wayland_is_unsupported` (all pure, env dicts); with a `FakeBackend` in the test file: `test_rapid_changes_evaluate_once_for_last_window`, `test_identical_consecutive_windows_dropped`, `test_push_called_for_every_distinct_change` (not debounced), `test_backend_exception_marks_unavailable_and_retries`, `test_pick_refused_while_pick_open_and_when_unsupported`, `test_pick_times_out_with_none` (inject a short timeout), `test_status_reports_last_window_and_support`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement. The watcher debounces with `threading.Timer`; a failing `backend.start` or callback sets state `unavailable` and a retry timer with exponential backoff (1 s doubling to 30 s); `stop` cancels timers.
- [ ] **Step 4:** Run; expect PASS. Commit `feat: window backend interface, selection and watcher`.

### Task 6: Rule engine

**Files:**
- Create: `src/decker/server/app_rule_engine.py`
- Test: `tests/server/test_app_rule_engine.py`

**Interfaces:**
- Consumes: `resolve_target` (Task 2), `AppRuleStore`, `PageController.active_profile_id`, `.active_page_id`, `.activate_profile`, `.activate`, `.device_pages`, `DeviceManager.list_devices`.
- Produces: `AppRuleEngine(Manager)` with `on_focus(window: WindowInfo) -> None` (evaluate all connected devices), `evaluate_device(device_id: str) -> None` (against the last window; used at start and device connect), `forget_device(device_id: str) -> None`.
- Behaviour: per device remember `last_target: RuleTarget | None` (initially `None`). Apply only when the new target is not `None` and differs from `last_target`; a `None` target resets `last_target` to `None`; the current window is kept for later `evaluate_device`. Applying: if the page is non-empty and still exists in that profile call `activate(device_id, page_id)`, otherwise `activate_profile(device_id, profile_id)`; do nothing when the profile is already active and (`page_id == ""` or the active page already equals it). Exceptions per device are caught and logged, never raised.

- [ ] **Step 1: Write failing tests** using real `PageStore`, `PageController`, `AppRuleStore` and a `MagicMock` device manager/plugin manager as in `tests/server/test_page_controller.py`: `test_matching_rule_activates_profile_default_page`, `test_rule_with_page_activates_that_page`, `test_missing_page_falls_back_to_profile_default`, `test_no_rule_no_default_changes_nothing`, `test_default_rule_applies_when_nothing_matches`, `test_manual_switch_sticks_while_target_unchanged` (focus A, switch manually, focus B with the same target: no switch), `test_returning_after_unmatched_window_reasserts` (A, manual switch, unmatched window, A: switches), `test_already_on_profile_with_no_page_does_nothing` (device on a non-default page of that profile stays), `test_evaluate_device_applies_current_window_on_connect`, `test_deleted_profile_race_does_not_raise` (rule inserted directly in the store pointing at a profile that does not exist), `test_devices_are_independent`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run; expect PASS. Commit `feat: app rule engine`.

### Task 7: Server wiring, RPCs and privacy

**Files:**
- Modify: `src/decker/server/server.py` (create/destroy managers, start watcher, evaluate devices after `_restore_devices`, stop on cleanup), `src/decker/server/service.py`, `src/decker/server/event_bus.py`, `src/decker/server/devices/manager.py` or the existing `devices_changed` path (call `evaluate_device` for a device that appears)
- Test: `tests/server/test_service_app_rules.py`, extend `tests/server/test_event_bus.py`

**Interfaces:**
- Consumes: Tasks 3-6.
- Produces: `EventBus.register(conn: Any, loopback: bool = True) -> None`; `EventBus.push_filtered(event_type: str, make_payload: Callable[[bool], str]) -> None` (each client gets `make_payload(its loopback flag)`); `EventBus.push_to(conn: Any, event_type: str, payload: str) -> None`. `DeckerService.on_connect` passes `_is_loopback(self._peer_host)` and keeps `self._conn`.
- RPCs (all `@exposed @api_response`, dicts over RPyC): `app_rules_list(device_id: str)`, `app_rule_add(device_id: str, rule: dict)` (returns the stored rule), `app_rule_update(device_id: str, rule: dict) -> bool`, `app_rule_delete(device_id: str, rule_id: str) -> bool`, `app_rule_move(device_id: str, rule_id: str, position: int) -> bool`, `app_default_rule_set(device_id: str, enabled: bool, profile_id: int, page_id: str) -> bool`, `window_detection_status()` (the watcher status; `window.title` is `""` for non-loopback callers), `window_pick() -> bool`. Events: `window_focused` (via `push_filtered`), `window_detection_changed`, `window_picked` (via `push_to` the caller's conn; payload `{"window": {...}}` or `{"window": null}`; title redacted for non-loopback).

- [ ] **Step 1: Write failing tests** (in-process service like `tests/server/test_service.py`, fake backend through `select_backend` injection or direct watcher): `test_rule_rpcs_round_trip`, `test_rule_rpc_rejects_invalid_rule`, `test_status_redacts_title_for_remote_peer`, `test_window_focused_redacted_for_remote_client_only` (two registered fake conns, one `loopback=False`), `test_window_pick_result_goes_only_to_caller`, `test_window_pick_false_when_unsupported`, `test_server_without_desktop_session_reports_unavailable_and_rule_rpcs_work`, `test_device_appearing_is_evaluated`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement the EventBus additions, the RPCs and the `server.py` wiring (managers created and destroyed with the others; the watcher stopped in `_cleanup`; window events pushed to the bus as JSON).
- [ ] **Step 4:** Run these plus `tests/server/test_event_bus.py`, `test_service.py`, `test_rpc_server.py`; expect PASS. Commit `feat: wire window detection and app rule RPCs into the server`.

### Task 8: Plasma (KWin) backend

**Files:**
- Create: `src/decker/server/windows/kwin.py`; the script from Task 1 is its data file
- Modify: `pyproject.toml` (`jeepney` with marker `sys_platform == "linux"`; type stubs if needed)
- Test: `tests/server/windows/test_kwin.py`

**Interfaces:**
- Consumes: Task 1 fixtures and notes, `WindowBackend` (Task 5).
- Produces: `KWinBackend` (`name = "kwin"`, `supports_pick = True`); `window_from_kwin(payload: Mapping[str, Any]) -> WindowInfo` (pure; `executable` = basename of the pid's process via `psutil`, `""` if gone).

- [ ] **Step 1: Write failing tests**: `test_window_from_kwin_maps_fixture_payloads` (the three Task 1 payloads), `test_query_window_info_result_maps_to_window_info` (`kwin_pick.json`), `test_pick_cancel_returns_none`, `test_start_unloads_stale_script_first` (fake D-Bus connection object recording calls: `unloadScript` before `loadScript`), `test_unavailable_when_kwin_6_missing_or_bus_name_unregistrable`, and a real-session smoke test skipped unless `DBUS_SESSION_BUS_ADDRESS` and KWin are present.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement against `jeepney` (D-Bus access in a thread, library imported inside `start`/`pick`); register the callback bus name and path from Task 1; `stop` unloads the script.
- [ ] **Step 4:** Run; expect PASS; run the smoke test on the Plasma machine. Commit `feat: kwin window backend`.

### Task 9: X11 backend

**Files:**
- Create: `src/decker/server/windows/x11.py`
- Modify: `pyproject.toml` (`python-xlib`, marker `sys_platform == "linux"`; `types-python-xlib` dev)
- Test: `tests/server/windows/test_x11.py`

**Interfaces:**
- Produces: `X11Backend` (`name = "x11"`, `supports_pick = True`); `window_from_x11(props: Mapping[str, Any]) -> WindowInfo` (pure; `window_class` from the `WM_CLASS` class part, `window_type` from `_NET_WM_WINDOW_TYPE` mapped to `normal`/`dialog`/`utility`/`dock`/`splash`/`menu`/`toolbar` (default `normal`), `title` from `_NET_WM_NAME`, `pid` from `_NET_WM_PID`, `executable` via `psutil`, `desktop_file` empty).

- [ ] **Step 1: Write failing tests**: `test_window_from_x11_maps_properties`, `test_window_type_atoms_map_and_default_to_normal`, `test_title_falls_back_to_wm_name`, `test_unavailable_without_display`, and an Xvfb smoke test (focus a window, receive the change; pick via a synthetic pointer click) skipped when `Xvfb`/`DISPLAY` is not available.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement: listen for `PropertyNotify` of `_NET_ACTIVE_WINDOW` on the root window in a thread; pick grabs the pointer with a crosshair cursor and takes the clicked top-level window (walk to the child of root); Escape or timeout returns `None`.
- [ ] **Step 4:** Run; expect PASS. Commit `feat: x11 window backend`.

### Task 10: Windows backend

**Files:**
- Create: `src/decker/server/windows/windows.py`
- Test: `tests/server/windows/test_windows_backend.py`

**Interfaces:**
- Produces: `WindowsBackend` (`name = "windows"`, `supports_pick = True`); `window_from_win32(hwnd_info: Mapping[str, Any]) -> WindowInfo` (pure; `window_class` = the window class name, `window_type` = `""`, `title`, `pid`, `executable` = process basename).

- [ ] **Step 1: Write failing tests**: `test_window_from_win32_maps_info_and_empty_type` (pure, runs on every OS), `test_backend_reports_unsupported_off_windows`, and Windows-only tests skipped elsewhere: `test_foreground_window_poll_reports_change`, `test_pick_returns_none_on_timeout`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement with `ctypes`: poll `GetForegroundWindow` every ~300 ms (`GetClassNameW`, `GetWindowTextW`, `GetWindowThreadProcessId`); pick installs a one-shot low-level mouse hook (`WH_MOUSE_LL`) in a thread with a message loop and takes `WindowFromPoint` of the click, walking up with `GetAncestor(GA_ROOT)`. All `ctypes.windll` use is inside methods.
- [ ] **Step 4:** Run (CI Windows runner covers the skipped ones); expect PASS. Commit `feat: windows window backend`.

### Task 11: Client plumbing

**Files:**
- Modify: `src/decker/client/connection_manager.py`, `src/decker/client/events/__init__.py`
- Test: extend `tests/client/test_connection_manager.py`, `tests/client/test_events.py`

**Interfaces:**
- Produces events: `AppRulesUpdatedEvent(rules: DeviceRules)`, `WindowFocusedEvent(window: WindowInfo)`, `WindowPickedEvent(window: WindowInfo | None)`, `DetectionStatusEvent(state: str, reason: str, backend: str, supports_pick: bool, window: WindowInfo | None)`. `ConnectionManager` gains `refresh_app_rules()`, `refresh_detection_status()` (called on connect and on `app_rules_changed`/`window_detection_changed`), and parsers `_parse_device_rules(data) -> DeviceRules`, `_parse_window(data) -> WindowInfo | None`.

- [ ] **Step 1: Write failing tests**: `test_parse_device_rules_round_trip`, `test_parse_rules_rejects_malformed`, `test_app_rules_changed_event_refreshes_rules`, `test_window_picked_event_pushes_event_with_none_on_cancel`, `test_detection_status_pushed_on_connect`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement, following `_refresh_profiles` and `_parse_device_profiles`.
- [ ] **Step 4:** Run; expect PASS. Commit `feat: client app rule events and parsing`.

### Task 12: Profiles and rules dialog

**Files:**
- Create: `src/decker/client/widgets/profiles_dialog.py`, `src/decker/client/widgets/rule_editor.py`
- Delete: `src/decker/client/widgets/profile_edit_dialog.py`, `tests/client/widgets/test_profile_edit_dialog.py`
- Modify: `src/decker/client/views/dashboard.py` (`_on_edit_profile` opens the new dialog)
- Test: `tests/client/widgets/test_profiles_dialog.py`, `tests/client/widgets/test_rule_editor.py`

**Interfaces:**
- Consumes: Task 11 events/models, `IconEdit`, the existing profile RPC names, `pages_list` for a profile's pages.
- Produces: `ProfilesDialog(call: Callable[..., None], pages_for_profile: Callable[[int], list[PageInfo]], parent: QWidget | None = None)`, non-modal, with `set_profiles(profiles: DeviceProfiles)`, `set_rules(rules: DeviceRules)`, `set_status(status: DetectionStatusEvent)`, `select_profile(profile_id: int)`. `call(rpc_name, *args)` fires an RPC (every edit saves immediately; no OK/Apply). `RuleEditor(QWidget)` with `set_rule(rule: AppRule)`, `rule() -> AppRule`, `set_unsupported_fields(fields: set[str])`, signal `changed`.
- Layout per spec: left profile list with add/rename/icon/delete (with the existing delete warning)/clone; right rule list (enable checkbox, name, "-> Profile / Page", move up/down) plus editor (name, condition rows field/operator/value, profile dropdown, page dropdown with "profile default"); pinned default-rule row (enable checkbox, target); status strip with the Window Spy button (button wired in Task 13); a warning on rules that use a field the backend does not supply.

- [ ] **Step 1: Write failing offscreen Qt tests**: `test_profile_actions_call_existing_rpcs` (rename, set icon, delete after confirm, clone), `test_add_rule_calls_app_rule_add_with_conditions`, `test_edit_rule_saves_immediately_via_app_rule_update`, `test_move_buttons_call_app_rule_move`, `test_default_rule_row_only_toggles_and_retargets` (no delete, no conditions, not movable), `test_page_dropdown_lists_only_chosen_profile_pages`, `test_empty_contains_value_is_flagged_before_saving`, `test_refresh_on_set_rules_keeps_selection`, `test_unsupported_field_warning`; for the dashboard `test_edit_profile_entry_opens_profiles_dialog_on_that_profile`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement; subscribe the dashboard to the Task 11 events and feed the dialog; remove the old dialog and its test.
- [ ] **Step 4:** Run `pytest tests/client -q`; expect PASS. Commit `feat: combined profiles and rules dialog`.

### Task 13: Window Spy

**Files:**
- Create: `src/decker/client/widgets/window_spy.py`
- Modify: `src/decker/client/widgets/profiles_dialog.py` (open the Spy; accept a prefilled new rule)
- Test: `tests/client/widgets/test_window_spy.py`

**Interfaces:**
- Produces: `WindowSpyDialog(call: Callable[..., None], own_pid: int, parent: QWidget | None = None)`, non-modal, with `set_status(status: DetectionStatusEvent)`, `on_focused(window: WindowInfo)`, `on_picked(window: WindowInfo | None)`; signal `create_rule(window: WindowInfo)`. `rule_from_window(window: WindowInfo) -> AppRule` (module function: `window_class equals`, plus `window_type equals` when not `normal` and not empty; profile `0`, name from the class).
- Behaviour per spec: **Pick window** calls `window_pick` when `supports_pick`, shows the result (cancel leaves the previous value); otherwise **Capture in 3 s** (countdown, then the next focused window whose `pid != own_pid`) and live **Follow** (ignores `own_pid`). Per-property copy buttons; unsupported fields greyed; disabled with the reason when detection is not `active`.

- [ ] **Step 1: Write failing tests**: `test_pick_button_calls_window_pick_and_shows_result`, `test_cancelled_pick_keeps_previous_window`, `test_capture_mode_when_pick_unsupported_ignores_own_pid` (fake clock/timer), `test_follow_ignores_own_pid`, `test_unsupported_fields_greyed`, `test_disabled_with_reason_when_unavailable`, `test_rule_from_window_prefills_class_and_non_normal_type`, `test_create_rule_signal_opens_new_rule_in_dialog`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement and wire into `ProfilesDialog`.
- [ ] **Step 4:** Run `pytest tests/client -q`; expect PASS. Commit `feat: window spy`.

### Task 14: Docs, platform table and final gates

**Files:**
- Create: `docs/app-profile-switching.md` (user guide, matching semantics, adding a backend)
- Modify: `README.md` (platform table row: Plasma yes, X11 yes, Windows yes, GNOME/macOS "not yet"), `docs/platform-support.md`, `CLAUDE.md` (server paragraph: window detection and rules; note `server/windows/`)

- [ ] **Step 1:** Write the docs and table changes; link the spec.
- [ ] **Step 2:** Run `poe format`, `poe mypy`, `poe pylint`, `poe test`; fix everything they report; expect all gates green with coverage >= 85%.
- [ ] **Step 3:** Run the stack once on the real Plasma desktop: `poe server`, `poe client`, add a rule for a terminal app, focus it and confirm the deck switches with the client closed; use the Window Spy pick. Record the result in the PR description.
- [ ] **Step 4:** Commit `docs: app profile switching`.
