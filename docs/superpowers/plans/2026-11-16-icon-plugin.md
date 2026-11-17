# Icon Plugin, Icon Control and FontAwesome Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a key show an icon from an installed icon pack in a chosen fill colour: an `icon` settings control with a searchable browser, server-side `pack:` icon references with SVG tinting, the `com.decker.icon` plugin, and a properly shipped `com.decker.fontawesome` pack.

**Architecture:** A pure `common/icon_ref.py` defines the `pack:<pack id>/<path>` reference and the `icon` value (`{"ref", "color"}`). The server resolves references from its `IconPackRegistry` when a plugin sends `set_image {"icon", "color"}`, tints SVGs in `AssetRenderer`, and composes as before. The client gets `IconEdit` + `IconBrowserDialog`. `decker-plugins` gets the new plugin, the fixed FontAwesome manifest and an SVG-capable index builder.

**Tech Stack:** Python 3.14, PyQt6, Pillow, cairosvg, pytest + assertpy, poetry/poe (decker), uv/ruff (decker-plugins).

**Spec:** `docs/superpowers/specs/2026-11-16-icon-plugin-design.md`

## Global Constraints

- Reference syntax `pack:<pack id>/<icon path>`, split at the first `/`; value of an `icon` field: `{"ref": "", "color": "#ffffff"}`; `ref` is `""` or a valid reference; `color` is `#rrggbb` or `#rrggbbaa`; invalid fields fall back per field.
- `set_image` payload: `{"icon": "<ref>", "color": "#rrggbb[aa]"}` is mutually exclusive with `{"image": ...}`; SDK: `ActionContext.set_icon(ref: str, color: str | None = None)`.
- Only SVGs are tinted (root `color` + default `fill`; alpha becomes root `opacity`); raster icons ignore `color`.
- Decker version becomes `0.3.0`; `com.decker.icon` declares `"decker": ">=0.3"`.
- `com.decker.fontawesome-full` is NOT committed, packaged or released (leave the untracked folder alone). FontAwesome manifest `name` is exactly `"Fontawesome Icons"`.
- decker: branch `feat/icon-plugin` stacked on `feat/text-style-control`; black 120, full annotations, <= 50-line methods, <= 5 args, mypy, pylint >= 9.0, coverage >= 85%, run `poe format` before the other gates. decker-plugins: new branch off `main`, ruff, version rule (new plugin, no tag yet), plugin tests under `plugins/<id>/tests/`.
- No Qt in `server/` or `common/`; icon reads keep the existing size cap (256 KiB) and path checks in `IconPackRegistry.read_icon`.
- Never push or open PRs without asking; the decker-plugins Decker pin can only move after the Decker branch is pushed (Task 12).

## Review Focus

- Hand-edited settings with a bad reference (`pack:` alone, `pack:x`, `pack:p/../../etc/passwd`, absolute path, unknown pack, pack of an uninstalled plugin): the key shows no image, nothing is read outside the pack, no crash. (Tasks 3, 5)
- SVG tinting edge cases: no `currentColor`, root already has `fill`, uppercase `<SVG`, XML prolog or comment before the root, no `viewBox`, attributes already containing `color`/`opacity`; PNG with a colour is untouched. (Task 4)
- A fully transparent or invalid colour: nothing visible / ignored, never a crash. (Task 4, 5)
- Browser with the 2001-icon solid pack: opening does not issue 2001 RPCs up front; switching pack or typing in search cancels pending loads; empty search shows everything; no match shows a message. (Task 6)
- Icon chosen earlier whose pack is later uninstalled: `IconEdit` shows the name with a placeholder preview, the key shows no image. (Tasks 5, 7)
- Compatibility: plugins declaring `">=0.2"` still install on 0.3.0; `com.decker.icon` (`">=0.3"`) is refused by a 0.2 server. (Task 1)

---

## Part A: decker (branch `feat/icon-plugin`)

### Task 1: Branch, version 0.3.0, icon reference module

