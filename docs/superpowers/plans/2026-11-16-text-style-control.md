# Text Style Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Title section of the key Appearance form with one reusable `text_style` control (text field + inset cog + floating single-row formatting toolbar), usable by plugins as a settings-schema type.

**Architecture:** A pure `common/text_style.py` defines the value shape, normalisation and legacy-key folding (shared by server and client). The settings schema gains a `text_style` type; the server validates it and `server/appearance.py` renders it (Pillow). The client adds `TextStyleEdit` (+ toolbar popup, `ColorToolButton`) registered in `SchemaForm`. Appearance key `title` becomes the nested value; old flat `title_*`/`show_title` keys are read-time folded into it.

**Tech Stack:** Python 3.14, PyQt6, Pillow, fontconfig (`fc-match`), pytest + assertpy, poe (format/mypy/pylint/test).

**Spec:** `docs/superpowers/specs/2026-11-16-text-style-control-design.md`

## Global Constraints

- Value shape (exact keys/defaults): `{"text": "", "visible": True, "font": "DejaVu Sans", "size": 12, "bold": False, "italic": False, "underline": False, "strike": False, "position": "bottom", "color": "#ffffff", "outline": None, "outline_width": 1}`; `position` ∈ `top|middle|bottom`; `size` 4–48; `outline_width` 1–6; colours `#rrggbb`.
- Schema type name `text_style`; widget class `TextStyleEdit`.
- No Qt imports in `server/` or `common/`; no rendering logic in `client/`.
- Legacy keys `title`(str), `title_position`, `title_font`, `title_size`, `title_color`, `title_outline`, `title_outline_width`, `show_title` must keep rendering identically and stay accepted in manifests/stored appearance.
- Toolbar order: `[font ▾][– size +] | [B][I][U][S] | [top][middle][bottom] | [color ▾][outline ▾][– width +] | [visible]`. "Show title" checkbox is removed.
- CLAUDE.md: black line length 120, full annotations, ≤ 50-line methods, ≤ 5 args, docstrings on public items only, tests under `tests/` mirroring `src/`, coverage ≥ 85%, pylint ≥ 9.0. Run `poe format` before `poe mypy`/`poe pylint`/`poe test`.

## Review Focus

