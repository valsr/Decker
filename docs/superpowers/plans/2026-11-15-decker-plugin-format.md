# Decker Plugin Format v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Decker's in-process plugin system with a versioned `.deckerplugin` package format whose plugins run as isolated processes over a JSON stdio protocol, with manifest-declared settings forms, Decker-drawn appearance, install/uninstall with per-plugin `uv` environments, and icon packs as a contribution kind.

**Architecture:** `PluginManager` keeps its public API (activate/deactivate/dispatch/list_actions) but delegates to a `PluginSupervisor` that runs one child process per plugin, speaking newline-delimited JSON on stdin/stdout. A dependency-free `decker_plugin_sdk` package gives Python authors the familiar `@action` / `DeckerPlugin` API. The server composes every key image (background → plugin image → title) and validates settings against manifest schemas; the client renders forms from those schemas.

**Tech Stack:** Python 3.14, PyQt6, RPyC, Pillow + cairosvg (existing), `packaging` (requirements/specifiers), `uv` (environments), pytest + assertpy.

**Spec:** `docs/superpowers/specs/2026-11-15-decker-plugin-format-design.md`

## Global Constraints

- Quality gates before every commit that ends a task: `poe format`, `poe mypy`, `poe pylint` (≥ 9.0), `QT_QPA_PLATFORM=offscreen poe test` (coverage ≥ 85%).
- Code style per `CLAUDE.md`: annotate everything; docstrings only on public members; methods < 50 lines; ≤ 5 args.
- Manifest `format` is `1`; protocol version is `1`; manifest keys are snake_case; unknown keys ignored; unknown `format` rejected.
- Plugin/contribution ids match the existing `_UUID_PATTERN` (`^[a-z0-9]+(\.[a-z0-9-]+)+$`); every contribution id starts with `<plugin id>.`.
- Package extension `.deckerplugin`; `manifest.json` at the archive root.
- `open_url` accepts only `http`/`https`.
- Requirements must be package-index requirements (no URL/git/path).
- Install/uninstall allowed only from loopback clients unless `server.allow_remote_plugin_install: true` (default `false`).
- Default plugin RSS limit 256 MiB (config `plugin.memory_limit`).
- `decker_plugin_sdk` imports nothing from `decker` and has no third-party dependencies.
- Milestones end in a working app and are shipped as separate PRs (M1 → M4), per "keep PRs focused".

## Review Focus

1. **A plugin (or a library it imports) writes non-protocol text to stdout** → the line is logged as plugin output and ignored; the plugin keeps running. *(Test in Task 5.)*
2. **A plugin sends `set_image` for a context that has already disappeared (page switched / key cleared)** → dropped; it never draws on whatever now occupies that key. *(Test in Task 7.)*
3. **Stored settings no longer match the schema after a plugin update** (key removed, type changed, out of range) → defaults fill in, invalid values are replaced, nothing crashes. *(Test in Task 2.)*
4. **Server stops (or restarts) while plugin processes are running** → every child is terminated; no orphans. *(Test in Task 6.)*
5. **Installing a new version while its actions are live on the visible page** → keys go blank briefly then re-appear under the new process with settings intact. *(Test in Task 14.)*

---

## File Structure

New:
- `src/decker/plugin/settings_schema.py` — parse/validate settings schemas; apply to values.
- `src/decker/plugin/protocol.py` — message type, encode/decode, event-name constants.
- `src/decker/plugin/runtime/__init__.py`, `process.py` (one child process), `supervisor.py` (lifecycle, watchdog, restart policy), `launcher.py` (command line per runtime).
- `src/decker_plugin_sdk/__init__.py`, `__main__.py`, `_runtime.py`, `_context.py`, `_gestures.py` — the Python SDK.
- `src/decker/server/appearance.py` — `Appearance` + `compose_key_image`.
- `src/decker/common/appearance_schema.py` — the built-in Appearance settings schema shared by server and client.
- `src/decker/client/widgets/schema_form.py` — native form from a schema.
- `src/decker/plugin/package.py` — read/validate/extract `.deckerplugin`.
- `src/decker/plugin/environment.py` — requirement validation + `uv` environment build; SDK staging.
- `src/decker/server/plugin_installer.py` — install/uninstall jobs.
- `src/decker/client/widgets/plugins_tab.py` — Settings → Plugins tab.
- `src/decker/server/contributions.py` — contribution registry + handler protocol.
- `src/decker/cli/plugin_scaffold.py` — `new` and `pack`.

Rewritten: `src/decker/plugin/manifest.py`, `src/decker/plugin/loader.py`, `src/decker/server/plugins.py`, `src/decker/client/widgets/action_config_panel.py`, `src/decker/asset/iconpack.py`, `src/decker/client/icon_picker.py`, `src/decker/bundled_plugins/com.decker.counter/*`.

Deleted (M1): `src/decker/plugin/native_loader.py`, `registry.py`, `executor.py`, `base.py`; `ActionContext`/`HardwareSink`/`SettingsStore` in `context.py` (keep `ActionTarget`, move to `src/decker/plugin/target.py`). Deleted (M4): `src/decker/cli/iconpack.py`, `IconPackManager.install`, `paths.iconpacks()`.

---

# Milestone 1 — Out-of-process runtime (PR "Plugin format v1: runtime and SDK")

Ends with: the Counter runs as a separate process through the SDK; everything else behaves as today (its client form is still the hand-coded one).

### Task 1: Manifest v1

**Files:**
- Rewrite: `src/decker/plugin/manifest.py`
- Test: `tests/plugin/test_manifest.py` (rewrite)

**Interfaces:**
- Produces:
  - `RuntimeSpec(type: Literal["python", "executable"], entry: str, python: str | None, requirements: tuple[str, ...])`
  - `StateSpec(image: str | None, title: str | None)`
  - `ActionSpec(id: str, name: str, tooltip: str, icon: str | None, gestures: frozenset[str], states: tuple[StateSpec, ...], settings: tuple[SettingEntry, ...], appearance: dict[str, Any])`
  - `IconPackSpec(id: str, name: str, path: str, description: str)`
  - `PluginManifest(format: int, id, name, version, author, description, homepage, icon, category, decker: str | None, runtime: RuntimeSpec | None, permissions: tuple[str, ...], global_settings: tuple[SettingEntry, ...], actions: tuple[ActionSpec, ...], icon_packs: tuple[IconPackSpec, ...])`
  - `PluginManifest.from_dict(data) -> PluginManifest`, `PluginManifest.load(path) -> PluginManifest`, `ManifestValidationError`, `SUPPORTED_FORMAT = 1`, `KNOWN_CONTRIBUTION_KINDS = frozenset({"actions", "icon_packs"})`
