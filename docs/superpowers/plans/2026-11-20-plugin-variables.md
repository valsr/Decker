# Plugin Variables and Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plugins declare global template variables in their manifest, supply values from code, and run `init`/`main` hooks in a process that starts with the server.

**Architecture:** `contributes.variables` declares exact names and patterns; the declaring plugin owns them (collisions rejected at load). A server-side `VariableStore` caches values; plugins answer `get_variable` requests and signal changes; text expansion reads only the cache. Plugins that declare variables are pinned running. The Python SDK gains `@init`, `@main`, `@variable`, `PluginContext` and variable helpers.

**Tech Stack:** Python 3.12, RPyC, pytest + assertpy, black (120), mypy, pylint.

**Spec:** `docs/superpowers/specs/2026-11-20-plugin-variables-design.md` (its `@variable("media_{deicve}_volume")` example is a typo for `{device}`).

## Global Constraints

- Quality gates: `poe format`, `poe mypy`, `poe pylint` (>= 9.0), `poe test` (coverage >= 85%). Annotate everything; methods under 50 lines; max 5 args; docstrings on public items only, one short line.
- Tests: pytest + assertpy, mirror the source layout, real components over mocks; test functions annotated `-> None`.
- Variable names: lowercase `[a-z][a-z0-9_]*`, at most 64 characters; values at most 1024 characters; at most 256 declarations per plugin.
- Core names `page_name`, `page_index`, `page_count`, `current_profile`, `profile_id` are never declarable.
- Global variables only: no per-device or per-key plugin variables; page/profile variables stay per device and server-owned.
- The server never calls a plugin on the draw/expansion path; expansion reads the cache only.
- A declared but unset or stopped variable expands to an empty string; an undeclared name stays as typed.
- A plugin's cached values are dropped when its process stops, and return after restart.
- Only a manifest `variables` entry makes a plugin always-on; plugins without one keep today's lazy start.
- Protocol changes are additive; `PROTOCOL_VERSION` and `hello.protocol` become 2. No OS-specific code (all five platform tiers).
- Update `docs/plugins/` (`protocol.md`, `package-and-manifest.md`, `sdk-quickstart.md`, `settings-schema.md`, `limits.md`), `CLAUDE.md`, `README.md` in the same change.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- A variable value containing `{page_name}` or `{{` is shown literally and never re-expanded.
- A getter that raises or hangs (5 s timeout) keeps the old value, logs once, and does not block other variables or leak a pending request when the plugin stops.
- Two plugins declaring the same name or pattern shape: the second fails to load with a recorded failure and the first keeps working; removing the first frees the name.
- A plugin that crashes three times (marked failed): its variables read as empty strings, keys redraw, and nothing shows an old value.
- `main` raising every tick still honours `interval`; `init` raising skips `main` but cards and actions keep working; `shutdown` stops `main` promptly even mid-interval.

---

### Task 1: Variable name, pattern and value helpers

**Files:**
- Create: `src/decker/common/variables.py`
- Modify: `src/decker/common/template.py` (add `template_names`)
- Test: `tests/common/test_variables.py`, `tests/common/test_template.py`

**Interfaces:**
- Produces (`decker.common.variables`):
  - constants `MAX_NAME_LENGTH = 64`, `MAX_VALUE_LENGTH = 1024`, `MAX_DECLARATIONS = 256`, `CORE_VARIABLE_NAMES: frozenset[str]` (from `TEMPLATE_VARIABLES`)
  - `is_valid_name(name: str) -> bool`
  - `is_valid_pattern(pattern: str) -> bool` — contains at least one `{placeholder}` (`[a-z][a-z0-9_]*`), unique placeholder names, no two placeholders adjacent, and the pattern with each placeholder replaced by `x` is a valid name.
  - `match_pattern(pattern: str, name: str) -> dict[str, str] | None` — placeholder values (each `[a-z0-9_]+`) or `None`.
  - `pattern_shape(pattern: str) -> str` — placeholders replaced by `{}` (identical shapes collide).
  - `value_text(value: Any) -> str | None` — `None` -> `None`; `str` as is; `bool` -> `"true"`/`"false"` (checked before `int`); `int`/`float` -> `str(value)`; any other type or text longer than `MAX_VALUE_LENGTH` raises `ValueError`.
