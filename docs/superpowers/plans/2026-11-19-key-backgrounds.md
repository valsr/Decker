# Key background images Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A key's background can be none, a solid colour, or a library image (PNG, SVG, animated GIF), drawn behind the icon and title; the library is called the "image library" in the UI and docs.

**Architecture:** The `background` appearance setting becomes a nested value `{type, color, image}` (new schema field type `background`, legacy bare colour strings fold on read). The server resolves the image ref to bytes (as it already does for the `icon` override) and `server/appearance.py` draws it as a cover-fit layer. An animated GIF background becomes an `AnimationSpec` with `layer="background"` and the static foreground image as `overlay`, unless the foreground is itself an animated GIF (then the foreground wins and the background shows its first frame). The client gets a `BackgroundEdit` composite built on `IconEdit`.

**Tech Stack:** Python 3.14, Pillow, cairosvg (via `AssetRenderer`), PyQt6, pytest + assertpy.

**Spec:** `docs/superpowers/specs/2026-11-19-key-backgrounds-design.md`

## Global Constraints

- Black (line length 120) + isort; annotate everything; methods under 50 lines; at most 5 args (use a small dataclass or keyword-only grouping; existing `# pylint: disable=too-many-arguments` on compose functions may stay).
- Docstrings only on public classes and functions, one short line; comments only for a non-obvious why.
- Tests mirror the source layout, use `assertpy`, prefer real components over mocks; unique test basenames (tests/server has no `__init__.py`); **never touch real hardware or the live desktop, never synthesise input**.
- Coverage at or above 85%; `poe format`, `poe mypy`, `poe pylint` (at least 9.0), `poe test` pass.
- Existing keys must look exactly as before: a stored bare `"#rrggbb"`/`"#rrggbbaa"` background renders identically and a plugin manifest `background` default given as a string keeps validating.
- Background value shape (exact): `{"type": "none" | "color" | "image", "color": "#rrggbb[aa]", "image": {"ref": ""}}`; default `{"type": "color", "color": "#000000", "image": {"ref": ""}}`. `image.ref` uses the existing `pack:<pack id>/<path>` references (`decker.common.icon_ref`).
- The image fills the key by cover-and-crop, centred; transparent areas show black; background images are never tinted.
- A missing or unreadable background image falls back to black, logs at debug once, and the icon and title still draw.
- Protocol identifiers (`iconpacks_list`, `iconpack_*`, pack ids, manifest `icon_packs`, config `icons.*`) are NOT renamed; only user-visible labels and docs change.

## Review Focus

- Legacy stored values: a bare colour string, a partial object, junk types, an unknown `type` must all normalise without raising (Task 1).
- A GIF background plus a static icon animates; an animated foreground wins; a GIF background that fails to decode leaves a static key, never a broken one (Task 2).
- The animation id must change when the background image, its mode, the overlay or the overlay colour changes, so a stale cached animation is never shown (Task 2).
- Key preview and hardware agree for all three modes, including an image ref to an uninstalled pack (Task 3).
- The client form round-trips every mode and keeps the colour/image the user last chose when they switch modes back and forth (Task 4).

---

### Task 1: The `background` value type and schema field

**Files:**
- Create: `src/decker/common/background.py`
- Modify: `src/decker/common/appearance_schema.py`, `src/decker/plugin/settings_schema.py`, `src/decker/server/appearance.py` (`resolve_appearance` only)
- Test: `tests/common/test_background.py`, `tests/plugin/test_settings_schema_background.py`, `tests/server/test_appearance_background_schema.py`

