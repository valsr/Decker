# Page Navigation (Decker side) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give plugins what page-navigation plugins need: opt-in `{variable}` templating (page name/index/count), a `page` settings dropdown, a `switch_page` protocol event, static (appearance-only) actions, and a built-in Blank action; bump Decker to 0.4.0.

**Architecture:** A pure `common/template.py` expands `{name}` text. Fields opt in with `"template": true` in the settings schema (Decker's own key title opts in). `PluginManager` builds page variables for a live key's device, expands the title when drawing and an expanded/page-resolved copy of the settings when delivering them to a plugin (stored settings stay raw), and refreshes both when a device's pages change. `switch_page` is routed outside the manager lock into `PageController.activate`. Static actions (`"static": true`) activate without a process. A read-only built-in plugin folder ships `com.decker.blank`.

**Tech Stack:** Python 3.14, PyQt6, pytest + assertpy, poetry/poe.

**Spec:** `docs/superpowers/specs/2026-11-17-page-navigation-design.md`

## Global Constraints

- Template syntax: `{name}` with `name` matching `[a-z_][a-z0-9_]*`; `{{` and `}}` are literal braces; an unknown name is left exactly as typed; one pass, no recursion, no format specs, no evaluation. Variables: `page_name`, `page_index` (1-based), `page_count`, for the key's device.
- Templating is **opt-in**: only `text` / `text_style` fields with `"template": true` (default false) and Decker's own appearance `title` (declared `template: true`). Stored settings stay raw; only drawing and delivery to plugins expand.
- `page` settings type: stored value a string page id (default `""`); delivered to plugins as `{"page_id": str, "name": str, "index": int}` (`index` 1-based); unset/deleted page -> `{"page_id": "", "name": "", "index": 0}`. Rejected in `global_settings`.
- `switch_page` payload: `{"to": "next"|"previous"|"first"|"last", "wrap": bool}` or `{"page_id": str}`; resolved for the sending context's device; unknown page, a single page, or a non-wrapping edge are logged and ignored; handled outside the manager lock.
- Static actions: manifest action key `"static": true`; may not declare `settings` or `gestures`; `runtime` is optional when every action is static; a static action starts no process, gets no `will_appear`, and ignores presses.
- Built-in plugin ids are reserved: install, update and repository installs of a built-in id are refused; Settings, Plugins shows no Uninstall for them.
- Decker 0.4.0 (`pyproject.toml`); `decker-plugins`'s `com.decker.pages` will declare `">=0.4"`.
- Never take the `PageController` lock from the plugin manager: use `page_controller.active_page_id(device_id)` (lock-free) and `page_store.list_pages(device_id)`.
- Conventions: black 120, full annotations, <= 50-line methods, <= 5 args, mypy, pylint (no new warnings), coverage >= 85%; `poe format` first; add files by **explicit path** (never `git add -A`/`src`/`docs` wildcards). Branch `feat/page-navigation` from `main`. Never push or open a PR without asking.

## Review Focus

- A text with braces that is not a template (`{id}`, `{{x}}`, `}{`, a lone `{`, JSON, an unclosed `{page_name`): unchanged or correctly unescaped, never an exception. (Tasks 2, 6)
- A field that did not opt in is never expanded, including user settings that happen to contain `{page_name}`; the stored raw template is never overwritten by delivery. (Task 6)
- A page renamed, added or deleted while keys on that device are live: titles and delivered settings update, no duplicate `settings_changed` when nothing changed. (Task 6)
- `switch_page` from the key being deactivated by the switch itself (the sender's context disappears mid-handler), concurrent presses, and deadlock-freedom with `PageController`. (Task 7)
- A static action: press, long press, deactivate, uninstall and failed-plugin paths must not call into a supervisor that has no entry for it. (Task 5)
- Hand-edited manifests/settings: `static` with settings, `page` in global settings, `template` on an int field, `{"page_id": 5}`, a page id belonging to another device. (Tasks 3, 4, 6)

---

### Task 1: Branch, docs, Decker 0.4.0

**Files:**
- Modify: `pyproject.toml` (`version = "0.4.0"`), `docs/plugins/protocol.md` (hello example), `tests/common/test_version.py` (the 0.3.0 pin test)

- [ ] **Step 1: Branch** `git switch -c feat/page-navigation main`; commit the design and both plans by explicit path (`git add docs/superpowers/specs/2026-11-17-page-navigation-design.md docs/superpowers/plans/2026-11-17-page-navigation.md docs/superpowers/plans/2026-11-17-pages-plugin.md`).
- [ ] **Step 2: Failing test** — change `test_package_declares_0_3_0` to `test_package_declares_0_4_0` (`tomllib` reads `pyproject.toml`; `== "0.4.0"`) and extend `test_gates_across_the_0_3_bump` with `is_compatible(">=0.4", "0.3.0")` false and `is_compatible(">=0.4", "0.4.0")` true.
- [ ] **Step 3: Run** `poetry run pytest tests/common/test_version.py -q` — Expected: FAIL.
- [ ] **Step 4: Implement** the version bump; run `poetry install --only-root` so the installed metadata reports 0.4.0.
- [ ] **Step 5: Run** the test file plus `poetry run python -c "from decker.common.version import decker_version as v; print(v())"` — Expected: PASS and `0.4.0`.
- [ ] **Step 6: Commit** `chore: Decker 0.4.0`.

### Task 2: Template expansion

**Files:**
- Create: `src/decker/common/template.py`, `tests/common/test_template.py`

**Interfaces:**
- Produces: `expand_template(text: str, variables: Mapping[str, str]) -> str`; `TEMPLATE_VARIABLES: tuple[str, ...] = ("page_name", "page_index", "page_count")` (documentation/validation only).

- [ ] **Step 1: Failing tests** — `test_replaces_known_variables`, `test_unknown_names_are_left_as_typed`, `test_double_braces_are_literal` (`"{{page_name}}"` -> `"{page_name}"`, `"}}"` -> `"}"`), `test_no_recursion` (a value containing `{page_name}` is not expanded again), `test_plain_text_is_unchanged`, `test_malformed_braces_never_raise` (parametrised: `"{"`, `"}"`, `"{}"`, `"{ page_name }"`, `"{page_name"`, `"page_name}"`, `"{{{page_name}}}"`, `"{page-name}"`, `"{Page_Name}"`), `test_values_are_inserted_verbatim` (a value with braces/backslashes/emoji is not interpreted), `test_empty_text_and_empty_variables`, `test_very_long_text_is_linear` (200k characters finishes quickly).
- [ ] **Step 2: Run** `poetry run pytest tests/common/test_template.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** with one compiled regex alternation (`\{\{|\}\}|\{([a-z_][a-z0-9_]*)\}`) and a single `re.sub` callback.
- [ ] **Step 4: Run** the same command — Expected: PASS.
- [ ] **Step 5: Commit** `feat(common): template expansion for key text`.

### Task 3: Schema — `template` flag and `page` type

**Files:**
- Modify: `src/decker/plugin/settings_schema.py`, `src/decker/plugin/manifest.py` (reject `page` in `global_settings`), `src/decker/common/appearance_schema.py` (title `template: True`)
- Test: `tests/plugin/test_settings_schema.py`, `tests/plugin/test_manifest.py`, `tests/server/test_appearance.py`

**Interfaces:**
- Produces: `text` and `text_style` entries accept `"template": bool` (stored in `SettingField.extra["template"]`, round-trips through `schema_to_json`); `FIELD_TYPES += "page"`; a `page` field's value is a string (`""` default, non-strings coerce to the default); `PluginManifest.from_dict` raises `ManifestValidationError` naming the field when `global_settings` contains a `page` field. `APPEARANCE_SCHEMA["title"]` carries `"template": True`.

- [ ] **Step 1: Failing tests** — `test_template_flag_accepted_on_text_and_text_style`, `test_template_flag_must_be_boolean`, `test_template_flag_rejected_on_other_types` (an `int` field with `template` is an error), `test_template_round_trips_through_schema_to_json`, `test_page_type_defaults_to_empty_string`, `test_page_value_coerces_non_strings_to_default` (`5`, `None`, `["x"]`), `test_page_default_must_be_a_string`, `test_page_in_global_settings_is_rejected` (manifest-level), `test_page_in_action_settings_is_accepted`, `test_appearance_title_opts_in_to_templates`.
- [ ] **Step 2: Run** `poetry run pytest tests/plugin tests/server/test_appearance.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** (`_EXTRA_KEYS["text"] += "template"`, add `"text_style": ("template",)`, bool validation like `multiline`, `_ZERO_VALUES["page"] = ""`, `_coerce` page branch).
- [ ] **Step 4: Run** `poetry run pytest tests/plugin tests/common tests/server/test_appearance.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(plugin): template flag on text fields and a page settings type`.

### Task 4: Static actions in the manifest

**Files:**
- Modify: `src/decker/plugin/manifest.py` (`ActionSpec.static`, `_parse_action`, the actions-need-runtime check)
- Test: `tests/plugin/test_manifest.py`

**Interfaces:**
- Produces: `ActionSpec.static: bool = False`; `"static": true` accepted (must be a bool); a static action declaring `settings` or `gestures` -> `ManifestValidationError`; a manifest without `runtime` is valid iff every action is static (otherwise the existing "declares no runtime" error, now naming the first non-static action); a manifest with `runtime` may mix static and normal actions.

- [ ] **Step 1: Failing tests** — `test_static_action_without_runtime_is_valid`, `test_non_static_action_without_runtime_is_still_rejected`, `test_mixed_actions_with_runtime`, `test_static_must_be_boolean`, `test_static_action_with_settings_rejected`, `test_static_action_with_gestures_rejected`, `test_static_action_keeps_appearance_defaults_and_states` (a preset with `appearance: {"title": {"text": "{page_index}"}}` parses and the default is kept verbatim).
- [ ] **Step 2: Run** `poetry run pytest tests/plugin/test_manifest.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `poetry run pytest tests/plugin -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(plugin): static actions in manifests`.

### Task 5: Activating static actions

**Files:**
- Modify: `src/decker/server/plugins.py` (`activate_action`, `deactivate_action`, `dispatch_key_down`, `dispatch_key_up`, `dispatch_settings_changed`, `_send_will_appear` callers)
- Test: `tests/server/test_plugins.py`

**Interfaces:**
- Consumes: `ActionSpec.static` (Task 4).
- Produces: `activate_action` for a static action creates the `_Live`, composes the key (appearance defaults + user appearance + `states[0]`), and does **not** call `supervisor.acquire` or send `will_appear`; `deactivate_action`, key down/up and `dispatch_settings_changed` for it never call the supervisor; a static plugin with no runtime needs no `register_actions` entry; `list_actions` includes static actions unchanged.

- [ ] **Step 1: Failing tests** (extend the `Env` fixture with a no-runtime plugin whose manifest has a static action `com.t.static.preset` with `appearance: {"background": "#336699", "title": {"text": "Hi", "position": "middle"}}`): `test_static_action_draws_its_appearance` (corner pixel is the background; title pixels present), `test_static_action_starts_no_process_and_sends_nothing` (no supervisor entry, no `will_appear` in the recorder log), `test_press_and_long_press_on_a_static_key_do_nothing`, `test_deactivating_a_static_key_does_not_touch_the_supervisor`, `test_user_appearance_overrides_the_static_defaults`, `test_static_action_in_a_runtime_plugin_does_not_start_the_process` (a plugin with `runtime` and one static action: activating only the static action never starts the process), `test_static_action_listed_in_list_actions`.
- [ ] **Step 2: Run** `poetry run pytest tests/server/test_plugins.py -q -k static` — Expected: FAIL.
- [ ] **Step 3: Implement** a `_is_static(live)` guard; skip supervisor calls for static lives; `activate_action` takes the static path before the `runtime is None` rejection.
- [ ] **Step 4: Run** `poetry run pytest tests/server -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(server): activate static actions without a process`.

### Task 6: Page variables, expansion and refresh

**Files:**
- Modify: `src/decker/server/plugins.py` (`create`, `_compose`, `_send_will_appear`, `dispatch_settings_changed`, new helpers), `src/decker/server/page_controller.py` (`_notify`), `tests/server/test_plugins.py` (the `Env` context gains `page_store`), `tests/server/test_page_controller.py`
- Test: `tests/server/test_plugins.py`, `tests/server/test_page_controller.py`

**Interfaces:**
- Consumes: `expand_template` (Task 2), schema `template`/`page` (Task 3), static activation (Task 5).
- Produces on `PluginManager`:
  - `page_variables(device_id: str) -> dict[str, str]` — `{"page_name", "page_index", "page_count"}` of the device's active page (`page_controller.active_page_id` + `page_store.list_pages`; `{}` when pages are unavailable).
  - `_compose` expands `appearance["title"]["text"]` (the user title only, not the plugin's fallback title).
  - `delivered_settings(live: _Live) -> dict[str, Any]` — a copy of `live.settings` in which `text`/`text_style` fields with `template: true` are expanded (for `text_style` only its `text`) and `page` fields are resolved to `{"page_id","name","index"}` for the key's device; used by `will_appear` and `settings_changed`. `live.settings` itself stays raw.
  - `refresh_page_dependent(device_id: str) -> None` — for each live key on the device: recompose when its raw title text contains `{`; re-send `settings_changed` only when the action's schema has `template`/`page` fields and the delivered settings differ from those last sent (`_Live.delivered`).
  - `PageController._notify(device_id)` calls `plugin_manager.refresh_page_dependent(device_id)` after pushing `pages_changed` (outside its lock).

- [ ] **Step 1: Failing tests** — expansion: `test_title_template_is_expanded_when_drawn` (stored `{"title": {"text": "{page_index}/{page_count}"}}`, three pages, second active -> the drawn title equals the drawing of the literal `"2/3"`; compare composed PNG bytes), `test_unknown_and_escaped_braces_in_the_title`, `test_plugin_fallback_title_is_not_expanded`, `test_title_without_pages_keeps_text_literal`; delivery: `test_opted_in_text_field_is_delivered_expanded` (schema `{"key":"label","type":"text","template":true}`, stored `"On {page_name}"` -> `will_appear.settings.label == "On Settings"`, stored value still raw), `test_not_opted_in_field_is_delivered_verbatim`, `test_text_style_text_is_expanded_other_fields_untouched`, `test_page_field_is_resolved_to_id_name_index`, `test_deleted_or_unset_or_foreign_page_resolves_to_empty` (also `{"page_id": 5}`-style garbage), `test_settings_changed_delivers_the_expanded_copy`, `test_set_settings_from_a_plugin_does_not_store_expanded_text` (a plugin writing back only changed keys keeps other templates raw); refresh: `test_rename_refreshes_title_and_settings` (rename a page -> recompose and one `settings_changed` with the new name), `test_no_duplicate_settings_changed_when_nothing_changed`, `test_other_devices_are_untouched`, `test_keys_without_templates_are_not_recomposed` (count `compose_key_image` calls via monkeypatch), `test_page_switch_redraws_keys_with_the_new_variables`; controller: `test_notify_refreshes_the_plugin_manager` (`add_page`, `rename_page`, `delete_page`, `activate` each call `refresh_page_dependent(device_id)` once, outside the controller lock).
- [ ] **Step 2: Run** `poetry run pytest tests/server/test_plugins.py tests/server/test_page_controller.py -q -k "template or page_ or refresh or notify or delivered"` — Expected: FAIL.
- [ ] **Step 3: Implement**; store `page_controller` and `page_store` from the context in `create`; keep each new method under 50 lines by splitting field-walking into a private helper.
- [ ] **Step 4: Run** `poetry run pytest tests/server -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(server): page variables, opt-in template expansion and page-aware refresh`.

### Task 7: `switch_page` protocol and SDK

**Files:**
- Modify: `src/decker/server/plugins.py` (`_route_context_message`, new `_on_switch_page`), `src/decker_plugin_sdk/_context.py`, `docs/plugins/protocol.md`, `docs/plugins/sdk-quickstart.md`
- Test: `tests/server/test_plugins.py`, `tests/sdk/test_runtime.py`

**Interfaces:**
- Consumes: `PageController.activate`, `page_store.list_pages`.
- Produces:
  - `PluginManager._on_switch_page(live: _Live, payload: dict[str, Any]) -> None` — resolves the target for `live.target.device_id` (`next`/`previous` with optional `wrap`, `first`, `last`, or `page_id`) and calls `page_controller.activate`; invoked from `_route_context_message` **after** the manager lock is released.
  - SDK: `ActionContext.switch_page(to: str = "next", wrap: bool = False) -> None` and `ActionContext.go_to_page(page_id: str) -> None`, emitting `switch_page` with `{"to": ..., "wrap": ...}` / `{"page_id": ...}`.

- [ ] **Step 1: Failing tests** — server: `test_next_goes_to_the_following_page`, `test_previous_goes_to_the_preceding_page`, `test_next_on_the_last_page_stays_unless_wrapping`, `test_wrap_goes_from_last_to_first_and_first_to_last`, `test_first_and_last`, `test_page_id_goes_to_that_page`, `test_unknown_page_id_is_ignored_and_logged`, `test_single_page_is_a_no_op`, `test_bad_payloads_are_ignored` (parametrised: `{}`, `{"to": "sideways"}`, `{"to": 5}`, `{"page_id": 7}`, `{"to": "next", "wrap": "yes"}` -> treated as no wrap), `test_page_of_another_device_is_not_reachable` (a `page_id` that belongs to a different device is ignored), `test_message_from_an_inactive_context_is_dropped`, `test_switch_does_not_hold_the_manager_lock` (patch `activate` to try `manager._lock.acquire(timeout=1)` from another thread and assert it succeeds), `test_a_key_can_switch_away_from_its_own_page` (the sender is deactivated by the switch; no exception, its page's keys are hidden and the new page's shown); SDK: `test_switch_page_emits_to_and_wrap`, `test_switch_page_defaults`, `test_go_to_page_emits_page_id`.
- [ ] **Step 2: Run** `poetry run pytest tests/server/test_plugins.py tests/sdk -q -k "switch or page"` — Expected: FAIL.
- [ ] **Step 3: Implement**; document the event in `protocol.md` (Plugin to server table + a short "Pages" section) and the two SDK methods in `sdk-quickstart.md`.
- [ ] **Step 4: Run** `poetry run pytest tests/server tests/sdk -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(server): switch_page protocol event and SDK methods`.

### Task 8: Built-in Blank

**Files:**
- Create: `src/decker/builtin_plugins/com.decker.blank/manifest.json`, `src/decker/builtin_plugins/com.decker.blank/icons/blank.png` (generate with Pillow), `tests/server/test_builtin_plugins.py`
- Modify: `src/decker/plugin/loader.py` (`PluginLoader` gains a built-in folder scan), `src/decker/server/plugins.py` (`create`, a `builtin` marker), `src/decker/server/plugin_installer.py`, `src/decker/server/repositories.py`/`update_checker.py` (ignore repository plugins with a built-in id), `src/decker/server/service.py` (`_plugin_info` adds `"builtin": bool`), `src/decker/client/widgets/plugins_tab.py` (no Uninstall for built-ins), `CLAUDE.md`, `docs/plugins/README.md`, `docs/plugins/package-and-manifest.md`
- Test: `tests/server/test_builtin_plugins.py`, `tests/plugin/test_loader.py`, `tests/server/test_plugin_installer.py`, `tests/client/widgets/test_plugins_tab.py`

**Interfaces:**
- Produces: `BUILTIN_PLUGINS_DIR: Path` (the package folder); `PluginLoader.scan_builtin() -> PluginScanResult`; `PluginManager.is_builtin(plugin_id: str) -> bool`; `plugins_list` entries gain `"builtin": bool`; installing, updating or repository-installing a built-in id raises `PluginInstallError("<id> is built into Decker")`; uninstalling one likewise. The Blank manifest: id `com.decker.blank`, name "Blank", version = Decker's, one static action `com.decker.blank.blank` ("Blank", tooltip "Draws only the background and title"), no runtime.

- [ ] **Step 1: Failing tests** — `test_blank_is_loaded_and_listed` (action list contains `com.decker.blank.blank`), `test_blank_key_draws_background_and_title_only`, `test_builtin_cannot_be_uninstalled`, `test_builtin_cannot_be_replaced_by_a_package_with_its_id`, `test_user_folder_with_a_builtin_id_is_refused_as_duplicate_and_the_builtin_wins`, `test_repository_plugin_with_a_builtin_id_is_ignored_with_a_warning` (catalog entry not installable, no crash), `test_plugins_list_marks_builtin`, client: `test_uninstall_button_is_disabled_for_builtin_plugins`, `test_blank_manifest_ships_in_the_package` (the file exists next to `loader.py`'s package and parses), `test_blank_icon_resolves`.
- [ ] **Step 2: Run** `poetry run pytest tests/server/test_builtin_plugins.py tests/plugin/test_loader.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement**; the built-in is added before the user plugins in `create`, so a user folder with the same id hits the existing "duplicate plugin id" failure path.
- [ ] **Step 4: Run** `poetry run pytest tests -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: built-in static Blank plugin`.

### Task 9: `page` dropdown in the config form

**Files:**
- Create: `src/decker/client/widgets/page_edit.py`, `tests/client/widgets/test_page_edit.py`
- Modify: `src/decker/client/widgets/schema_form.py` (`_BUILDERS["page"]`), `tests/client/widgets/test_schema_form.py`

**Interfaces:**
- Consumes: the `pages_list` RPC (`device_id` -> `{pages: [{page_id, name}], ...}`), `AppContext.get().active_device_id`, `to_plain`.
- Produces: `PageEdit(device_id: Callable[[], str | None] | None = None, rpc: Callable[[], RpcCaller | None] | None = None, parent: QWidget | None = None)` — a `QComboBox`; `value() -> str` (page id, `""` for none), `set_value(value: Any) -> None` (any non-string -> `""`; emits nothing), `value_changed = pyqtSignal()` on user selection. Items: "(no page)" for `""`, then the device's pages in order with their names; a stored id that no longer exists shows a disabled "(deleted page)" item and keeps its id as the value. No device or no connection -> only the "(no page)" item and a tooltip "Select a key on a device first". Default providers use `AppContext`.

- [ ] **Step 1: Failing tests** — `test_lists_the_devices_pages_in_order_with_a_no_page_entry`, `test_value_is_the_page_id_not_the_name`, `test_selecting_emits_value_changed_and_updates_value`, `test_set_value_emits_nothing`, `test_unknown_stored_id_shows_deleted_page_and_keeps_the_value`, `test_garbage_value_becomes_no_page` (`5`, `None`, `{"x": 1}`), `test_no_device_or_connection_does_not_crash`, `test_rpc_failure_does_not_crash`, `test_renamed_page_shows_its_new_name_after_reload` (calling `reload()` re-reads), `test_schema_form_builds_a_page_edit_and_round_trips` (in `test_schema_form.py`).
- [ ] **Step 2: Run** `poetry run pytest tests/client/widgets/test_page_edit.py tests/client/widgets/test_schema_form.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `PageEdit` (public `reload()` re-queries; the constructor calls it) and register `_page_field`.
- [ ] **Step 4: Run** `poetry run pytest tests/client -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(client): page dropdown for page settings`.

### Task 10: Docs, gates and check

**Files:**
- Modify: `docs/plugins/settings-schema.md` (`template`, `page`), `docs/plugins/package-and-manifest.md` (`static`), `docs/plugins/protocol.md` (settings delivery note: template/page fields arrive expanded/resolved; `set_settings` guidance), `docs/plugins/README.md`, `CLAUDE.md` (the "ships no plugins" statements)

- [ ] **Step 1: Write the docs** — the template syntax and variables, opt-in flag, the `page` value shape, `static` actions, built-in Blank, `switch_page`, and the `set_settings` caveat (send only changed keys).
- [ ] **Step 2: Run** `poetry run poe format`, `poe mypy`, `poe pylint`, `poe test`. Expected: mypy clean, pylint no new warnings, coverage >= 85%, all green (re-run only for failures outside files this plan touched).
- [ ] **Step 3: Offscreen check** — render (a) a Blank key with title `{page_index}/{page_count}` on page 2 of 3 and (b) the page dropdown in the config form against a fake RPC; view the PNGs and report what was and was not observed.
- [ ] **Step 4: Commit** `docs: templating, page settings, static actions and built-in Blank`.