- Produces (`decker.common.template`): `template_names(text: str) -> frozenset[str]` — the `{name}` tokens in text (not `{{`/`}}`).

- [ ] **Step 1: Write failing tests.** `test_variables.py`: `test_valid_names` (`media_volume`, `a1` valid; `Media`, `1a`, `` and a 65-character name invalid); `test_pattern_validity` (`media_{device}_volume` valid; `media_volume`, `{a}{b}`, `{a}_{a}`, `media_{Device}` invalid); `test_match_pattern` (`media_{device}_volume` matches `media_speakers_volume` -> `{"device": "speakers"}`, not `media_volume`, not `other_speakers_volume`); `test_pattern_shape_ignores_placeholder_names` (`a_{x}` and `a_{y}` equal shapes); `test_value_text` (`True` -> `"true"`, `3` -> `"3"`, `0.5` -> `"0.5"`, `None` -> `None`, `[1]` raises, 1025-character string raises). `test_template.py`: `template_names("a {x} {{y}} {z_1}")` is `{"x", "z_1"}`.
- [ ] **Step 2: Run** `uv run pytest tests/common/test_variables.py tests/common/test_template.py --no-cov` — expect FAIL.
- [ ] **Step 3: Implement** the module and `template_names` (reuse `_TOKEN`).
- [ ] **Step 4: Run** the same command — expect PASS.
- [ ] **Step 5: Commit** `feat: variable name, pattern and value helpers`.

### Task 2: `VariableStore`

**Files:**
- Create: `src/decker/server/variables.py`
- Test: `tests/server/test_variables.py`

**Interfaces:**
- Consumes: Task 1 helpers; `VariableSpec` is defined in Task 3, so this task defines it first in `decker/plugin/manifest.py` as `@dataclass(frozen=True) class VariableSpec: name: str | None; pattern: str | None; description: str = ""` (exactly one of `name`/`pattern` set). Task 3 adds parsing.
- Produces:
  - `class VariableConflict(Exception)`
  - `class VariableStore: __init__(self, on_change: Callable[[frozenset[str]], None] | None = None)`
    - `declare(plugin_id: str, specs: Sequence[VariableSpec]) -> None` — atomic; raises `VariableConflict` when a name equals another plugin's exact name, matches another plugin's pattern, a pattern's shape equals another plugin's, or collides with a core name.
    - `undeclare(plugin_id: str) -> None` — removes declarations, registrations and values; `on_change` gets the names that had a value.
    - `owner_of(name: str) -> str | None` — declaring plugin of an exact name or a matching pattern.
    - `register(plugin_id: str, name: str) -> bool` — concrete name inside the plugin's own pattern (exact declared names are always registered); `False` if refused.
    - `unregister(plugin_id: str, name: str) -> None` — drops registration and value.
    - `set_value(plugin_id: str, name: str, value: str | None) -> bool` — `False` unless the plugin owns the registered name; calls `on_change({name})` only when the stored value changes; `None` clears.
    - `drop_values(plugin_id: str) -> None` — plugin stopped: clears its values and its concrete registrations (exact declarations stay).
    - `registered_names(plugin_id: str) -> list[str]`; `snapshot() -> dict[str, str]` (set values only)
    - `view() -> Mapping[str, str]` — `.get(name, default)` returns the value, `""` for a declared-but-unset name (exact, or matching any declared pattern), else `default`.
    - `listing() -> list[dict[str, Any]]` — one dict per exact name and per registered concrete name: `name`, `pattern` (or `""`), `description`, `owner`, `value` (or `None`).
  - Thread-safe; never calls `on_change` while holding its lock.