- Stored appearance holding both legacy flat keys and a nested `title`: nested wins per field. (Task 1)
- Invalid nested values (`size: "abc"`, `position: "left"`, `color: "red"`, unknown keys, non-dict) fall back per field, never reject the whole value. (Task 2)
- Mutating a resolved value or the schema default must not change the shared default. (Task 2)
- Unusual text: empty text with no plugin title draws nothing; very long text, emoji and an unavailable font family do not crash the renderer. (Tasks 3, 4)
- Outline `None`: width ignored in the render and its spinner disabled in the UI; underline/strike get the outline only when an outline is set. (Tasks 4, 6)
- Popup at the right/bottom screen edge stays on screen; Esc and a second cog click close it; `set_value` while open refreshes controls without emitting `value_changed` (keeps `ActionConfigPanel`'s "don't clobber edits" logic correct). (Task 6)

---

### Task 1: Shared value module

**Files:**
- Create: `src/decker/common/text_style.py`
- Test: `tests/common/test_text_style.py`

**Interfaces:**
- Produces:
  - `TEXT_STYLE_DEFAULTS: Mapping[str, Any]` (the Global Constraints shape, read-only)
  - `POSITIONS: tuple[str, ...] = ("top", "middle", "bottom")`, `SIZE_RANGE = (4, 48)`, `OUTLINE_WIDTH_RANGE = (1, 6)`
  - `normalize_text_style(value: Any, defaults: Mapping[str, Any] = TEXT_STYLE_DEFAULTS) -> dict[str, Any]` — complete dict; each field independently validated, invalid/missing → the field from `defaults`; non-dict → copy of `defaults`; unknown keys dropped; `outline` accepts `None`, `""` (→ `None`) or `#rrggbb`.
  - `fold_legacy_title(values: Mapping[str, Any]) -> dict[str, Any]` — copy of `values` with legacy keys removed and `title` replaced by a *partial* nested dict holding only fields that were present (`title` str → `text`; `show_title` → `visible`; `title_position|font|size|color|outline|outline_width` → `position|font|size|color|outline|outline_width`). If `title` is already a dict its fields win over legacy ones. No legacy keys and no `title` → no `title` in the result.

- [ ] **Step 1: Write failing tests** — `test_normalize_fills_defaults`, `test_normalize_invalid_fields_fall_back_individually` (`{"size": "abc", "position": "left", "color": "red", "bold": "yes", "text": "Hi"}` → only `text` kept, rest default), `test_normalize_non_dict_gives_defaults`, `test_normalize_drops_unknown_keys`, `test_normalize_empty_outline_is_none`, `test_normalize_clamps_nothing_out_of_range_falls_back` (`size: 99` → 12), `test_normalize_returns_fresh_dict` (mutating result leaves `TEXT_STYLE_DEFAULTS` equal), `test_fold_maps_every_legacy_key` (assert the full mapping above, incl. `show_title: False` → `visible: False`), `test_fold_nested_wins_over_legacy` (`{"title": {"size": 20}, "title_size": 9}` → `title == {"size": 20}`), `test_fold_without_title_data_adds_no_title`, `test_fold_keeps_unrelated_keys` (`background` untouched).
- [ ] **Step 2: Run** `poetry run pytest tests/common/test_text_style.py -v` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the signatures above in `src/decker/common/text_style.py`, constants as module-level `UPPER_CASE`; use `types.MappingProxyType` for the defaults.
- [ ] **Step 4: Run** the same command — Expected: PASS.
- [ ] **Step 5: Commit** `feat(common): text style value, normalisation and legacy title folding`.

### Task 2: `text_style` settings-schema type

**Files:**
- Modify: `src/decker/plugin/settings_schema.py` (`FIELD_TYPES`, `_ZERO_VALUES`, `_coerce`, `_parse_default`, `apply_schema`)
- Test: `tests/plugin/test_settings_schema.py`

**Interfaces:**
- Consumes: `normalize_text_style`, `TEXT_STYLE_DEFAULTS` (Task 1).
- Produces: field type `"text_style"`. Parsed `SettingField.default` is a full normalised dict (partial manifest defaults are completed from `TEXT_STYLE_DEFAULTS`; a non-dict default raises `ValueError` like other bad defaults). `_coerce` never returns `_MISSING` for this type (it normalises, using the field default as the fallback source). `apply_schema` returns a fresh dict copy per call so callers can't mutate the field default. `schema_to_json` round-trips it unchanged.

- [ ] **Step 1: Write failing tests** — `test_text_style_type_accepted`, `test_text_style_default_completed_from_partial` (`{"default": {"position": "top"}}` → full dict, position top), `test_text_style_non_dict_default_rejected`, `test_apply_schema_text_style_invalid_fields_fall_back_per_field`, `test_apply_schema_text_style_missing_uses_default`, `test_apply_schema_text_style_returns_copy` (mutate result, apply again, default unchanged), `test_text_style_round_trips_through_schema_to_json`.
- [ ] **Step 2: Run** `poetry run pytest tests/plugin/test_settings_schema.py -v -k text_style` — Expected: FAIL.
- [ ] **Step 3: Implement** by adding `"text_style"` to `FIELD_TYPES` and special-casing it in `_parse_default` and `_coerce` (pass the field default as the `defaults` argument; this means `_coerce` needs the default — thread it through `apply_schema`, keep the signature ≤ 5 args).
- [ ] **Step 4: Run** `poetry run pytest tests/plugin -v` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(plugin): text_style settings field type`.

### Task 3: Appearance schema, resolution and basic rendering

**Files:**
- Modify: `src/decker/common/appearance_schema.py`, `src/decker/server/appearance.py` (`resolve_appearance`, `compose_key_image`, `_draw_title`)
- Modify tests: `tests/server/test_appearance.py`, `tests/server/test_plugins.py:545-559`
- Test: `tests/server/test_appearance.py`

**Interfaces:**
- Consumes: `fold_legacy_title`, `normalize_text_style` (Task 1), `text_style` type (Task 2).
- Produces:
  - `APPEARANCE_SCHEMA`: Title section is now the single entry `{"key": "title", "type": "text_style", "label": "Title"}`.
  - `APPEARANCE_KEYS` = schema keys ∪ legacy keys (`show_title`, `title_position`, `title_font`, `title_size`, `title_color`, `title_outline`, `title_outline_width`) so `service.py:467` and `manifest.py:235` keep accepting them.
  - `resolve_appearance(action_defaults, stored)` — folds each of `action_defaults` and `stored` with `fold_legacy_title`, merges `title` field-wise (stored over defaults), then `apply_schema`. Result has `title` as a full dict and no legacy keys.
  - `compose_key_image` draws `appearance["title"]`: text = `title["text"]` or `plugin_title`; nothing drawn when `visible` is false or the text is empty. Position/font/size/color/outline behave exactly as today (reuse existing `_font`, margins, scaling).

- [ ] **Step 1: Write failing tests** (new, in `tests/server/test_appearance.py`): `test_defaults_from_schema` updated to expect `"title": TEXT_STYLE_DEFAULTS` dict and no legacy keys; `test_legacy_flat_keys_fold_into_title` (`resolve_appearance({}, {"title": "Hi", "title_position": "top", "show_title": False})["title"]` has text Hi, position top, visible False); `test_nested_title_wins_over_legacy` (Review Focus 1); `test_manifest_default_legacy_keys_still_accepted` (a manifest `appearance: {"title_position": "top"}` loads; use the existing manifest test helper in this file); `test_visible_false_hides_plugin_title`; `test_empty_text_without_plugin_title_draws_nothing`; `test_long_unicode_text_does_not_crash` (`"W"*200 + "🙂"`); `test_unavailable_font_falls_back` (`font: "No Such Family 123"`). Update `tests/server/test_plugins.py` assertions that read `["title"]` as a string to read `["title"]["text"]`.
- [ ] **Step 2: Run** `poetry run pytest tests/server/test_appearance.py tests/server/test_plugins.py -v` — Expected: new/updated tests FAIL.
- [ ] **Step 3: Implement** the three items above. `_draw_title(draw, text, style: Mapping[str, Any], size: int) -> None` replaces the old signature (title text now passed separately; keep ≤ 5 args).
- [ ] **Step 4: Run** `poetry run pytest tests/server tests/plugin tests/common -v` — Expected: PASS (existing legacy-keyed render tests still pass unchanged via folding; leave a few as the legacy-compat tests).
- [ ] **Step 5: Commit** `feat(server): render title from nested text_style appearance`.

### Task 4: Bold, italic, underline, strikethrough rendering

**Files:**
- Modify: `src/decker/server/appearance.py`
- Test: `tests/server/test_appearance.py`

**Interfaces:**
- Consumes: Task 3's `_draw_title`.
- Produces:
  - `_font_file(family: str, bold: bool = False, italic: bool = False) -> str | None` (cached) — `fc-match` with pattern `f"{family}:bold"`/`:italic` and format `%{file}\n%{weight}`; also exposes whether the returned face is really bold (`weight >= 180`). Factor the lookup so `_font(family, size, bold, italic)` returns `(font, is_real_bold)`.
  - Rendering: if `bold` and not a real bold face, fake bold = extra stroke of `max(1, round(size_px / 24))`. Draw in two passes: (1) when `outline` is set, text with `stroke_width = outline_width_px + fake_bold`, fill and stroke in the outline colour; (2) text with `stroke_width = fake_bold`, fill/stroke in `color`.
  - Underline / strike: lines drawn with `ImageDraw.line` from `draw.textbbox(...)` (same anchor/stroke), thickness `max(1, round(size_px / 14))`, in `color`; underline sits just below the baseline, strike at the x-height middle. When `outline` is set each line is first drawn thicker by `2 * outline_width_px` in the outline colour.

- [ ] **Step 1: Write failing tests** — `test_bold_differs_from_regular` (images differ and bold has more text-coloured pixels), `test_italic_differs_from_regular`, `test_underline_adds_a_horizontal_run` (with text `"WWWW"`, some row has a continuous run of text-colour pixels at least as wide as the text without underline having one), `test_strike_row_is_through_the_text_middle` (run row lies between the top and bottom of the glyph bounds), `test_underline_outlined_only_when_outline_set` (outline colour pixels appear around the line only with `outline` set), `test_outline_none_ignores_outline_width`, `test_fake_bold_when_family_has_no_bold_face` (monkeypatch `_font_file` to return a regular-weight file with weight 80; image still differs from regular), `test_all_styles_together_do_not_crash`.
- [ ] **Step 2: Run** `poetry run pytest tests/server/test_appearance.py -v -k "bold or italic or underline or strike or outline"` — Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces; split into helpers (`_draw_text_passes`, `_draw_decorations`) to stay under 50 lines per method.
- [ ] **Step 4: Run** `poetry run pytest tests/server -v` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(server): bold, italic, underline and strike title rendering`.

### Task 5: `ColorToolButton`

**Files:**
- Create: `src/decker/client/widgets/color_tool_button.py`
- Test: `tests/client/widgets/test_color_tool_button.py`

**Interfaces:**
- Produces: `ColorToolButton(icon_text: str, allow_none: bool = False, parent: QWidget | None = None)` (`QToolButton`, popup mode `MenuButtonPopup` with a "Pick colour…" action and, when `allow_none`, a "None" action). Property `color: str | None` (`#rrggbb` or `None`); `set_color(color: str | None) -> None` (no signal); signal `color_changed = pyqtSignal(object)` emitted only on user change. Button icon = `icon_text` glyph with a 3 px bar in the current colour beneath it (empty bar when `None`). Clicking the main button opens `QColorDialog.getColor`; tests patch the dialog the same way `tests/client/widgets/test_color_button.py` does.

- [ ] **Step 1: Write failing tests** — `test_set_color_updates_property_without_signal`, `test_pick_emits_color_changed` (patch `QColorDialog.getColor`), `test_cancelled_dialog_changes_nothing`, `test_none_action_clears_color_and_emits_none`, `test_none_action_absent_unless_allowed`, `test_invalid_color_ignored`.
- [ ] **Step 2: Run** `poetry run pytest tests/client/widgets/test_color_tool_button.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** the class to the interface.
- [ ] **Step 4: Run** the same command — Expected: PASS.
- [ ] **Step 5: Commit** `feat(client): colour tool button with optional none`.

### Task 6: `TextStyleToolbar` and `TextStyleEdit`

**Files:**
- Create: `src/decker/client/widgets/text_style_toolbar.py`, `src/decker/client/widgets/text_style_edit.py`
- Test: `tests/client/widgets/test_text_style_toolbar.py`, `tests/client/widgets/test_text_style_edit.py`

**Interfaces:**
- Consumes: `ColorToolButton` (Task 5), `normalize_text_style`, `POSITIONS`, `SIZE_RANGE`, `OUTLINE_WIDTH_RANGE` (Task 1).
- Produces:
  - `TextStyleToolbar(QFrame)` — window flag `Qt.WindowType.Popup` (closes on outside click and Esc natively), single `QHBoxLayout` row in the Global Constraints order. Font: `QFontComboBox`; size and outline width: `QSpinBox` with the ranges above plus explicit `–`/`+` `QToolButton`s; B/I/U/S: checkable `QToolButton`s with tooltips showing `Ctrl+B/I/U` (strike has none) and `QShortcut`s (context `WidgetWithChildrenShortcut`); position: three checkable icon buttons in an exclusive `QButtonGroup` (icons painted with `QPainter`, tooltips Top/Middle/Bottom); colour = `ColorToolButton("T")`, outline = `ColorToolButton("A", allow_none=True)`; outline-width controls disabled while outline is `None`; visible: checkable button (eye glyph). Methods: `style_value() -> dict[str, Any]` (without `text`), `set_style(value: Mapping[str, Any]) -> None` (no signal), signal `style_changed = pyqtSignal()` on any user edit.
  - `TextStyleEdit(QWidget)` — `QLineEdit` with a cog `QAction` at `TrailingPosition` (checkable look while the popup is open). Methods `value() -> dict[str, Any]` (full normalised dict incl. `text`), `set_value(value: Any) -> None` (normalises; refreshes line edit and toolbar; emits nothing), signal `value_changed = pyqtSignal()` on user edits of text or style. Cog click toggles the popup; popup opens under the field aligned to its right edge and is clamped into `QGuiApplication.primaryScreen().availableGeometry()`.

- [ ] **Step 1: Write failing tests** — toolbar: `test_set_style_round_trips`, `test_style_changed_on_each_control` (parametrised over bold/italic/underline/strike/position/size/colour/visible), `test_set_style_emits_nothing`, `test_outline_none_disables_outline_width`, `test_outline_width_enabled_when_outline_set`, `test_size_plus_minus_buttons_respect_range`, `test_ctrl_b_toggles_bold`. Edit: `test_value_is_normalised_dict`, `test_typing_emits_value_changed_and_updates_text`, `test_set_value_emits_nothing_and_updates_controls` (Review Focus 6, also with popup open), `test_cog_toggles_popup`, `test_escape_closes_popup`, `test_popup_clamped_to_screen` (move the edit to the bottom-right corner of the screen, assert popup geometry inside `availableGeometry()`), `test_set_value_with_garbage_uses_defaults`.
- [ ] **Step 2: Run** `poetry run pytest tests/client/widgets/test_text_style_toolbar.py tests/client/widgets/test_text_style_edit.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** both classes; keep widget construction in small private helpers (`_build_font_row`, `_build_style_buttons`, …) to stay under 50 lines per method.
- [ ] **Step 4: Run** the same command — Expected: PASS.
- [ ] **Step 5: Commit** `feat(client): reusable TextStyleEdit with floating formatting toolbar`.

### Task 7: Form integration, panel, docs

**Files:**
- Modify: `src/decker/client/widgets/schema_form.py` (`_BUILDERS`), `src/decker/client/widgets/action_config_panel.py`, `docs/plugins/settings-schema.md`, `docs/plugins/package-and-manifest.md:97`
- Modify tests: `tests/client/widgets/test_action_config_panel.py`
- Test: `tests/client/widgets/test_schema_form.py`

**Interfaces:**
- Consumes: `TextStyleEdit` (Task 6), `fold_legacy_title`, `normalize_text_style` (Task 1).
- Produces:
  - `_text_style_field(entry) -> _Field` in `schema_form.py`, registered as `"text_style"`; `get = edit.value`, `set = edit.set_value`; row label as usual.
  - `ActionConfigPanel.show_action_config` folds `appearance` through `fold_legacy_title` and merges `title` field-wise over the defaults' `title` before comparing/populating, so old stored keys show correctly. Save still sends only values differing from defaults (the whole `title` dict when any field differs), which drops legacy keys on write-back.
  - Docs: `text_style` row in the types table (value shape, field ranges, partial defaults allowed) and a short "Text style" section with a schema example and the nested value; the `appearance` row in `package-and-manifest.md` lists `background` and `title` (nested), noting the old flat `title_*`/`show_title` keys are still accepted.

- [ ] **Step 1: Write failing tests** — `test_text_style_field_round_trips` (schema form), `test_text_style_field_default_applied`, `test_two_text_style_fields_independent`; panel: update the four existing `_fields["title"].set("typing…")` tests to set `{"text": "typing…"}` and read `values()["title"]["text"]`, and add `test_legacy_stored_keys_populate_title_control` (stored `{"title": "Old", "title_size": 20}` → control shows text Old, size 20) and `test_save_drops_legacy_keys` (save callback receives appearance with nested `title` and none of the legacy keys).
- [ ] **Step 2: Run** `poetry run pytest tests/client/widgets/test_schema_form.py tests/client/widgets/test_action_config_panel.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** the builder, the panel folding, and the docs edits.
- [ ] **Step 4: Run** `poetry run pytest tests/client tests/server tests/plugin tests/common -v` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(client): text_style field in schema forms and appearance panel; docs`.

### Task 8: Quality gates and live check

**Files:** none new.

- [ ] **Step 1: Run** `poetry run poe format`, then `poe mypy`, `poe pylint`, `poe test`. Expected: mypy clean, pylint ≥ 9.0, coverage ≥ 85%. Fix anything raised.
- [ ] **Step 2: Live check** — `poe server`, `poe client`: select a key, type a title, open the cog, toggle bold/underline/strike, change position, colour, outline (and "None"), size, visible; Save; confirm the hardware/preview key matches. Reopen a key saved before this change and confirm its title and style show unchanged. Report what was and wasn't observed.
- [ ] **Step 3: Commit** any formatting fixes: `chore: format`.