**Files:**
- Create: `src/decker/common/icon_ref.py`, `tests/common/test_icon_ref.py`
- Modify: `pyproject.toml` (`version = "0.3.0"`), `docs/plugins/protocol.md:29` (hello example `0.3.0`), `tests/common/test_version.py`

**Interfaces:**
- Produces:
  - `ICON_REF_PREFIX = "pack:"`; `DEFAULT_ICON_COLOR = "#ffffff"`
  - `make_icon_ref(pack_id: str, path: str) -> str`
  - `parse_icon_ref(ref: Any) -> tuple[str, str] | None` — `(pack_id, path)` or None when not a string, lacks the prefix, lacks a `/`, or either part is empty; path segments `..` and a leading `/` are rejected (None).
  - `normalize_icon_value(value: Any, defaults: Mapping[str, Any] | None = None) -> dict[str, Any]` — `{"ref", "color"}`; invalid `ref` → default ref (`""`), invalid `color` → default colour; non-dict → defaults; unknown keys dropped; returns a fresh dict.

- [ ] **Step 1: Branch** `git switch -c feat/icon-plugin` (from `feat/text-style-control`).
- [ ] **Step 2: Failing tests** — `tests/common/test_icon_ref.py`: `test_make_and_parse_round_trip` (`make_icon_ref("com.decker.fontawesome.solid", "house.svg")` parses back to both parts), `test_path_may_contain_slashes`, `test_parse_rejects_bad_refs` (parametrised: `None`, `5`, `""`, `"pack:"`, `"pack:x"`, `"pack:/a.svg"`, `"pack:p/"`, `"file:p/a"`, `"pack:p/../a.svg"`, `"pack:p//etc/passwd"`, `"pack:p/a/../../b"`), `test_normalize_fills_defaults`, `test_normalize_invalid_fields_fall_back_individually` (`{"ref": "nope", "color": "red"}` → both default), `test_normalize_accepts_rgba_color`, `test_normalize_non_dict_gives_defaults`, `test_normalize_returns_fresh_dict`. In `tests/common/test_version.py` add `test_package_declares_0_3_0` (reads `pyproject.toml` with `tomllib`) and `test_plugins_declaring_0_2_stay_compatible_but_0_3_gate_refuses_0_2` (`is_compatible(">=0.2", "0.3.0")` true; `is_compatible(">=0.3", "0.2.0")` false).
- [ ] **Step 3: Run** `poetry run pytest tests/common -q` — Expected: FAIL.
- [ ] **Step 4: Implement** the module (colour check reuses the 6-or-8-digit pattern from `common/text_style.py`; import it rather than duplicating) and bump the version in `pyproject.toml` and the protocol doc; run `poetry install` so the installed metadata reports 0.3.0.
- [ ] **Step 5: Run** `poetry run pytest tests/common -q` and `poetry run python -c "from decker.common.version import decker_version as v; print(v())"` — Expected: PASS and `0.3.0`.
- [ ] **Step 6: Commit** `feat(common): icon references and Decker 0.3.0`.

### Task 2: `icon` settings value

**Files:**
- Modify: `src/decker/plugin/settings_schema.py` (`_ZERO_VALUES["icon"]`, `_coerce`, `_parse_default`, `apply_schema`)
- Test: `tests/plugin/test_settings_schema.py`

**Interfaces:**
- Consumes: `normalize_icon_value`, `DEFAULT_ICON_COLOR` (Task 1).
- Produces: field type `icon` (already in `FIELD_TYPES`) now has an object value; default completed from partial dict (non-dict default raises `ValueError`); `apply_schema` normalises per field using the field default as fallback and returns a fresh copy; `schema_to_json` round-trips. Same treatment as `text_style`.