- [ ] **Step 1: Write failing tests** (real store): `test_declare_exact_and_owner`; `test_declare_rejects_core_name`; `test_declare_rejects_name_owned_by_another_plugin`; `test_declare_rejects_name_matching_other_pattern`; `test_declare_rejects_identical_pattern_shape`; `test_declare_is_atomic` (a conflicting second spec leaves nothing declared); `test_register_concrete_in_own_pattern_only`; `test_set_value_only_by_owner` and `test_set_value_none_clears`; `test_on_change_only_when_value_changes`; `test_drop_values_keeps_exact_declarations_drops_concrete`; `test_undeclare_frees_name_for_another_plugin`; `test_view_returns_empty_for_declared_unset_and_default_otherwise`; `test_snapshot_only_set_values`; `test_value_text_expansion_is_not_recursive` (value `"{page_name}"` expanded via `expand_template(text, store.view())` yields the literal text).
- [ ] **Step 2: Run** `uv run pytest tests/server/test_variables.py --no-cov` — expect FAIL.
- [ ] **Step 3: Implement** `VariableStore` and `VariableSpec`.
- [ ] **Step 4: Run** — expect PASS.
- [ ] **Step 5: Commit** `feat: VariableStore owns declared variables and cached values`.

### Task 3: Manifest `contributes.variables` and the contribution handler

**Files:**
- Modify: `src/decker/plugin/manifest.py` (`KNOWN_CONTRIBUTION_KINDS`, `PluginManifest.variables`, `_parse_variable`, the "contributes no cards, actions or icon packs" check)
- Modify: `src/decker/server/contributions.py` (`contributed_kinds`)
- Modify: `src/decker/server/plugins.py` (`_VariablesHandler`, `PluginManager._variables: VariableStore`, registry list)
- Test: `tests/plugin/test_manifest.py`, `tests/server/test_contributions.py`, `tests/server/test_plugins_variables.py`

**Interfaces:**
- Consumes: Task 1 helpers, Task 2 `VariableStore`/`VariableSpec`/`VariableConflict`.
- Produces: `PluginManifest.variables: tuple[VariableSpec, ...]`; `PluginManager.variables: VariableStore` (public attribute); manifest rules: entries have exactly one of `name`/`pattern` (valid), no duplicates within the plugin, count <= `MAX_DECLARATIONS`, no core name (and no pattern matching a core name), a `runtime` is required, and a `decker` constraint must be declared (`ManifestValidationError` otherwise). A plugin that contributes only variables is valid.

- [ ] **Step 1: Write failing tests.** `test_manifest.py`: variables parse (`{"name": "media_volume", "description": "x"}` and `{"pattern": "media_{device}_volume"}`); `test_variables_need_runtime`; `test_variables_need_decker_constraint`; `test_variable_core_name_rejected`; `test_variable_pattern_matching_core_name_rejected` (`page_{x}`); `test_duplicate_variable_in_plugin_rejected`; `test_variables_only_plugin_is_valid`. `test_plugins_variables.py` (real `PluginManager` as in `tests/server/test_plugins.py`): `test_adding_plugin_declares_variables`; `test_second_plugin_with_same_name_fails_to_load_and_first_keeps_working` (a recorded `PluginLoadFailedEvent`); `test_removing_plugin_frees_its_names`.
- [ ] **Step 2: Run** `uv run pytest tests/plugin/test_manifest.py tests/server/test_contributions.py tests/server/test_plugins_variables.py --no-cov` — expect FAIL.
- [ ] **Step 3: Implement.** `_VariablesHandler` (`kind = "variables"`) registers the plugin's runtime like `_CardsHandler` (`_register_runtime`) and calls `store.declare`; `unregister` calls `store.undeclare` and `supervisor.unregister`. Update `ContributionRegistry`'s kind set via `KNOWN_CONTRIBUTION_KINDS`.
- [ ] **Step 4: Run** the Step 2 command and `tests/server`, `tests/plugin` — expect PASS.
- [ ] **Step 5: Commit** `feat: contributes.variables in the manifest, declared through the contribution registry`.

### Task 4: SDK lifecycle and variable API