- Consumes: `parse_settings_schema` from Task 2 (write Task 2 first or stub the import in the same commit).

- [ ] **Step 1: Write failing tests** in `tests/plugin/test_manifest.py`, using the spec's Counter manifest as `_COUNTER` fixture:
  - `test_counter_manifest_parses` — `actions[0].id == "com.decker.counter.counter"`, `actions[0].gestures == {"press", "long_press"}`, `runtime.type == "python"`, `runtime.entry == "plugin.py"`.
  - `test_unknown_format_rejected` — `format: 2` → `ManifestValidationError` matching `"format 2"`.
  - `test_missing_format_rejected`.
  - `test_unknown_top_level_keys_ignored`.
  - `test_contributes_required_and_non_empty` — `{}` → error.
  - `test_unknown_contribution_kind_rejected` — `{"screensavers": []}` → error message contains `"requires a newer version of Decker"`.
  - `test_actions_require_runtime` — actions present, no runtime → error.
  - `test_icon_pack_only_needs_no_runtime` — passes with `runtime is None`.
  - `test_contribution_id_must_be_prefixed_by_plugin_id` — action id `com.other.x` → error.
  - `test_invalid_gesture_rejected` — `"gestures": ["swipe"]` → error.
  - `test_url_requirement_rejected` — `"requirements": ["foo @ https://x/y.whl"]` → error; `["git+https://x"]` → error; `["requests>=2"]` → ok.
  - `test_runtime_type_must_be_python_or_executable`.
  - `test_action_gestures_default_to_press`.
  - `test_malformed_json_and_non_object_rejected` (via `load`).
- [ ] **Step 2: Run** `poetry run pytest tests/plugin/test_manifest.py -v` — expect failures (import/attribute errors).
- [ ] **Step 3: Implement** the dataclasses (frozen) and `from_dict` in `manifest.py`. Requirement validation uses `packaging.requirements.Requirement(req)`; reject when `.url` is set or the string doesn't parse. Keep `_UUID_PATTERN` and `_optional_str`. Add `packaging = "^25.0"` to `[tool.poetry.dependencies]`.
- [ ] **Step 4: Run** the tests — PASS.
- [ ] **Step 5: Commit** `feat(plugin): manifest format v1`.

### Task 2: Settings schema

**Files:**
- Create: `src/decker/plugin/settings_schema.py`
- Test: `tests/plugin/test_settings_schema.py`

**Interfaces:**
- Produces:
  - `SettingSection(title: str)`, `SettingField(key: str, type: str, label: str, default: Any, optional: bool, placeholder: str, help: str, extra: Mapping[str, Any])`, `SettingEntry = SettingSection | SettingField`
  - `FIELD_TYPES = frozenset({"int", "float", "text", "bool", "choice", "color", "font", "icon"})`
  - `parse_settings_schema(data: Any, where: str) -> tuple[SettingEntry, ...]` (raises `ValueError` with `where` in the message; `manifest.py` re-raises as `ManifestValidationError`)
  - `apply_schema(schema: Sequence[SettingEntry], values: Mapping[str, Any]) -> dict[str, Any]`
  - `schema_to_json(schema: Sequence[SettingEntry]) -> list[dict[str, Any]]` (round-trips to the manifest shape; sent to clients)

- [ ] **Step 1: Write failing tests:**
  - `test_parses_sections_and_fields_in_order`.
  - `test_unknown_type_rejected`, `test_duplicate_key_rejected`, `test_choice_requires_options`.
  - `test_default_must_match_type` — `{"type": "int", "default": "x"}` → error.
  - `test_apply_fills_defaults` — `apply_schema(counter_schema, {}) == {"step": 1, "double_step": None, "max": 0}`.
  - `test_apply_drops_unknown_keys`.
  - `test_apply_replaces_invalid_values_with_default` — `{"step": "abc"} → step == 1`; `{"step": 0}` (below `min: 1`) → `1`; `{"background": "blue"}` for `color` → default.
  - `test_apply_optional_empty_becomes_none` — `{"double_step": ""} → None`.
  - `test_apply_coerces_int_strings` — `{"step": "5"} → 5`.
  - `test_apply_choice_outside_options_uses_default`.
  - `test_schema_to_json_round_trips`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** Color = `^#[0-9a-fA-F]{6}$`. `int` accepts ints and int-like strings, clamps nothing — out of `min`/`max` → default. `optional` fields with `None`/`""` → `None`; a non-optional field with no `default` gets the type's zero value (`0`, `0.0`, `""`, `False`, first option).
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(plugin): declarative settings schema`.

### Task 3: Protocol

**Files:**
- Create: `src/decker/plugin/protocol.py`
- Test: `tests/plugin/test_protocol.py`

**Interfaces:**
- Produces: `PROTOCOL_VERSION = 1`, `MAX_LINE_BYTES = 8 * 1024 * 1024`, `Message(event: str, context: str | None = None, payload: dict[str, Any] = {})` (frozen), `encode(message: Message) -> bytes` (UTF-8 JSON + `b"\n"`, omits `context` when None and `payload` when empty), `decode(line: bytes) -> Message` raising `ProtocolError`, `SERVER_EVENTS` and `PLUGIN_EVENTS` frozensets with exactly the event names in spec §5.

- [ ] **Step 1: Write failing tests:** `test_round_trip`, `test_encode_is_single_line_even_with_newlines_in_payload`, `test_decode_rejects_non_json`, `test_decode_rejects_missing_event`, `test_decode_rejects_non_object_payload`, `test_decode_rejects_oversized_line`, `test_event_sets_match_spec` (assert the two sets literally).
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(plugin): stdio JSON protocol`.

### Task 4: Python SDK

**Files:**
- Create: `src/decker_plugin_sdk/__init__.py`, `__main__.py`, `_runtime.py`, `_context.py`, `_gestures.py`
- Modify: `pyproject.toml` — `packages = [{ include = "decker", from = "src" }, { include = "decker_plugin_sdk", from = "src" }]`
- Test: `tests/sdk/test_runtime.py`, `tests/sdk/fixtures/echo_plugin.py`