- [ ] **Step 1: Failing tests** — `test_icon_default_is_empty_ref_and_white`, `test_icon_default_completed_from_partial` (`{"color": "#ff0000"}`), `test_icon_non_dict_default_rejected`, `test_apply_schema_icon_invalid_fields_fall_back_per_field` (`{"ref": "pack:p/../x", "color": "#112233"}` → ref `""`, colour kept), `test_apply_schema_icon_missing_uses_default`, `test_apply_schema_icon_returns_copy`, `test_icon_round_trips_through_schema_to_json`, `test_icon_accepts_rgba_colour`. Update any existing test that assumed a string value for `icon`.
- [ ] **Step 2: Run** `poetry run pytest tests/plugin/test_settings_schema.py -q -k icon` — Expected: FAIL.
- [ ] **Step 3: Implement** by treating `icon` like `text_style` in the three functions named above.
- [ ] **Step 4: Run** `poetry run pytest tests/plugin -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(plugin): icon settings value {ref, color}`.

### Task 3: Registry references and plugin names

**Files:**
- Modify: `src/decker/asset/iconpack.py` (`_Pack.plugin_name`, `list_packs`, new `read_ref`), `src/decker/server/service.py` (`iconpacks_list` passes it through unchanged — verify only)
- Test: `tests/server/test_contributions.py`, `tests/server/test_service.py`

**Interfaces:**
- Consumes: `parse_icon_ref` (Task 1).
- Produces: `IconPackRegistry.read_ref(ref: str) -> bytes | None` — parses, then `read_icon(pack_id, path)`; None for anything invalid, unknown, escaping or too large. `list_packs()` entries gain `"plugin_name": str` (the manifest `name`).

- [ ] **Step 1: Failing tests** (use the registry fixtures already in `test_contributions.py`): `test_read_ref_returns_icon_bytes`, `test_read_ref_rejects_bad_references` (parametrised over the Review Focus list incl. `pack:p/../../etc/passwd`, absolute path, unknown pack → None), `test_read_ref_respects_size_cap`, `test_read_ref_after_unregister_is_none`, `test_list_packs_includes_plugin_name`. Adjust the `test_service.py` `iconpacks_list` expectation if it compares the whole dict.
- [ ] **Step 2: Run** `poetry run pytest tests/server/test_contributions.py tests/server/test_service.py -q -k "ref or iconpack or list_packs"` — Expected: FAIL.
- [ ] **Step 3: Implement** `read_ref` and the extra field.
- [ ] **Step 4: Run** the same command plus `poetry run pytest tests/server -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(server): resolve pack: icon references; list packs with plugin names`.

### Task 4: SVG tinting in the renderer

**Files:**
- Create: `src/decker/asset/tint.py`, `tests/asset/test_tint.py`
- Modify: `src/decker/asset/renderer.py` (`render_bytes`), `src/decker/server/appearance.py` (`compose_key_image`), `tests/server/test_appearance.py`

**Interfaces:**
- Produces:
  - `tint_svg(data: bytes, color: str) -> bytes` — rewrites only the root `<svg ...>` start tag: sets `color="#rrggbb"`, sets `fill="#rrggbb"` only when the root has no `fill`, sets `opacity="<a/255 rounded to 3 decimals>"` when alpha < 255; replaces existing `color`/`opacity` attributes; matches `<svg` case-insensitively after an optional prolog/comments; returns the input unchanged when no root tag is found or `color` is invalid.
  - `AssetRenderer.render_bytes(data: bytes, width: int, height: int, color: str | None = None) -> Image.Image | None` — tints SVG input when `color` is given; raster input ignores it.
  - `compose_key_image(appearance, plugin_image, plugin_title, size=144, plugin_image_color: str | None = None) -> bytes`.