**Interfaces:**
- Produces: `BACKGROUND_TYPES = ("none", "color", "image")`, `BACKGROUND_DEFAULT: Mapping[str, Any]`, `normalize_background(value: Any, defaults: Mapping[str, Any] | None = None) -> dict[str, Any]` returning the complete shape; accepts a bare colour string (legacy, becomes `{"type": "color", "color": value, ...}`), a partial dict (missing fields fall back to defaults, invalid fields fall back individually, unknown `type` falls back to the default type, `image` normalised with `normalize_icon_value` keeping only `ref`), anything else yields the defaults.
- Produces: schema field type `"background"` in `FIELD_TYPES`, `_ZERO_VALUES`, `_OBJECT_NORMALIZERS`; `APPEARANCE_SCHEMA["background"]` becomes `{"key": "background", "type": "background", "label": "Background"}` (the alpha option moves into the value's `color`, which always allows `#rrggbbaa`).
- Produces: `resolve_appearance` merges `background` like `title` (action defaults then stored values, each normalised), so an action manifest `"background": "#112233"` default becomes `{"type": "color", "color": "#112233", ...}`.
- Consumes: `normalize_icon_value`, `is_color` (existing).

- [ ] **Step 1: Write failing tests:** `test_default_shape`; `test_legacy_color_string_folds`; `test_legacy_rgba_string_folds`; `test_partial_dict_fills_defaults`; `test_junk_values_yield_defaults` (parametrised: None, 5, [], "red", {"type": "video"}, {"color": 5}, {"image": 7}); `test_image_ref_validated` (an invalid ref falls back to `""`; extra image keys such as `color` are dropped); `test_manifest_schema_accepts_background_field_and_string_default`; `test_resolve_appearance_folds_legacy_stored_and_manifest_defaults` (stored beats action default beats schema default).
- [ ] **Step 2:** Run `poetry run pytest tests/common/test_background.py tests/plugin/test_settings_schema_background.py tests/server/test_appearance_background_schema.py -q`; expect failures.
- [ ] **Step 3: Implement** `normalize_background`, register the `background` type in `settings_schema.py` (also in any place that lists field types for validation or client schema forms; grep for `"text_style"` to find every registry), update `APPEARANCE_SCHEMA`, and extend `resolve_appearance`.
- [ ] **Step 4:** Run the tests and `poetry run pytest tests/server tests/plugin tests/common -q`; expect pass.
- [ ] **Step 5: Commit** `feat: background setting value with legacy folding`.

### Task 2: Rendering the background (static and animated)

**Files:**
- Modify: `src/decker/server/appearance.py`, `src/decker/animation/model.py`, `src/decker/animation/factory.py`
- Test: `tests/server/test_appearance_background_render.py`, `tests/animation/test_animated_background.py`

**Interfaces:**
- Consumes: `normalize_background`/resolved `appearance["background"]` (Task 1), `AssetRenderer`, `decode_gif`, `is_animated_gif`.
- Produces: `compose_key_image(appearance, plugin_image, plugin_title, size=144, plugin_image_color=None, plugin_image_scale=1.0, background_image: bytes | None = None) -> bytes`: `_background_layer(appearance, size, background_image)` draws `none` as opaque black, `color` as today (colour with alpha over opaque black), `image` as the cover-fit of `background_image` over opaque black (SVG, PNG, JPEG, GIF first frame via `AssetRenderer`; decode failure or `None` falls back to black and logs at debug).
- Produces: `cover_fit(image: Image.Image, size: int) -> Image.Image` (public helper: scale to cover, centre-crop, square `size`).
- Produces: `compose_key_face(..., background_image: bytes | None = None, poster: bool = True) -> Composed`: an animation is produced for (a) an animated foreground GIF as today, which wins; else (b) when the background mode is `image` and `background_image` is an animated GIF: `AnimationSpec(gif=background_image, appearance, title, scale, layer="background", overlay=image, overlay_color=image_color)`.
- Produces: `AnimationSpec` gains `layer: str = "foreground"`, `overlay: bytes | None = None`, `overlay_color: str | None = None`; `animation_id` includes them (and the overlay's SHA) so ids change with the background image, mode, overlay and overlay colour.
- Produces: `compose_key_frames(appearance, frames, plugin_title, size=144, plugin_image_scale=1.0, *, layer="foreground", overlay=None, overlay_color=None) -> list[Image.Image]`: for `layer="background"` each frame is `cover_fit` to the key, composited over opaque black, then the static `overlay` (rendered at the scaled inner size with `overlay_color` tint) and the title are drawn on top; `layer="foreground"` behaves exactly as today. `factory._compose` passes the spec's new fields.

- [ ] **Step 1: Write failing tests:** `test_none_mode_is_black`; `test_color_mode_matches_legacy_output_byte_for_byte` (compare to the output of the old render for the same appearance: build the expected via the legacy path or a stored golden PNG built in the test from `Image.new`); `test_image_mode_png_covers_and_crops` (non-square source, checks corner pixels); `test_transparent_png_shows_black`; `test_svg_background_renders`; `test_missing_or_corrupt_image_falls_back_to_black_with_icon_and_title_drawn`; `test_gif_background_first_frame_is_the_poster`; `test_static_foreground_over_animated_background_yields_background_animation` (spec layer, overlay set); `test_animated_foreground_wins_over_animated_background` (spec is the foreground animation; background shows first frame); `test_animation_id_changes_with_background_overlay_color_and_mode`; `test_frames_composite_overlay_and_title_over_each_frame` (pixel checks); `test_compose_key_frames_foreground_layer_unchanged`.
- [ ] **Step 2:** Run the new tests; expect failures.
- [ ] **Step 3: Implement** per the interfaces; keep `compose_key_image` and `compose_key_face` under their pylint exemptions, and extract helpers to stay under 50 lines per method.
- [ ] **Step 4:** Run the new tests, `tests/animation`, `tests/server/test_appearance*.py`; expect pass.
- [ ] **Step 5: Commit** `feat: render image backgrounds and animated GIF backgrounds`.

### Task 3: Server wiring (library refs to bytes, preview, animation)

**Files:**
- Modify: `src/decker/server/plugins.py` (`_compose`), anything else that calls `compose_key_face` (grep shows only `_compose`)
- Test: `tests/server/test_plugins_background.py`

**Interfaces:**
- Consumes: `compose_key_face(..., background_image=...)` (Task 2), `IconPackManager.read_ref`.
- Behaviour: `_compose` reads `appearance["background"]["image"]["ref"]` through `self.icon_packs.read_ref` when the background type is `image` and passes the bytes as `background_image`; an uninstalled pack or an unreadable ref passes `None` (black fallback, icon and title still drawn). `preview_image`, `key_animation` and the hardware path all go through `_compose`, so they agree. `_expanded_appearance` must preserve the nested `background` untouched.

- [ ] **Step 1: Write failing tests** with a real `PluginManager` test harness like the existing `tests/server/test_plugins*.py` (read them first for how a live key and a fake `icon_packs` are set up): `test_image_background_from_a_library_ref_appears_in_the_composed_png`; `test_ref_to_uninstalled_pack_falls_back_to_black`; `test_preview_image_with_draft_background_matches_the_applied_result` (draft vs saved give identical PNGs); `test_gif_background_with_static_icon_registers_an_animation` (sink receives an `AnimationSpec` with `layer="background"`); `test_animated_icon_override_wins_over_gif_background`; `test_legacy_string_background_in_stored_appearance_still_renders`.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3: Implement** the read and the parameter pass-through.
- [ ] **Step 4:** Run the new tests and `tests/server`; expect pass.
- [ ] **Step 5: Commit** `feat: resolve background library images for key faces`.

### Task 4: Client `BackgroundEdit` and form integration

**Files:**
- Create: `src/decker/client/widgets/background_edit.py`
- Modify: `src/decker/client/widgets/schema_form.py` (builder + `_watch`), `src/decker/client/widgets/action_config_panel.py` only if it special-cases the `background` key (grep first), `src/decker/client/widgets/icon_edit.py` only if `set_show_colour(False)` is insufficient
- Test: `tests/client/widgets/test_background_edit.py`

**Interfaces:**
- Consumes: `normalize_background` (Task 1), `IconEdit` (with `set_show_colour(False)`), `ColorButton(alpha=True)`.
- Produces: `BackgroundEdit(QWidget)` with `value_changed` signal, `value() -> dict` and `set_value(value)` (normalising, no signal). A mode combo (None / Solid colour / Image), the colour button visible in colour mode, an `IconEdit` (no tint control) visible in image mode; the previously chosen colour and image are kept when switching modes. Registered in `schema_form._BUILDERS["background"]` and watched through `value_changed` in `_watch`. Rename user-visible text in the picker dialogs and tooltips to "Image library" in the same task if the strings live in files this task touches; the sweeping rename is Task 5.

- [ ] **Step 1: Write failing offscreen tests:** `test_modes_show_the_right_controls`; `test_value_round_trip_for_each_mode`; `test_legacy_string_value_shows_as_color_mode`; `test_switching_modes_keeps_the_other_modes_choice`; `test_changes_emit_value_changed_once`; `test_set_value_does_not_emit`; `test_schema_form_builds_background_field_and_reports_edits` (through the real `SchemaForm`/appearance form).
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3: Implement** the widget and register it.
- [ ] **Step 4:** Run the new tests and `tests/client`; expect pass.
- [ ] **Step 5: Commit** `feat: background mode editor`.

### Task 5: Rename to "image library", docs, gates

**Files:**
- Modify: user-visible strings in `src/decker/client/` (icon picker dialog titles, tooltips, tab labels, "Icon library"/"Icons" labels where they name the library), `README.md`, `CLAUDE.md` wording, `docs/plugins/*` (library wording only), a new `docs/key-backgrounds.md`, `docs/platform-support.md` only if it lists features per tier
- Test: update existing client tests that assert the old labels

- [ ] **Step 1:** grep the client for the library's user-visible names (`grep -rn "Icon library\|icon library\|Icons" src/decker/client`) and the docs (`grep -rIl -i "icon library" docs README.md CLAUDE.md`); change only labels and prose, never identifiers, RPC names, manifest keys, pack ids or config keys. Update the tests that assert changed labels.
- [ ] **Step 2:** Write `docs/key-backgrounds.md`: the three modes, value shape, legacy strings, cover-fit, GIF background rules (foreground GIF wins, static icon over an animated background), uninstalled-pack fallback, the unchanged protocol names, limitations (no scaling option, no tint, one animated source per key). Add a README line where appearance features are listed and a CLAUDE.md sentence on the nested `background` appearance setting.
- [ ] **Step 3:** Run `poe format`, `poe mypy`, `poe pylint`, `poe test`; all pass.
- [ ] **Step 4: Commit** `docs: image library naming and key backgrounds`.