**Files:**
- Modify: `src/decker_plugin_sdk/_runtime.py`, `src/decker_plugin_sdk/__init__.py`
- Create: `src/decker_plugin_sdk/_variables.py` (decorators, `PluginContext`, module-level helpers, lifecycle threads)
- Test: `tests/sdk/test_runtime.py` (follow its fixtures), `tests/sdk/test_variables.py`

**Interfaces:**
- Produces (exported from `decker_plugin_sdk`): decorators `init` (bare), `main` (bare or `main(interval: float | None = 2.0)`), `variable(pattern_or_name: str)`; `class PluginContext` with `register_variable(name: str) -> None`, `unregister_variable(name: str) -> None`, `signal_variable_updated(name: str) -> None`, `get_variable(name: str) -> str | None`, `has_variable(name: str) -> bool`, `log(message: str, level: str = "info") -> None`; module-level functions with the same five variable names.
- Getter contract: `@variable("exact_name")` takes no arguments; `@variable("pattern_{device}")` takes the placeholder values as keyword arguments (`device="speakers"`). A getter may be sync or async and returns `str | int | float | bool | None`.
- Runtime behaviour:
  - After sending `ready`, the runtime starts a lifecycle thread: `init(ctx)` once (sync, or `asyncio.run` for async), then `main(ctx)` repeatedly with `interval` seconds between calls, or once if `interval is None` for an async `main`. If there is no `main`, the thread ends. If `init` raises, log an error event and do not start `main`. A `main` exception is logged and the loop continues. `shutdown` stops the loop promptly (interruptible wait; async `main` cancelled).
  - `get_variable` events (request, name) are answered in the existing worker pool with `variable_value` (`ok`/`value`, or `ok: false` with an error). Values go through `value_text` (invalid -> `ok: false`).
  - `variables_changed` events update the local copy (`set` merges, `removed` deletes) backing `get_variable`/`has_variable`; `signal_variable_updated(name)` evaluates the plugin's own getter, updates the local copy and sends `variable_updated`.
  - `register_variable(name)`/`unregister_variable(name)` send the events (`register_variable` validates that a matching `@variable` getter exists, else logs a warning and sends nothing).

- [ ] **Step 1: Write failing tests** with an in-memory stdin/stdout like `test_runtime.py`: `test_init_runs_after_ready_in_its_own_thread`; `test_init_exception_skips_main_but_actions_still_run`; `test_main_called_at_interval` (interval 0.05, count calls); `test_main_exception_is_logged_and_loop_continues`; `test_shutdown_stops_main_promptly` (interval 5 s, shutdown returns within 1 s); `test_async_main_without_interval_runs_once`; `test_get_variable_request_answered_exact` and `..._pattern_passes_placeholders`; `test_getter_raising_answers_not_ok`; `test_variables_changed_feeds_get_and_has_variable`; `test_signal_sends_variable_updated_and_updates_local_copy`; `test_register_without_matching_getter_sends_nothing`.
- [ ] **Step 2: Run** `uv run pytest tests/sdk --no-cov` — expect FAIL.
- [ ] **Step 3: Implement.** Keep `_runtime.py` changes small by putting the registry, context and lifecycle in `_variables.py`; the module-level helpers talk to the running `_Runtime` through a module-level handle set in `run`.
- [ ] **Step 4: Run** `uv run pytest tests/sdk --no-cov` — expect PASS.
- [ ] **Step 5: Commit** `feat: SDK init, main and variable hooks with a variable API`.

### Task 5: Server protocol handling, value cache and pushes

**Files:**
- Create: `src/decker/server/variable_runner.py`
- Modify: `src/decker/plugin/protocol.py` (`PROTOCOL_VERSION = 2`), `src/decker/server/plugins.py` (hello uses `PROTOCOL_VERSION`; `_route_message`; `_on_ready`)
- Test: `tests/server/test_variable_runner.py`, `tests/server/test_plugins_variables.py`