- [ ] **Step 1: Failing tests** — `test_tint.py`: `test_sets_color_and_default_fill`, `test_keeps_existing_fill`, `test_alpha_becomes_opacity`, `test_replaces_existing_color_and_opacity`, `test_uppercase_tag_and_prolog_and_comment`, `test_no_svg_root_returns_input`, `test_invalid_color_returns_input`, `test_tint_changes_only_the_root_tag` (everything after the first `>` is byte-identical). Renderer/compose pixel tests: `test_currentcolor_icon_renders_in_given_colour` (FontAwesome-shaped SVG `<svg viewBox="0 0 10 10"><path fill="currentColor" d="M0 0h10v10H0z"/></svg>`, centre pixel equals the colour), `test_unstyled_svg_takes_default_fill`, `test_translucent_colour_blends_with_background`, `test_fully_transparent_colour_draws_nothing_visible_and_does_not_crash`, `test_png_ignores_colour`, `test_svg_without_viewbox_does_not_crash`.
- [ ] **Step 2: Run** `poetry run pytest tests/asset/test_tint.py tests/server/test_appearance.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** with a single compiled regex for the root tag; build the new attribute string rather than editing in place.
- [ ] **Step 4: Run** `poetry run pytest tests/asset tests/server/test_appearance.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(asset): tint SVG icons with a fill colour`.

### Task 5: `set_image` icon references, SDK, protocol docs

**Files:**
- Modify: `src/decker/server/plugins.py` (`_Live.plugin_image_color`, `_on_set_image`, `_compose`), `src/decker_plugin_sdk/_context.py` (`set_icon`), `docs/plugins/protocol.md`, `docs/plugins/sdk-quickstart.md`
- Test: `tests/server/test_plugins.py`, `tests/sdk/test_runtime.py`

**Interfaces:**
- Consumes: `IconPackRegistry.read_ref` (Task 3), `compose_key_image(..., plugin_image_color=)` (Task 4), `normalize_icon_value`'s colour rule (Task 1).
- Produces:
  - `set_image` payload `{"icon": "<ref>", "color": "<colour>"}`: the server reads the reference (the manager already owns the registry the service exposes as `icon_packs`), stores bytes in `plugin_image` and the colour in `plugin_image_color`. Unreadable/invalid reference → image cleared and a warning logged. Invalid `color` → no tint (warning). Payload with both `image` and `icon` → dropped with a warning. `{"image": null}` clears both. An `image` payload resets `plugin_image_color` to None.
  - `ActionContext.set_icon(ref: str, color: str | None = None) -> None` emitting `set_image` with `icon` (+ `color` when given).

- [ ] **Step 1: Failing tests** — server (follow the existing `set_image` tests in `TestAppearanceComposition`/neighbours): `test_set_image_icon_reference_composes_pack_icon` (register a pack with an SVG, send `{"icon": ref, "color": "#ff0000"}`, composed key has a red pixel), `test_set_image_icon_unknown_reference_clears_image`, `test_set_image_icon_escape_attempts_clear_image` (parametrised Review Focus list), `test_set_image_icon_invalid_color_is_untinted`, `test_set_image_with_both_image_and_icon_is_dropped`, `test_set_image_null_clears_icon_and_colour`, `test_raster_image_after_icon_resets_tint`, `test_uninstalled_pack_leaves_key_without_image` (unregister, trigger recompose). SDK: `test_set_icon_emits_set_image_with_icon_and_color`, `test_set_icon_without_color_omits_it`.
- [ ] **Step 2: Run** `poetry run pytest tests/server/test_plugins.py tests/sdk -q -k "icon"` — Expected: FAIL.
- [ ] **Step 3: Implement** in `_on_set_image` (split into helpers to stay under 50 lines), `_compose`, and `set_icon`; document the payload in `protocol.md` (Plugin to server table + Images section) and `set_icon` in `sdk-quickstart.md`.
- [ ] **Step 4: Run** `poetry run pytest tests/server tests/sdk -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(server): set_image icon references and SDK set_icon`.

### Task 6: Tinted thumbnails and `IconBrowserDialog`

**Files:**
- Modify: `src/decker/client/action_icons.py` (`decode_icon`), `src/decker/client/icon_picker.py` (replace `IconPackBrowserDialog` by `IconBrowserDialog`, keep `IconPickerWidget` working)
- Test: `tests/client/test_action_icons.py`, `tests/client/test_icon_picker.py`

**Interfaces:**
- Produces:
  - `decode_icon(icon_b64: str, tint: str | None = None) -> QPixmap | None` — when `tint` is given and the decoded bytes contain `currentColor`, the pixmap is recoloured (alpha preserved) with `tint`; other images unchanged.
  - `IconBrowserDialog(parent: QWidget | None, connection_manager: RpcCaller | None, tint: str | None = None)`: left `QTreeWidget` (`_tree`): top item "All icons", then one item per plugin (`plugin_name`) with a child per pack (`name`); right icon grid (`_icon_list`); `QLineEdit` `_search` above the grid. Selecting a node lists its icons (All = every pack's, in pack order); typing filters names (case-insensitive substring on the file stem) with a short debounce (`QTimer`, 150 ms); no match → status "No icons match."; empty pack → "This pack has no icons.". Signal `icon_chosen = pyqtSignal(str, str)` `(pack_id, path)` on double-click or Enter.
  - Thumbnails load one `iconpack_icon` call per event-loop turn, visible items first; any selection or search change clears the pending queue first.

- [ ] **Step 1: Failing tests** — `decode_icon`: `test_tint_recolours_currentcolor_svg`, `test_tint_leaves_raster_and_plain_svg_alone`, `test_decode_without_tint_unchanged`. Dialog (fake `RpcCaller` returning JSON for `iconpacks_list`/`iconpack_icons` and base64 for `iconpack_icon`, counting calls): `test_tree_groups_packs_under_plugin_names`, `test_all_icons_node_lists_every_pack`, `test_search_filters_by_name_case_insensitively`, `test_search_no_match_shows_message`, `test_empty_search_restores_everything`, `test_opening_large_pack_does_not_load_every_icon_up_front` (2001 names; after one `processEvents` far fewer than 2001 `iconpack_icon` calls), `test_visible_icons_load_before_off_screen_ones`, `test_changing_selection_cancels_pending_loads`, `test_double_click_emits_pack_and_path`, `test_server_failure_shows_status`. Update/replace tests that referenced `IconPackBrowserDialog`.
- [ ] **Step 2: Run** `poetry run pytest tests/client/test_action_icons.py tests/client/test_icon_picker.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** both; keep the old class name as an alias only if other modules import it (grep first).
- [ ] **Step 4: Run** `poetry run pytest tests/client -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(client): searchable icon browser grouped by plugin and pack, tinted thumbnails`.