**Interfaces:**
- Produces (public SDK API, exported from `decker_plugin_sdk`):
  - `Gesture` (StrEnum: `PRESS="press"`, `DOUBLE_PRESS="double_press"`, `LONG_PRESS="long_press"`)
  - `DeckerPlugin` with handlers `on_will_appear`, `on_will_disappear`, `on_key_down`, `on_key_up`, `on_press`, `on_double_press`, `on_long_press`, `on_settings_changed`, `on_global_settings_changed`, each `(self, ctx: ActionContext) -> None`; and `gestures(self, settings: dict) -> frozenset[Gesture] | None` (default `None` = use the manifest's list)
  - `action(action_id: str)` decorator
  - `ActionContext`: attributes `context`, `action`, `device`, `key_index`, `column`, `row`, `settings` (dict), `global_settings` (dict), `state` (int); methods `set_image(data: bytes, format: str = "png")`, `clear_image()`, `set_title(title: str)`, `set_state(state: int)`, `show_alert()`, `show_ok()`, `set_settings(settings: dict)`, `set_global_settings(settings: dict)`, `open_url(url: str)`, `log(message: str, level: str = "info")`
  - `run(actions: Mapping[str, type[DeckerPlugin]], stdin: BinaryIO, stdout: BinaryIO) -> int`
  - `python -m decker_plugin_sdk <entry.py>`: imports the entry by path (`importlib.util.spec_from_file_location`), collects `@action` classes, redirects `sys.stdout` to `sys.stderr` *before* importing the entry, calls `run(...)` with the real stdout buffer.
- Behaviour pinned by the spec: send `ready` after receiving `hello`; reply `pong` to `ping` on the reader thread; dispatch handlers on a 4-worker pool with per-context ordering (one queue per context); after `will_appear` and `settings_changed`, if `gestures()` returns non-None, send `set_gestures {gestures: [...]}`; exit 0 on `shutdown` or EOF; never write anything but protocol lines to stdout. Must not import `decker`.

- [ ] **Step 1: Write failing tests** driving `run()` with in-memory pipes (`os.pipe` wrapped in file objects) and the `echo_plugin` fixture (one action whose `on_press` calls `ctx.set_title("pressed")`, whose `gestures` returns `{PRESS, DOUBLE_PRESS}` when `settings.get("dbl")`):
  - `test_ready_after_hello`, `test_ping_answered_while_handler_blocks` (handler sleeps on an Event), `test_press_dispatches_handler_and_set_title`, `test_set_gestures_sent_after_will_appear_when_overridden`, `test_no_set_gestures_when_gestures_returns_none`, `test_handler_exception_logged_not_fatal` (next event still handled; a `log` message with level `error` is sent), `test_events_for_one_context_run_in_order`, `test_exit_on_shutdown`, `test_exit_on_eof`, `test_sdk_does_not_import_decker` (subprocess `python -c "import decker_plugin_sdk, sys; assert not any(m == 'decker' or m.startswith('decker.') for m in sys.modules)"`), `test_module_entry_point_runs_plugin_file` (spawn `python -m decker_plugin_sdk tests/sdk/fixtures/echo_plugin.py`, send hello, expect ready).
- [ ] **Step 2: Run** `poetry run pytest tests/sdk -v` — FAIL.
- [ ] **Step 3: Implement.** Writer serialises with a lock. Settings/global settings in `ActionContext` are refreshed from `will_appear`/`settings_changed`/`global_settings_changed` payloads.
- [ ] **Step 4: Run** — PASS. **Step 5: Commit** `feat(sdk): Python plugin SDK`.

### Task 5: Plugin process

**Files:**
- Create: `src/decker/plugin/runtime/__init__.py`, `process.py`, `launcher.py`
- Test: `tests/plugin/runtime/test_process.py`, `tests/plugin/runtime/test_launcher.py`

**Interfaces:**
- Consumes: `Message`, `encode`, `decode`, `ProtocolError` (Task 3); `RuntimeSpec` (Task 1).
- Produces:
  - `launch_command(plugin_dir: Path, runtime: RuntimeSpec, bundled: bool) -> list[str]` — bundled python: `[sys.executable, "-m", "decker_plugin_sdk", entry]`; installed python: `[str(plugin_dir / ".venv/bin/python"), "-m", "decker_plugin_sdk", entry]`; executable: `[str(plugin_dir / entry)]`. Entry must resolve inside `plugin_dir` else `ValueError`.
  - `launch_env(sdk_path: Path | None) -> dict[str, str]` — minimal env: `PATH`, `HOME`, `LANG`, `PYTHONUNBUFFERED=1`, plus `PYTHONPATH=<sdk_path>` when given (bundled plugins pass `None`).
  - `PluginProcess(plugin_id: str, command: list[str], cwd: Path, env: dict[str, str], on_message: Callable[[Message], None], on_exit: Callable[[int], None])` with `start() -> None`, `send(message: Message) -> None` (no-op if not running), `stop(timeout: float = 3.0) -> None` (send `shutdown`, wait, then terminate, then kill), `is_running: bool`, `pid: int | None`, `rss_bytes() -> int | None` (from `/proc/<pid>/status` `VmRSS`).
  - stdout reader thread decodes lines → `on_message`; undecodable lines are logged at warning as `"[<plugin_id>] non-protocol output: …"` and ignored; stderr reader logs each line as `"[<plugin_id>] …"`; `on_exit(returncode)` fires once when the process ends for any reason.

- [ ] **Step 1: Write failing tests** with tiny fixture scripts run by `sys.executable`:
  - `test_message_round_trip` (fixture echoes `hello` as `ready`).
  - `test_non_protocol_stdout_is_ignored_and_process_keeps_running` *(Review Focus 1)* — fixture prints `"hello world"` then a valid `ready`; `on_message` receives only `ready`; `is_running` still true.
  - `test_stderr_is_logged_with_plugin_prefix` (caplog).
  - `test_stop_sends_shutdown_then_kills_unresponsive` — fixture ignores shutdown; `stop(timeout=0.5)` returns, `is_running` false.
  - `test_on_exit_called_once_on_crash`.
  - `test_rss_bytes_positive_while_running`.
  - launcher: `test_bundled_python_uses_server_interpreter`, `test_installed_python_uses_plugin_venv`, `test_entry_outside_plugin_dir_rejected`, `test_env_is_minimal_and_has_sdk_path`.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(plugin): plugin child process`.

### Task 6: Supervisor

**Files:**
- Create: `src/decker/plugin/runtime/supervisor.py`
- Test: `tests/plugin/runtime/test_supervisor.py`

**Interfaces:**
- Consumes: `PluginProcess`, `launch_command`, `launch_env` (Task 5).
- Produces: `SupervisorPolicy(idle_grace_s: float = 10.0, ping_interval_s: float = 5.0, ping_timeout_s: float = 10.0, memory_limit: int = 256 * 1024 * 1024, max_crashes: int = 3, crash_window_s: float = 60.0, backoff_s: tuple[float, ...] = (0.5, 2.0, 5.0))` and
  `PluginSupervisor(policy: SupervisorPolicy, process_factory: Callable[..., PluginProcess], on_message: Callable[[str, Message], None], on_failed: Callable[[str, str], None])` with:
  - `register(plugin_id: str, command: list[str], cwd: Path, env: dict[str, str], hello: dict[str, Any]) -> None`
  - `acquire(plugin_id: str) -> None` / `release(plugin_id: str) -> None` (ref-count of live contexts; start on first acquire; stop `idle_grace_s` after count hits 0 unless re-acquired)
  - `send(plugin_id: str, message: Message) -> None` — queued until the plugin sends `ready` (sends `hello` first on every start)
  - `is_failed(plugin_id) -> bool`, `reset_failure(plugin_id) -> None`, `unregister(plugin_id) -> None` (stops the process)
  - `tick(now: float) -> None` — drives ping/memory/idle checks (called from a 1 s timer thread started by `start()`; tests call `tick` directly with an injected clock)
  - `start() -> None`, `stop_all() -> None`
  - On unexpected exit while acquired: restart after `backoff_s[n]`; after `max_crashes` within `crash_window_s` → mark failed, call `on_failed(plugin_id, reason)`, drop queued messages. Over memory limit or unanswered ping past `ping_timeout_s` → kill (counts as a crash). On restart, the supervisor replays nothing itself — `on_message`'s owner (Task 7) re-sends `will_appear` for live contexts when it sees `ready`.

- [ ] **Step 1: Write failing tests** with a fake `PluginProcess` (records sent messages, can be told to exit/answer pings, reports a settable RSS) and a fake clock:
  - `test_first_acquire_starts_and_sends_hello`, `test_messages_queued_until_ready`, `test_second_acquire_does_not_start_second_process`, `test_release_stops_after_idle_grace`, `test_reacquire_within_grace_keeps_process`, `test_crash_restarts_with_backoff`, `test_repeated_crashes_mark_failed_and_notify`, `test_reset_failure_allows_restart`, `test_memory_limit_kills`, `test_unanswered_ping_kills`, `test_stop_all_stops_every_process` *(Review Focus 4)*, `test_unregister_stops_process`.
  - Plus an integration test with real processes: `test_server_stop_leaves_no_orphans` *(Review Focus 4)* — start two real fixture plugins, `stop_all()`, assert both pids are gone (`os.kill(pid, 0)` raises `ProcessLookupError`).
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(plugin): process supervisor with restart and watchdog`.

### Task 7: Loader + PluginManager on the new runtime; Counter ported

**Files:**
- Rewrite: `src/decker/plugin/loader.py`, `src/decker/server/plugins.py`
- Create: `src/decker/plugin/target.py` (move `ActionTarget` here unchanged)
- Delete: `src/decker/plugin/native_loader.py`, `registry.py`, `executor.py`, `base.py`, `context.py`; their tests (`tests/plugin/test_native_loader.py`, `test_registry.py`, `test_base.py`, `test_context.py`, executor tests)
- Modify: `src/decker/plugin/__init__.py` (export nothing plugin-author-facing), imports of `ActionTarget` in `key_assignments.py`, `service.py`, `page_controller.py` and tests; `src/decker/common/config/defaults.yml` (add `plugin: memory_limit: 268435456`); `src/decker/server/server.py` (call `plugin_manager.destroy()` → `supervisor.stop_all()` on shutdown — confirm it is already in the manager teardown path)
- Rewrite: `src/decker/bundled_plugins/com.decker.counter/manifest.json` (spec manifest, but in M1 the action's `settings` also lists today's appearance keys `background`, `title`, `title_position`, `title_font`, `title_size`, `title_color`, `title_outline`, `title_outline_width` with today's `DEFAULTS`, so behaviour is unchanged until M2), `plugin.py` (import from `decker_plugin_sdk`; `CounterAction.gestures` returns `{PRESS, LONG_PRESS}` plus `DOUBLE_PRESS` when `double_step` is set; drop the `DEFAULTS` dict — settings arrive complete)
- Test: `tests/plugin/test_loader.py`, `tests/server/test_plugins.py`, `tests/bundled_plugins/test_counter.py` (rewrite)

**Interfaces:**
- Consumes: `PluginManifest` (Task 1), `apply_schema`, `schema_to_json` (Task 2), `PluginSupervisor` (Task 6), `launch_command`/`launch_env` (Task 5), `GestureRecognizer` (existing).
- Produces:
  - `InstalledPlugin(manifest: PluginManifest, plugin_dir: Path, bundled: bool)`; `PluginLoader(plugins_dir, bundled: bool).scan() -> PluginScanResult(plugins: list[InstalledPlugin], failures: list[PluginLoadFailedEvent])`
  - `PluginManager` keeps the existing public methods and signatures (`create`, `destroy`, `load_failures`, `list_actions`, `get_key_display_states`, `store_settings`, `activate_action`, `deactivate_action`, `dispatch_key_down`, `dispatch_key_up`, `dispatch_settings_changed`) and adds `add_plugin(plugin: InstalledPlugin) -> None`, `remove_plugin(plugin_id: str) -> None`, `plugins() -> list[InstalledPlugin]`, `live_targets(plugin_id: str) -> list[ActionTarget]`.
  - `list_actions()` entries gain `"tooltip"` and `"settings_schema"` (from `schema_to_json`).
  - Settings passed to plugins and returned to clients always go through `apply_schema(action.settings, stored)`.
  - Server push event `open_url` with payload `{"plugin_id", "url"}` for `http`/`https` only (others logged and dropped).
  - `device_connected {device}` is sent to a plugin for each open device right after its `ready`; `device_connected`/`device_disconnected` are forwarded to running plugins from the device manager's existing hot-plug handling (if it has none, only the post-`ready` announcement is implemented — note it in the PR).
  - `dispatch_settings_changed` calls `supervisor.reset_failure(plugin_id)` so a user re-saving settings retries a failed plugin (spec §6).

- [ ] **Step 1: Write failing tests** (real counter plugin process, fake hardware sink as today):
  - loader: `test_scans_plugin_folders`, `test_invalid_manifest_reported_as_failure`, `test_bundled_flag_set`.
  - manager: `test_list_actions_includes_settings_schema_and_tooltip`, `test_activate_sends_will_appear_with_complete_settings`, `test_press_reaches_plugin_and_image_reaches_sink`, `test_set_gestures_changes_recognizer_registration` (counter with `double_step` set → press waits for the double-press window), `test_deactivate_sends_will_disappear_and_releases`, `test_set_image_for_disappeared_context_is_dropped` *(Review Focus 2)* — deactivate, then deliver a queued `set_image` for the old context; sink not called, `DeviceState` unchanged, `test_ready_after_restart_replays_will_appear_for_live_contexts`, `test_failed_plugin_keys_marked_and_failure_reported` (keys blanked and labelled "Plugin failed"; a `PluginLoadFailedEvent`-style `plugin_failed` push reaches clients), `test_resaving_settings_retries_failed_plugin`, `test_device_connected_sent_after_ready`, `test_open_url_non_http_dropped`, `test_set_settings_from_plugin_is_validated_and_persisted`.
  - counter: `test_press_increments`, `test_double_press_registered_only_with_double_step`, `test_long_press_resets`, `test_max_wraps` — run through the SDK `run()` with pipes, not the server.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** `PluginManager` owns one `PluginSupervisor`; per-context state `{target, action spec, recognizer, gestures}`; inbound `set_image`/`set_title` map context → `ActionTarget` and go to the existing `_StreamDeckHardwareSink` only while the context is live; `show_alert`/`show_ok` stay no-ops (as today). Bundled plugins: `bundled=True`, `sdk_path=None`. Keep the `PluginLoadFailedEvent` path for scan failures and add one for `on_failed`.
- [ ] **Step 4: Run** full suite `QT_QPA_PLATFORM=offscreen poetry run poe test` — PASS; fix callers broken by the `ActionTarget` move.
- [ ] **Step 5:** Manual: `poe server` + `poe client`, place a Counter, press on device — counts, long press resets, double press only after setting a double step.
- [ ] **Step 6: Commit** `feat(plugin): run plugins out of process; port Counter to the SDK`.

### Task 8: Open-URL confirmation in the client

**Files:**
- Modify: `src/decker/client/connection_manager.py` (`open_url` event → `OpenUrlRequestedEvent`), `src/decker/client/events/__init__.py`, `src/decker/client/window.py`
- Test: `tests/client/test_window.py`, `tests/client/test_connection_manager.py`

**Interfaces:**
- Produces: `OpenUrlRequestedEvent(plugin_id: str, url: str)`; `MainWindow` shows `QMessageBox.question(self, "Open link", f"{plugin_id} wants to open {url}")` and calls `QDesktopServices.openUrl` only on Yes; ignores non-http(s) defensively.

- [ ] **Step 1: Failing tests:** `test_open_url_event_parsed`, `test_open_url_opens_only_after_confirmation` (patch `QMessageBox.question` → Yes/No, patch `QDesktopServices.openUrl`), `test_open_url_rejects_file_scheme`.
- [ ] **Step 2–4:** run/implement/run.
- [ ] **Step 5: Commit** `feat(client): confirm plugin open_url requests`. Run all quality gates; open PR for M1.

---

# Milestone 2 — Settings forms and Decker-drawn appearance (PR "Plugin format v1: settings forms and appearance")

Ends with: every action's config panel is generated from its manifest; title/background are Decker's for every action; the Counter's hard-coded form is gone.

### Task 9: Appearance model and key composition

**Files:**
- Create: `src/decker/common/appearance_schema.py`, `src/decker/server/appearance.py`
- Test: `tests/server/test_appearance.py`

**Interfaces:**
- Produces:
  - `APPEARANCE_SCHEMA: list[dict]` — settings-schema JSON (Task 2 shape) with sections "Background" and "Title" and keys `background` (color, default `"#000000"`), `show_title` (bool, `True`), `title` (text, `""`), `title_position` (choice top/middle/bottom, `"bottom"`), `title_font` (font, `"DejaVu Sans"`), `title_size` (int 4–48, `12`), `title_color` (color, `"#ffffff"`), `title_outline` (color, optional), `title_outline_width` (int 1–6, `1`).
  - `resolve_appearance(action_defaults: Mapping[str, Any], stored: Mapping[str, Any]) -> dict[str, Any]` — `apply_schema(parse(APPEARANCE_SCHEMA), {**action_defaults, **stored})`.
  - `compose_key_image(appearance: Mapping[str, Any], plugin_image: bytes | None, plugin_title: str, size: int = 144) -> bytes` (PNG). Order: background fill → plugin image scaled to fit (rendered with existing `AssetRenderer.render_bytes`) → title (user `title` if non-empty else `plugin_title`; skipped when `show_title` is false or the text is empty). Title drawing moves here from the Counter (fc-match font lookup, stroke outline, sizes relative to 72 px × `size/72`).
- Manifest: `ActionSpec.appearance` is validated against `APPEARANCE_SCHEMA` keys in Task 1's parser (add the check here; unknown keys → error).

- [ ] **Step 1: Failing tests:** `test_defaults_from_schema`, `test_action_defaults_override_schema_defaults`, `test_stored_overrides_action_defaults`, `test_background_fills_key` (pixel at corner == background), `test_plugin_image_drawn_over_background` (centre pixel from a solid red 72×72 PNG), `test_user_title_beats_plugin_title`, `test_plugin_title_used_when_no_user_title`, `test_show_title_false_hides_title`, `test_svg_plugin_image_supported`, `test_unknown_appearance_key_in_manifest_rejected`.
- [ ] **Step 2–4:** run/implement/run.
- [ ] **Step 5: Commit** `feat(server): Decker-drawn key appearance`.

### Task 10: Appearance storage, composition in the image path, Counter migration

**Files:**
- Modify: `src/decker/server/key_assignments.py` (add `appearance TEXT NOT NULL DEFAULT '{}'` column with migration; `KeyAssignment.appearance: dict[str, Any]`; `update_appearance(device_id, page_id, key_index, appearance) -> bool`), `src/decker/server/plugins.py` (keep per-context `plugin_image`, `plugin_title`, `state`; every change → `compose_key_image(...)` → existing sink `set_image`; state images from `states[n].image` via `read_icon` when the plugin hasn't set one), `src/decker/server/service.py` (new RPC `key_update_appearance(device_id, page_id, key_index, appearance_json) -> bool`; key state payloads gain `"appearance"` and `"appearance_defaults"`), counter manifest (remove the M1 appearance keys from `settings`; add `"appearance": {"background": "#1f618d"}`), counter `plugin.py` (render only background-less count image: transparent PNG with the count; stop calling `set_title`)
- Test: `tests/server/test_key_assignments.py`, `tests/server/test_plugins.py`, `tests/server/test_service.py`, `tests/bundled_plugins/test_counter.py`

**Interfaces:**
- Consumes: `resolve_appearance`, `compose_key_image` (Task 9).
- Produces: `KeyAssignmentStore.update_appearance(...)`, RPC `key_update_appearance`, migration `_migrate_counter_appearance()` — for rows with `plugin_uuid == "com.decker.counter"`, move keys `background`, `title`, `title_position`, `title_font`, `title_size`, `title_color`, `title_outline`, `title_outline_width` from `settings` to `appearance` (an empty `title_outline` becomes absent). Runs once (guarded by a `schema_version`-style marker the store already uses for its page migration, or a new `meta` row).

- [ ] **Step 1: Failing tests:** `test_appearance_column_migrated_with_empty_default`, `test_update_appearance_persists`, `test_counter_appearance_migrated_out_of_settings` (old row `{"step": 2, "background": "#ff0000", "title": "A"}` → settings `{"step": 2}`, appearance `{"background": "#ff0000", "title": "A"}`), `test_appearance_change_recomposes_key_without_plugin_round_trip`, `test_state_image_used_until_plugin_sets_image`, `test_counter_key_is_blue_by_default` (composed corner pixel == `#1f618d`), `test_counter_no_longer_sets_title`, `test_key_update_appearance_rpc`.
- [ ] **Step 2–4:** run/implement/run.
- [ ] **Step 5: Commit** `feat: store per-key appearance and compose key images`.

### Task 11: Schema-driven config panel

**Files:**
- Create: `src/decker/client/widgets/schema_form.py`
- Rewrite: `src/decker/client/widgets/action_config_panel.py`
- Modify: `src/decker/client/views/dashboard.py` (`show_counter_config` → `show_action_config(slot, schema, save_settings_cb, save_appearance_cb)`; look up the action's `settings_schema` from the action list)
- Test: `tests/client/widgets/test_schema_form.py`, `tests/client/widgets/test_action_config_panel.py`, `tests/client/views/test_dashboard.py`

**Interfaces:**
- Consumes: `APPEARANCE_SCHEMA` (Task 9), action list entries with `settings_schema` (Task 7), key state `appearance`/`appearance_defaults` (Task 10).
- Produces:
  - `SchemaForm(QWidget)`: `set_schema(schema: list[dict[str, Any]], values: dict[str, Any]) -> None`, `values() -> dict[str, Any]`. Widget per type: int → `QSpinBox` (`special_value` → `setSpecialValueText`), optional int → `QLineEdit` + `QIntValidator` (empty → `None`), float → `QDoubleSpinBox`, text → `QLineEdit`/`QPlainTextEdit` (`multiline`), bool → `QCheckBox`, choice → `QComboBox` (data = value), color → existing `ColorButton` (optional color → checkbox + button, unchecked → `None`), font → `QFontComboBox`, icon → `QLineEdit` (plain path until the icon library). Sections → bold `QLabel` with `role="title"`. `help` → tooltip; `placeholder` → placeholder text.
  - `ActionConfigPanel.show_action_config(settings_schema, settings, appearance, appearance_defaults, save_cb: Callable[[dict, dict], None])` — two `SchemaForm`s (Appearance first, then plugin settings) + Save; keeps the existing "don't clobber edits in progress if the same values are re-sent" behaviour; `show_placeholder()` unchanged. Save sends only appearance values that differ from `appearance_defaults`.
  - `COUNTER_DEFAULTS` and the counter page are deleted.

- [ ] **Step 1: Failing tests:** one `test_<type>_round_trips` per field type; `test_optional_int_empty_is_none`; `test_sections_render_as_headings`; `test_values_returns_defaults_for_untouched_fields`; panel: `test_counter_schema_renders_step_double_step_max`, `test_save_sends_settings_and_changed_appearance_only`, `test_resent_identical_values_keep_edits`, dashboard: `test_selecting_key_shows_schema_form_for_its_action`, `test_save_calls_key_update_settings_and_key_update_appearance`.
- [ ] **Step 2–4:** run/implement/run.
- [ ] **Step 5:** Manual: config panel for a Counter shows Appearance + Counting; changing background recolours the key immediately.
- [ ] **Step 6: Commit** `feat(client): settings forms generated from manifests`. Run all gates; open PR for M2.

---

# Milestone 3 — Install, uninstall, environments, tooling (PR "Plugin format v1: install and uninstall")

### Task 12: Package reading and safe extraction

**Files:**
- Create: `src/decker/plugin/package.py`
- Test: `tests/plugin/test_package.py`

**Interfaces:**
- Produces: `MAX_PACKAGE_BYTES = 64 * 1024 * 1024`, `MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024`, `MAX_ENTRIES = 10_000`, `PackageError(Exception)`, `read_manifest(data: bytes) -> PluginManifest` (validates archive + manifest, no writes), `extract(data: bytes, dest: Path) -> PluginManifest` (dest must not exist; created by this call).
- Rejections (each a `PackageError` with a user-readable message): over size caps; not a zip; no root `manifest.json`; entry names containing `\`, absolute paths, `..` components, or symlink entries (`external_attr` S_IFLNK); duplicate names; manifest errors (wrap `ManifestValidationError`).

- [ ] **Step 1: Failing tests** (build zips in-memory with `zipfile`): `test_valid_package_reads_manifest`, `test_extract_writes_files_under_dest`, `test_rejects_oversized_upload`, `test_rejects_zip_bomb_by_uncompressed_total`, `test_rejects_too_many_entries`, `test_rejects_parent_traversal`, `test_rejects_absolute_path`, `test_rejects_backslash_names`, `test_rejects_symlink_entry`, `test_rejects_missing_root_manifest` (manifest only in a subfolder), `test_rejects_non_zip`, `test_manifest_error_message_preserved`.
- [ ] **Step 2–4:** run/implement/run. **Step 5: Commit** `feat(plugin): safe .deckerplugin reading`.

### Task 13: Environments and SDK staging

**Files:**
- Create: `src/decker/plugin/environment.py`
- Modify: `src/decker/common/paths.py` (add `sdk() -> Path` = `~/.decker/sdk`)
- Test: `tests/plugin/test_environment.py`

**Interfaces:**
- Produces:
  - `EnvironmentBuildError(Exception)`
  - `stage_sdk(dest_root: Path | None = None) -> Path` — copies the installed `decker_plugin_sdk` package directory to `<root>/<decker version>/decker_plugin_sdk` (idempotent) and returns the parent directory (used as `PYTHONPATH`); called by `PluginManager.create`.
  - `build_environment(plugin_dir: Path, runtime: RuntimeSpec, progress: Callable[[str], None], uv: str = "uv") -> None` — `uv venv <plugin_dir>/.venv [--python <spec>]`, then if requirements: `uv pip install --python <plugin_dir>/.venv/bin/python <reqs…>`; timeouts 300 s each; non-zero exit or missing `uv` → `EnvironmentBuildError` with the last 20 lines of output; `progress` receives each output line.

- [ ] **Step 1: Failing tests:** `test_stage_sdk_copies_package_and_is_idempotent`, `test_build_creates_venv_with_server_python_when_no_spec` and `test_build_installs_requirements` (both marked `@pytest.mark.slow`, skipped when `shutil.which("uv")` is None; the second installs a tiny pure-Python package from a local wheel built in the test via `uv build` on a fixture project, using `--find-links` and `--no-index` — add those as an optional `index: Path | None` arg for tests only via `extra_args: Sequence[str] = ()`), `test_missing_uv_raises`, `test_failed_install_raises_with_output` (fake `uv` script on PATH that exits 1).
- [ ] **Step 2–4:** run/implement/run. **Step 5: Commit** `feat(plugin): per-plugin uv environments`.

### Task 14: Installer service and RPCs

**Files:**
- Create: `src/decker/server/plugin_installer.py`
- Modify: `src/decker/server/service.py`, `src/decker/server/server_context.py` (add `plugin_installer`), `src/decker/server/server.py` (construct it), `src/decker/common/config/defaults.yml` (`server.allow_remote_plugin_install: false`)
- Test: `tests/server/test_plugin_installer.py`, `tests/server/test_service.py`

**Interfaces:**
- Consumes: `read_manifest`, `extract` (Task 12), `build_environment` (Task 13), `PluginManager.add_plugin/remove_plugin/plugins/live_targets` (Task 7), `KeyAssignmentStore`, `DeviceManager.clear_key_state`, `DeviceStateStore.delete_key_state`, `event_bus.push`.
- Produces:
  - `PluginInstaller(plugins_dir: Path, context: ServerContext, decker_version: str)` with `install(filename: str, data: bytes) -> str` (job id; work on a background thread), `uninstall(plugin_id: str) -> None` (raises `PluginInstallError` for unknown or bundled ids), `usage(plugin_id: str) -> int` (assigned keys across all devices/pages).
  - Events: `plugin_install_progress {job_id, message}`, `plugin_install_finished {job_id, ok: bool, plugin_id: str | None, version: str | None, previous_version: str | None, message: str}`, `plugins_changed {}` after any successful install/uninstall.
  - Install flow: `read_manifest` → refuse bundled id → check `manifest.decker` against `decker_version` with `packaging.specifiers.SpecifierSet` ("requires Decker <spec>") → extract to `plugins_dir/.staging-<job>` → build env if `runtime.type == "python"` → if the id exists: deactivate its live targets (remember them), `remove_plugin`, move old folder aside → rename staging into `plugins_dir/<id>` → `add_plugin` → reactivate remembered targets → delete old folder. Any failure → remove staging, restore old folder, finish with `ok: False`.
  - Uninstall flow: deactivate live targets, `remove_plugin`, unassign every key that uses the plugin (all devices/pages) clearing images/labels, delete its plugin settings rows, `rmtree` its folder, push `plugins_changed` and per-device refresh.
  - RPCs on `DeckerService`: `plugins_list() -> list[dict]` (`id, name, version, author, description, bundled, actions: int, icon_packs: int, icon_b64, global_settings_schema, global_settings`), `plugin_install_allowed() -> bool`, `plugin_install(filename: str, data: bytes) -> str`, `plugin_uninstall(plugin_id: str) -> bool`, `plugin_usage(plugin_id: str) -> int`, `plugin_update_global_settings(plugin_id: str, settings_json: str) -> bool` (validated with `apply_schema`, persisted, `global_settings_changed` sent to the running plugin).
  - Loopback rule: `DeckerService.on_connect` records the peer host from the connection's socket (`conn._channel.stream.sock.getpeername()[0]`); `plugin_install`/`plugin_uninstall` raise `PermissionError("Installing plugins is only allowed from the server's own machine")` unless the peer is loopback (`ipaddress.ip_address(host).is_loopback`) or `server.allow_remote_plugin_install` is true; `plugin_install_allowed` reports the same decision.
- Global settings persistence: add a `global_settings` table to `PluginSettingsStore` keyed by `plugin_id`; `hello` carries them.

- [ ] **Step 1: Failing tests:** `test_install_new_plugin_registers_and_announces` (executable-runtime fixture to avoid uv), `test_install_refuses_bundled_id`, `test_install_refuses_incompatible_decker_version`, `test_failed_install_leaves_nothing_behind`, `test_reinstall_replaces_and_reactivates_live_keys` *(Review Focus 5)* — live key on the active page, install v2: `will_disappear` to the old process, `will_appear` to the new one with the same settings, `previous_version == "1.0.0"`, `test_failed_upgrade_restores_previous_version`, `test_uninstall_clears_keys_on_all_pages_and_removes_folder`, `test_uninstall_bundled_refused`, `test_usage_counts_keys_across_pages`, `test_remote_peer_cannot_install_by_default`, `test_remote_install_allowed_by_config`, `test_install_allowed_reports_decision`, `test_global_settings_validated_persisted_and_sent`, `test_client_disconnect_mid_install_still_completes`.
- [ ] **Step 2–4:** run/implement/run. **Step 5: Commit** `feat(server): plugin install/uninstall service`.

### Task 15: Settings → Plugins tab and drag-and-drop install

**Files:**
- Create: `src/decker/client/widgets/plugins_tab.py`
- Modify: `src/decker/client/widgets/settings_dialog.py` (Plugins tab = `PluginsTab`, failure list moves into it), `src/decker/client/window.py` (`setAcceptDrops(True)`; `dragEnterEvent`/`dropEvent` accept local files ending `.deckerplugin`), `src/decker/client/connection_manager.py` (events `plugin_install_progress`, `plugin_install_finished`, `plugins_changed` → client events; refresh actions on `plugins_changed`), `src/decker/client/events/__init__.py`
- Test: `tests/client/widgets/test_plugins_tab.py`, `tests/client/test_window.py`

**Interfaces:**
- Consumes: RPCs from Task 14; `SchemaForm` (Task 11).
- Produces: `PluginsTab(QWidget)` with `refresh() -> None`; rows show icon, name, version, author, "bundled"/"installed", and contributions ("2 actions · 1 icon pack"); Uninstall (installed only) → `QMessageBox.question` with "<name> is used on N keys. Uninstall it and clear those keys?" (count from `plugin_usage`); Install… → `QFileDialog` filtered to `*.deckerplugin`; a global-settings `SchemaForm` + Apply for the selected plugin when it declares one; an install-status line fed by progress/finished events; when `plugin_install_allowed()` is false, Install is disabled with tooltip "Installing plugins is only allowed from the server's own machine".
  - `install_package_file(path: Path) -> None` (module-level helper in `plugins_tab.py`, shared by the tab and the window drop): reads bytes (refuse > 64 MiB client-side with a message), calls `plugin_install`, shows a toast/status. The install-time notice "Plugins run with your user's permissions. Only install plugins from authors you trust." is shown in the confirmation before sending.
  - `MainWindow.dropEvent` → `install_package_file` for each dropped `.deckerplugin`; other files ignored; disabled (drop rejected) when installs aren't allowed.

- [ ] **Step 1: Failing tests:** `test_lists_plugins_with_contribution_summary`, `test_uninstall_confirms_with_usage_count_and_calls_rpc`, `test_bundled_plugin_has_no_uninstall`, `test_install_button_disabled_when_not_allowed`, `test_install_progress_and_result_shown`, `test_global_settings_form_applies`, `test_drop_deckerplugin_triggers_install`, `test_drop_other_files_ignored`, `test_drop_rejected_when_install_not_allowed`, `test_plugins_changed_refreshes_action_list`.
- [ ] **Step 2–4:** run/implement/run.
- [ ] **Step 5:** Manual: drop a packed plugin on the window → it appears in the sidebar without restarting; uninstall clears its keys.
- [ ] **Step 6: Commit** `feat(client): plugin manager tab and drag-and-drop install`.

### Task 16: CLI — new, pack, install, remove, list

**Files:**
- Create: `src/decker/cli/plugin_scaffold.py`, `src/decker/cli/templates/plugin/` (`manifest.json`, `plugin.py`, `icons/action.png`)
- Rewrite: `src/decker/cli/plugin.py` (install/remove/list over RPC), `src/decker/cli/app.py` (`plugin new|pack|install|remove|list`)
- Test: `tests/cli/test_plugin_scaffold.py`, `tests/cli/test_plugin.py`, `tests/cli/test_app.py`

**Interfaces:**
- Produces: `scaffold(plugin_id: str, dest: Path) -> Path` (creates `<dest>/<plugin_id>/` from the template with ids substituted; refuses an existing folder), `pack(folder: Path, out_dir: Path | None = None) -> Path` (validates with `read_manifest` on the produced bytes; writes `<id>-<version>.deckerplugin`; excludes `.venv`, `__pycache__`, dotfiles). `install(conn: CliConnection, path: Path) -> str` sends the bytes, returns the job id, and the CLI prints "Install started (job <id>); progress appears in the client and the server log". `remove(conn, plugin_id)`, `list_plugins(conn) -> list[dict]`.

- [ ] **Step 1: Failing tests:** `test_scaffold_creates_valid_plugin` (then `pack` it and `read_manifest` succeeds), `test_scaffold_refuses_existing_folder`, `test_pack_excludes_venv_and_pycache`, `test_pack_rejects_invalid_manifest`, `test_install_sends_bytes_over_rpc` (fake conn), `test_remove_and_list_use_rpc`, `test_app_routes_plugin_subcommands`.
- [ ] **Step 2–4:** run/implement/run.
- [ ] **Step 5: Commit** `feat(cli): plugin new/pack and RPC-based install`. Run all gates; open PR for M3.

---

# Milestone 4 — Icon packs as a contribution (PR "Plugin format v1: icon pack contributions")

### Task 17: Contribution registry and icon pack handler

**Files:**
- Create: `src/decker/server/contributions.py`
- Rewrite: `src/decker/asset/iconpack.py` (registry of contributed packs; no installing), `src/decker/asset/store.py` (drop the pack table; keep `user_icon_assignments`)
- Modify: `src/decker/server/plugins.py` (`add_plugin`/`remove_plugin` go through the registry; actions become the `"actions"` handler), `src/decker/server/server.py`, `src/decker/server/server_context.py`, `src/decker/server/service.py`
- Delete: `src/decker/cli/iconpack.py`, iconpack commands in `src/decker/cli/app.py`, `paths.iconpacks()`/`iconpacks_dir()`, `IconPackManifest`/`validate_icons_json` in `asset/manifest.py`, their tests
- Test: `tests/server/test_contributions.py`, `tests/asset/test_iconpack.py` (rewrite), `tests/server/test_service.py`

**Interfaces:**
- Produces:
  - `ContributionHandler` Protocol: `kind: str`, `register(plugin: InstalledPlugin) -> None`, `unregister(plugin_id: str) -> None`.
  - `ContributionRegistry(handlers: Sequence[ContributionHandler])` with `add(plugin) -> None` (calls every handler whose kind the manifest contributes; a handler error rolls back already-registered handlers and re-raises), `remove(plugin_id) -> None`. Assert at construction that handler kinds == `KNOWN_CONTRIBUTION_KINDS`.
  - `IconPackRegistry` (kind `"icon_packs"`): `list_packs() -> list[dict]` (`id, name, description, plugin_id, icon_count`), `list_icons(pack_id: str) -> list[str]` (image files `.png .jpg .jpeg .svg` under the pack folder, relative paths, sorted; `icons.json` used for ordering when present), `read_icon(pack_id: str, name: str) -> bytes | None` (resolved path must stay inside the pack folder; size ≤ `MAX_ICON_BYTES` from `decker.plugin.icons`).
  - RPCs: `iconpacks_list() -> list[dict]`, `iconpack_icons(pack_id: str) -> list[str]`, `iconpack_icon(pack_id: str, name: str) -> str` (base64, `""` if missing).
  - Bundled Counter gains the example `iconpack/` folder and `icon_packs` contribution from the spec manifest.

- [ ] **Step 1: Failing tests:** `test_registry_dispatches_by_kind`, `test_handler_failure_rolls_back`, `test_icon_pack_only_plugin_starts_no_process`, `test_list_icons_finds_images`, `test_read_icon_rejects_path_escape` (`"../manifest.json"`), `test_read_icon_rejects_oversized`, `test_uninstall_removes_pack`, `test_iconpack_rpcs`, `test_counter_contributes_example_pack`.
- [ ] **Step 2–4:** run/implement/run. **Step 5: Commit** `feat: icon packs as a plugin contribution`.

### Task 18: Icon picker fed by the server

**Files:**
- Rewrite: `src/decker/client/icon_picker.py` (`IconPackBrowserDialog` lists packs/icons via RPC and renders icons from `iconpack_icon`; no `IconPackManager`, no local pack paths)
- Modify: callers in `src/decker/client/views/device.py`
- Test: `tests/client/test_icon_picker.py` (rewrite)

**Interfaces:**
- Consumes: RPCs from Task 17 through `ConnectionManager.call`.
- Produces: `IconPackBrowserDialog(parent, connection_manager)` with signal `icon_chosen(str pack_id, str icon_name)`; icons loaded lazily per pack and cached per dialog.

- [ ] **Step 1: Failing tests:** `test_lists_packs_from_server`, `test_selecting_pack_lists_its_icons`, `test_icon_choice_emits_pack_and_name`, `test_works_without_local_pack_files` (no filesystem access patched to fail).
- [ ] **Step 2–4:** run/implement/run.
- [ ] **Step 5:** Manual: from a second machine's client (server with `host: 0.0.0.0`), browse the Counter's example pack.
- [ ] **Step 6: Commit** `feat(client): browse icon packs from the server`. Update `CLAUDE.md` (plugin architecture paragraph: out-of-process plugins, `decker_plugin_sdk`, `.deckerplugin`), run all gates; open PR for M4.