**Interfaces:**
- Consumes: Task 2 `VariableStore`, Task 3 `PluginManager.variables`, Task 4 wire events.
- Produces:
  - `class VariableRunner: __init__(self, supervisor: PluginSupervisor, store: VariableStore, timeout: float = 5.0)`; `ask(plugin_id: str, name: str) -> None` (off-thread; sends `get_variable` with a request id and waits up to `timeout`, then `store.set_value`; a failed or timed-out ask keeps the old value and logs once); `on_value(plugin_id: str, payload: Mapping[str, Any]) -> None`; `plugin_stopped(plugin_id: str) -> None` (releases pending asks); `push(plugin_id: str | None, changed: Mapping[str, str], removed: Sequence[str]) -> None` (`variables_changed` to one ready plugin, or to every ready plugin if `None`).
  - `PluginManager` routing: `register_variable` -> `store.register` then `ask`; `unregister_variable` -> `store.unregister` and push removal; `variable_updated` -> `ask` (only for the owner and a registered name); `variable_value` -> `runner.on_value`. Each store change pushes `variables_changed` to all ready plugins. On a plugin's `ready`: send the full snapshot, then `ask` for each of `store.registered_names(plugin_id)`.

- [ ] **Step 1: Write failing tests** (real supervisor with a stub process factory as in `tests/plugin/runtime/test_supervisor.py`, or the real fixture plugin if simpler): `test_ask_sets_value_from_variable_value`; `test_ask_timeout_keeps_old_value`; `test_ask_not_ok_keeps_old_value_and_logs_once`; `test_update_from_non_owner_is_ignored`; `test_variable_updated_triggers_ask`; `test_register_concrete_name_triggers_ask`; `test_change_pushes_variables_changed_to_ready_plugins`; `test_ready_sends_snapshot_then_asks_registered_names`; `test_plugin_stopped_releases_pending_ask`; `test_hello_protocol_is_2`.
- [ ] **Step 2: Run** `uv run pytest tests/server/test_variable_runner.py tests/server/test_plugins_variables.py --no-cov` — expect FAIL.
- [ ] **Step 3: Implement** `VariableRunner` and the routing; `_on_plugin_message` stays exception-safe as today.
- [ ] **Step 4: Run** the Step 2 command and `tests/plugin` — expect PASS.
- [ ] **Step 5: Commit** `feat: server handles plugin variable events, caches values and pushes changes`.

### Task 6: Always-on plugins, drop on stop, expansion and key redraws

**Files:**
- Modify: `src/decker/plugin/runtime/supervisor.py` (`on_exit` callback attribute), `src/decker/server/plugins.py` (`template_variables`, `refresh_variable_users`, always-on acquire, drop on exit), `src/decker/server/page_vars.py` only if needed
- Test: `tests/plugin/runtime/test_supervisor.py`, `tests/server/test_plugins_variables.py`

**Interfaces:**
- Consumes: Task 2 `view()`/`snapshot()`, Task 5 runner.
- Produces:
  - `PluginSupervisor.on_exit: Callable[[str], None] | None` — called with the plugin id whenever its process ends (stop, crash, kill, watchdog), after the process is gone; the manager sets it to drop the plugin's values (`store.drop_values`, `runner.plugin_stopped`, push removals, redraw users).
  - `PluginManager.template_variables(device_id: str) -> Mapping[str, str]` — page and profile variables win over global ones; the global part is `store.view()` so declared-unset names expand to `""`. Used wherever `page_variables` is used for expansion today (`_expanded_appearance`, `delivered_settings`/`_delivery`).
  - `PluginManager.refresh_variable_users(names: frozenset[str]) -> None` — recomposes/redelivers every live key whose templated text (`template_names`) references one of `names`; the store's `on_change` calls it.
  - A plugin with `manifest.variables` non-empty is acquired once at `add_plugin` (permanent reference, never released until removal) so it starts with the server.