### Task 7: `IconEdit` control and form registration

**Files:**
- Create: `src/decker/client/widgets/icon_edit.py`, `tests/client/widgets/test_icon_edit.py`
- Modify: `src/decker/client/widgets/schema_form.py` (`_BUILDERS["icon"]`), `docs/plugins/settings-schema.md`
- Test: `tests/client/widgets/test_schema_form.py`

**Interfaces:**
- Consumes: `IconBrowserDialog` (Task 6), `decode_icon` (Task 6), `make_icon_ref`/`parse_icon_ref`/`normalize_icon_value` (Task 1), `ColorButton(alpha=True)` + `set_show_name(False)`.
- Produces: `IconEdit(rpc: Callable[[], RpcCaller | None] | None = None, parent: QWidget | None = None)` — one row: 24 px preview, name label (icon file stem, or "No icon"), **Browse…**, clear (✕), fill-colour swatch. `value() -> dict` (`{"ref", "color"}`), `set_value(value: Any) -> None` (normalises; emits nothing), `value_changed = pyqtSignal()` on user edits. Preview is fetched with `iconpack_icon` and tinted with the colour; a missing/unreadable icon shows a placeholder and keeps the name. Default `rpc` resolves `AppContext.get().connection_manager` at call time. `SchemaForm` builds it for type `icon`.

- [ ] **Step 1: Failing tests** — `test_value_defaults`, `test_set_value_round_trips_and_emits_nothing`, `test_browse_choice_sets_ref_and_emits` (patch the dialog to return `("com.x.p", "house.svg")`), `test_clear_resets_ref_keeps_colour_and_emits`, `test_colour_change_emits_and_updates_value`, `test_name_label_shows_stem_or_no_icon`, `test_missing_icon_shows_placeholder_and_keeps_name`, `test_preview_uses_fill_colour` (fake rpc returning a currentColor SVG; preview pixel has the colour), `test_garbage_value_uses_defaults`, `test_no_connection_does_not_crash`; form: `test_icon_field_round_trips`, `test_icon_field_default_applied`.
- [ ] **Step 2: Run** `poetry run pytest tests/client/widgets/test_icon_edit.py tests/client/widgets/test_schema_form.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `IconEdit`, register `_icon_field`, update the `icon` row and add an "Icon" section (value shape, `pack:` references, example field) in `settings-schema.md`.
- [ ] **Step 4: Run** `poetry run pytest tests/client -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(client): IconEdit control for icon settings`.

### Task 8: Decker gates

**Files:** none new.

- [ ] **Step 1: Run** `poetry run poe format`, `poe mypy`, `poe pylint`, `poe test` (re-run on the known `update_checker` segfault flake). Expected: mypy clean, pylint >= 9.0, coverage >= 85%, all green. Fix anything raised.
- [ ] **Step 2: Offscreen check** — render `IconEdit` and the open `IconBrowserDialog` against the real `com.decker.fontawesome` pack (register it in an `IconPackRegistry`, fake rpc over it) to PNGs; view them and confirm the tree grouping, search and tinted thumbnails. Report what was and wasn't observed.
- [ ] **Step 3: Commit** any formatting fixes: `chore: format`.

---

## Part B: decker-plugins (new branch off `main`; Decker installed editable from the Part A branch for local runs: `uv pip install -e /work/decker/decker`)

### Task 9: Ship `com.decker.fontawesome`

**Files:**
- Create (tracked): `plugins/com.decker.fontawesome/**` (manifest, `LICENSE.txt`, `brands/`, `regular/`, `solid/`), `plugins/com.decker.fontawesome/tests/test_pack.py`
- Modify: `plugins/com.decker.fontawesome/manifest.json`

**Interfaces:**
- Produces: manifest `name` = `"Fontawesome Icons"`, `description` = `"Font Awesome Free icons (brands, regular and solid)."` (trailing space and boilerplate removed), everything else unchanged. `com.decker.fontawesome-full` stays untracked.

- [ ] **Step 1: Branch** `git switch -c feat/fontawesome-and-icon-plugin` (from `main`).
- [ ] **Step 2: Failing tests** in `plugins/com.decker.fontawesome/tests/test_pack.py` (load with `PluginManifest.load` like the Counter tests): `test_manifest_is_valid_and_named`, `test_every_declared_pack_folder_exists_and_has_icons`, `test_pack_ids_start_with_plugin_id`, `test_manifest_icon_resolves`, `test_every_icon_is_readable_within_the_size_cap` (register the plugin in `IconPackRegistry`; no `read_icon` returns None), `test_every_svg_renders` (`AssetRenderer.render_bytes(..., 72, 72)` not None for every icon), `test_license_is_shipped`, `test_packages_without_tests_and_within_limits` (use `pack_all` on a staged copy; size < 64 MiB, entries < 10 000, no `tests/` entry).
- [ ] **Step 3: Run** `uv run pytest plugins/com.decker.fontawesome -q` — Expected: FAIL (name still "Counter").
- [ ] **Step 4: Implement** the manifest edits.
- [ ] **Step 5: Run** the same command — Expected: PASS.
- [ ] **Step 6: Commit** only `plugins/com.decker.fontawesome` (`git add plugins/com.decker.fontawesome`; never `-A`): `feat: add the Font Awesome icon pack plugin`.

### Task 10: Index builder renders SVG icons

**Files:**
- Modify: `tools/build_index.py` (`_icon_source`, new `_write_icon`)
- Test: `tests/tools/test_build_index.py`

**Interfaces:**
- Consumes: Decker's `AssetRenderer` (`render_path(path, w, h) -> Image`).
- Produces: `_icon_source` also tries `<icon>.svg`; `icons/<id>.png` is always a real PNG: an SVG source is rendered to 256x256 RGBA, a PNG source is copied unchanged. Unrenderable SVG → icon omitted with a warning on stderr, build continues.

- [ ] **Step 1: Failing tests** — `test_svg_manifest_icon_is_rendered_to_png` (temp plugins dir whose manifest icon is `brands/mark` with `mark.svg`; output opens as PNG, size 256x256), `test_svg_icon_path_with_extension_is_supported` (`"icon": "x.svg"`), `test_png_manifest_icon_is_copied_unchanged` (Counter, byte-identical), `test_unrenderable_svg_is_skipped_with_warning` (`capsys`; index still written), `test_fontawesome_gets_an_index_icon` (build an entry for the real `com.decker.fontawesome` package; `icons/com.decker.fontawesome.png` exists).
- [ ] **Step 2: Run** `uv run pytest tests/tools/test_build_index.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests -q` and `uv run ruff check .` — Expected: PASS / clean.
- [ ] **Step 5: Commit** `feat(tools): render SVG manifest icons to PNG in the index`.

### Task 11: `com.decker.icon` plugin

**Files:**
- Create: `plugins/com.decker.icon/manifest.json`, `plugins/com.decker.icon/plugin.py`, `plugins/com.decker.icon/icons/icon.png`, `plugins/com.decker.icon/tests/test_icon.py`

**Interfaces:**
- Consumes: `ActionContext.set_icon`, `ActionContext.clear_image` (Task 5), the `icon` settings value (Task 2).
- Produces: manifest `id` `com.decker.icon`, `name` "Icon", `version` `1.0.0`, `"decker": ">=0.3"`, python runtime without requirements, category "Utilities", one action `com.decker.icon.icon` (gestures `["press"]`, appearance default `{"background": "#000000"}`, settings `[{"key": "icon", "type": "icon", "label": "Icon"}]`); `plugin.py` class `IconPlugin(DeckerPlugin)` with `@action("com.decker.icon.icon")` `IconAction`: `will_appear` and `settings_changed` call `ctx.set_icon(ref, color)` when `ref` is non-empty, else `ctx.clear_image()`.

- [ ] **Step 1: Failing tests** — through the SDK loop on pipes like `com.decker.counter/tests/test_counter.py`: `test_manifest_is_valid_and_gated_on_0_3` (loads; `is_compatible(">=0.3", "0.2.0")` false), `test_will_appear_with_icon_sends_set_image_icon_and_colour`, `test_settings_changed_updates_the_icon`, `test_empty_ref_clears_the_image`, `test_default_settings_show_nothing`.
- [ ] **Step 2: Run** `uv run pytest plugins/com.decker.icon -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the manifest, plugin and a 144 px placeholder `icon.png` (any simple PNG; generate with Pillow, don't hand-edit).
- [ ] **Step 4: Run** `uv run pytest plugins/com.decker.icon -q`, `uv run python -m tools.pack_all --out <scratch>` (packs `com.decker.icon`; the untracked `-full` folder also gets packed locally, which is fine), `uv run ruff check .` — Expected: PASS, package built, clean.
- [ ] **Step 5: Commit** `feat: add the Icon plugin`.

### Task 12: Handoff (stop for the human)

- [ ] **Step 1:** Run both repos' full suites once more and report results (decker: `poetry run poe test`; decker-plugins: `uv run pytest`).
- [ ] **Step 2:** Do NOT push. Tell the user: the `decker-plugins` pin (`pyproject.toml` + `uv.lock`) still points at the old Decker commit, so CI there will fail on `set_icon` until the Decker branch is pushed and the pin is updated to its head; ask whether to push and open the PRs.