- [ ] **Step 1: Write failing tests.** Supervisor: `test_on_exit_called_after_crash_and_after_stop`. Manager: `test_plugin_with_variables_starts_without_a_card` (process started after `add_plugin`/`create`); `test_plugin_without_variables_stays_lazy`; `test_value_appears_in_key_title_template` (title `Vol {media_volume}` -> `Vol 40` after the value is set); `test_value_change_redraws_only_keys_using_it`; `test_unset_declared_variable_expands_to_empty_string`; `test_undeclared_name_stays_as_typed`; `test_page_variable_wins_over_plugin_variable_of_same_name` (cannot be declared, so assert core names stay server-owned); `test_value_with_braces_not_reexpanded`; `test_process_exit_drops_values_and_redraws`; `test_restart_restores_values_after_init`; `test_removing_plugin_drops_values_and_stops_process`.
- [ ] **Step 2: Run** `uv run pytest tests/plugin/runtime/test_supervisor.py tests/server/test_plugins_variables.py --no-cov` — expect FAIL.
- [ ] **Step 3: Implement.** `on_exit` is an attribute set after construction (the constructor is at the argument limit).
- [ ] **Step 4: Run** the Step 2 command and `tests/server` — expect PASS.
- [ ] **Step 5: Commit** `feat: always-on variable plugins, value expansion and key redraws`.

### Task 7: End-to-end through a real plugin process

**Files:**
- Create: `tests/server/fixtures/variable_plugin/` (manifest + `plugin.py` using the SDK: declares `test_counter` and `test_{item}_value`; `init` registers `test_alpha_value`; `main(interval=0.1)` bumps a counter and signals; one action `…bump`)
- Test: `tests/server/test_variables_e2e.py`

**Interfaces:**
- Consumes: Tasks 1-6 (real `PluginManager`, real supervisor, real SDK process).

- [ ] **Step 1: Write failing tests:** `test_values_flow_from_plugin_to_expansion` (wait for `test_counter` > 0 and for `test_alpha_value`); `test_signal_from_action_updates_expansion`; `test_killing_the_process_clears_then_restores_values`; `test_slow_getter_does_not_block_other_variables` (a getter sleeping past the timeout, shortened for the test); `test_shutdown_stops_main`.
- [ ] **Step 2: Run** `uv run pytest tests/server/test_variables_e2e.py --no-cov` — expect FAIL.
- [ ] **Step 3: Build the fixture plugin** and fix whatever the end-to-end run exposes in Tasks 1-6 (report any change to earlier tasks).
- [ ] **Step 4: Run** — expect PASS; run it 3 times to check it is not flaky.
- [ ] **Step 5: Commit** `test: plugin variables end to end through a real plugin process`.

### Task 8: RPC, docs and gates

**Files:**
- Modify: `src/decker/server/service.py` (`variables_list`), docs: `docs/plugins/protocol.md`, `package-and-manifest.md`, `sdk-quickstart.md`, `settings-schema.md`, `limits.md`; `CLAUDE.md`; `README.md`
- Test: `tests/server/test_service*.py` (follow the existing `plugins_actions_list` test), `tests/cli` only if commands are enumerated there

**Interfaces:**
- Produces: `DeckerService.variables_list() -> list` (`@exposed @api_response`, like `plugins_actions_list`) returning `PluginManager.variables.listing()`; `[]` with no context.

- [ ] **Step 1: Write the failing test:** `test_variables_list_returns_declared_and_registered_with_values`.
- [ ] **Step 2: Run** it — expect FAIL; **implement** `variables_list`; run — expect PASS.
- [ ] **Step 3: Docs.** `protocol.md`: the six new events and `hello.protocol: 2`; `package-and-manifest.md`: `contributes.variables`, the `decker` constraint, always-on behaviour; `sdk-quickstart.md`: `@init`, `@main`, `@variable`, the helpers, a worked example; `settings-schema.md`: the `template` note and the available variables; `limits.md`: the three limits and the always-on lifecycle line; `CLAUDE.md` plugins paragraph and the `variables_list` RPC; `README.md` features. Keep each concise and in the neighbouring style.
- [ ] **Step 4: Gates:** `poe format && poe mypy && poe pylint && poe test` — pylint >= 9.0, coverage >= 85%; the only known failure is `tests/server/test_builtin_plugins.py::test_blank_version_is_deckers` (pre-existing, unrelated).
- [ ] **Step 5: Commit** `feat: variables_list RPC; plugin variables in the plugin docs, CLAUDE.md and README`.
