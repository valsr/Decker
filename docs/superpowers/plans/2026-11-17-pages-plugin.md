# Pages Plugin (`com.decker.pages`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a `com.decker.pages` plugin in the `decker-plugins` repo: **Next page**, **Previous page**, **Go to page**, plus static **Page indicator** and **Page name** presets.

**Architecture:** A python-runtime plugin (`decker >=0.4`) whose runtime actions call the new SDK methods `ctx.switch_page(...)` / `ctx.go_to_page(...)`; the two arrows draw the plugin's own Font Awesome caret SVGs recoloured; Go To uses the new `page` setting type; the two presets are `"static": true` actions that only carry templated title defaults.

**Spec:** `/work/decker/decker/docs/superpowers/specs/2026-11-17-page-navigation-design.md` (Decker side: `/work/decker/decker/docs/superpowers/plans/2026-11-17-page-navigation.md`, which must be implemented first)

**Repo:** `/work/decker/decker-plugins` (branch `feat/pages-plugin` from `origin/main`). Tests run against the Decker branch with `PYTHONPATH=/work/decker/decker/src` until the Decker pin can move.

## Global Constraints

- Plugin id `com.decker.pages`, name "Pages", version `1.0.0`, `"decker": ">=0.4"`, python runtime, no requirements, category "Utilities", author "Decker".
- Actions (ids start `com.decker.pages.`): `next`, `previous`, `goto` (runtime); `indicator`, `name` (`"static": true`).
- **Next / Previous:** gestures `["press"]`; settings `wrap` (bool, "Wrap around", default **false**) and `color` (color with `"alpha": true`, "Icon colour", default `#ffffff`); the key shows `assets/caret-right.svg` / `assets/caret-left.svg` recoloured and drawn at about 60% of the key.
- **Go to page:** gestures `["press"]`; setting `page` (type `page`, label "Page"); the plugin sets the fallback title `Go To <page name>` (empty while no page is chosen or the page was deleted); a press calls `ctx.go_to_page(page_id)` only when a page is chosen.
- **Presets:** `indicator` appearance default `{"title": {"text": "{page_index} / {page_count}", "position": "middle", "size": 24}}`; `name` default `{"title": {"text": "{page_name}", "position": "middle", "size": 16}}`; both have no settings.
- The two caret SVGs are copied **byte-for-byte** from `plugins/com.decker.fontawesome/solid/caret-left.svg` and `caret-right.svg` into `plugins/com.decker.pages/assets/`, with `assets/NOTICE.txt` crediting Font Awesome Free 7.3.1 (Icons: CC BY 4.0).
- decker-plugins conventions: ruff (line length 120), tests under `plugins/com.decker.pages/tests/`, the version rule (new plugin, no tag yet), add files by **explicit path**. Never push or open a PR without asking; CI there stays red until the Decker pin moves to a Decker commit with the new features (a handoff step).

## Review Focus

- A recoloured caret must be visible on the default black key (the SVG uses `currentColor`, which renders black): the colour setting actually reaches the drawing, including `#rrggbbaa`. (Task 2)
- A hand-edited or default-less colour (`None`, `"red"`, `"#12"`) must not crash the plugin or produce an invisible icon. (Task 2)
- Go To with no page, a deleted page, or garbage in `page`: no press effect, no crash, no stale title. (Task 3)
- A rename of the target page updates the title (the server re-sends settings). (Task 3)
- The asset files are the Font Awesome originals, unmodified, and ship in the package; the static presets ship with the plugin and need no process. (Task 1)

---

### Task 1: Skeleton, manifest and assets

**Files:**
- Create: `plugins/com.decker.pages/manifest.json`, `plugins/com.decker.pages/assets/caret-left.svg`, `plugins/com.decker.pages/assets/caret-right.svg`, `plugins/com.decker.pages/assets/NOTICE.txt`, `plugins/com.decker.pages/icons/pages.png` (generate with Pillow), `plugins/com.decker.pages/plugin.py` (stub classes), `plugins/com.decker.pages/tests/test_manifest.py`

**Interfaces:**
- Produces: the manifest per Global Constraints (five actions; the three runtime actions' `settings`; the two static presets with their `appearance` defaults); `plugin.py` registering `@action("com.decker.pages.next")`, `...previous`, `...goto` classes (bodies in Tasks 2–3).

- [ ] **Step 1: Branch** `git fetch origin && git switch -c feat/pages-plugin origin/main`; copy the design/plan links nowhere (docs live in the decker repo).
- [ ] **Step 2: Failing tests** (`PluginManifest.load`, `pack_all` as in the fontawesome tests): `test_manifest_is_valid_and_gated_on_0_4` (id, name, version, `decker == ">=0.4"`, `is_compatible(">=0.4", "0.3.0")` false), `test_five_actions_with_the_expected_ids_and_static_flags`, `test_runtime_action_settings` (next/previous have `wrap` bool default false and `color` with alpha default `#ffffff`; goto has one `page` field), `test_presets_are_static_with_templated_title_defaults` (exact `appearance` defaults, no settings), `test_caret_assets_are_the_font_awesome_originals` (bytes equal to the fontawesome pack's files), `test_notice_credits_font_awesome`, `test_icons_resolve`, `test_packages_with_assets_and_without_tests` (`pack_all` on a staged copy: the zip contains `assets/caret-left.svg`, `assets/caret-right.svg`, `manifest.json`, `plugin.py`, and no `tests/`).
- [ ] **Step 3: Run** `cd /work/decker/decker-plugins && PYTHONPATH=/work/decker/decker/src .venv/bin/python -m pytest plugins/com.decker.pages -q -p no:cacheprovider` — Expected: FAIL.
- [ ] **Step 4: Implement** the files (copy the SVGs with `cp`, never edit them).
- [ ] **Step 5: Run** the same command and `.venv/bin/ruff check .` — Expected: PASS / clean.
- [ ] **Step 6: Commit** `feat: Pages plugin skeleton with manifest, caret assets and presets` (explicit paths).

### Task 2: Next and Previous

**Files:**
- Modify: `plugins/com.decker.pages/plugin.py`
- Test: `plugins/com.decker.pages/tests/test_arrows.py`

**Interfaces:**
- Consumes: SDK `ActionContext.switch_page(to, wrap)` and `set_image(data, format)`.
- Produces: `render_caret(svg: bytes, color: str) -> bytes` — replaces `currentColor` with `color[:7]`, sets the root `fill-opacity`/`opacity` from an `#rrggbbaa` alpha, and widens the root `viewBox` to a centred square so the caret fills about 60% of it; invalid colours fall back to `#ffffff`. `ArrowAction(DeckerPlugin)` with a `direction` (`"next"`/`"previous"`): `on_will_appear`/`on_settings_changed` call `ctx.set_image(render_caret(...), "svg")`; `on_press` calls `ctx.switch_page(direction, wrap=bool(ctx.settings["wrap"]))`.

- [ ] **Step 1: Failing tests** (SDK loop on pipes, like `test_icon.py`): `test_next_shows_the_right_caret_in_the_chosen_colour` (the `set_image` payload is svg; decode and render it with Decker's renderer: the centre pixel is the colour), `test_previous_shows_the_left_caret` (left vs right renders differ, mirrored), `test_default_colour_is_visible_on_black` (white pixels present), `test_rgba_colour_has_partial_alpha`, `test_caret_is_about_sixty_percent_of_the_key` (ink bounding box height roughly 0.6 of the image, centred), `test_invalid_colours_fall_back_to_white` (parametrised: `None`, `"red"`, `"#12"`, `5`), `test_settings_changed_redraws_with_the_new_colour`, `test_press_sends_switch_page_next_with_wrap_false_by_default`, `test_press_sends_wrap_true_when_enabled`, `test_previous_press_sends_previous`, `test_render_caret_leaves_other_svg_content_alone` (everything after the root tag is unchanged except the `currentColor` replacement).
- [ ] **Step 2: Run** `PYTHONPATH=/work/decker/decker/src .venv/bin/python -m pytest plugins/com.decker.pages -q -p no:cacheprovider` — Expected: FAIL.
- [ ] **Step 3: Implement** with plain string/regex handling (no extra dependencies); read the SVG files relative to `__file__`.
- [ ] **Step 4: Run** the same command plus `.venv/bin/ruff check .` — Expected: PASS / clean.
- [ ] **Step 5: Commit** `feat(pages): next and previous page keys` (explicit paths).

### Task 3: Go to page

**Files:**
- Modify: `plugins/com.decker.pages/plugin.py`
- Test: `plugins/com.decker.pages/tests/test_goto.py`

**Interfaces:**
- Consumes: SDK `ActionContext.go_to_page(page_id)` and `set_title`; the delivered setting `{"page_id", "name", "index"}`.
- Produces: `GotoAction(DeckerPlugin)`: `on_will_appear`/`on_settings_changed` set the title `Go To <name>` when a page is chosen, else `""`; `on_press` calls `ctx.go_to_page(page_id)` only when `page_id` is a non-empty string.

- [ ] **Step 1: Failing tests:** `test_title_is_go_to_the_page_name` (`{"page_id": "p2", "name": "Settings", "index": 2}` -> `set_title` payload `{"title": "Go To Settings"}`), `test_press_goes_to_the_chosen_page`, `test_no_page_chosen_has_an_empty_title_and_press_does_nothing`, `test_deleted_page_resolves_empty_so_nothing_happens` (the server's `{"page_id": "", "name": "", "index": 0}`), `test_garbage_page_value_does_not_crash` (parametrised: `None`, `"p2"`, `5`, `{"page_id": 5}`, `[]`), `test_rename_updates_the_title` (a `settings_changed` with the new name), `test_names_with_braces_or_newlines_are_passed_through_as_text` (`"A {b}\nC"`; the server collapses line breaks), `test_press_after_rename_still_uses_the_page_id`.
- [ ] **Step 2: Run** `PYTHONPATH=/work/decker/decker/src .venv/bin/python -m pytest plugins/com.decker.pages -q -p no:cacheprovider` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same command plus `.venv/bin/ruff check .` — Expected: PASS / clean.
- [ ] **Step 5: Commit** `feat(pages): go to page key` (explicit paths).

### Task 4: Gates and handoff

**Files:** none new.

- [ ] **Step 1: Run** `.venv/bin/ruff check .`, `PYTHONPATH=/work/decker/decker/src .venv/bin/python -m pytest -q -p no:cacheprovider` (all plugins and tools), and `PYTHONPATH=/work/decker/decker/src .venv/bin/python -m tools.pack_all --out <scratch>`; confirm `com.decker.pages-1.0.0.deckerplugin` builds. Expected: clean, all green, package built.
- [ ] **Step 2: End-to-end check** with the Decker branch: compose the Next/Previous key images from the plugin's `set_image` payloads (white caret at about 60% on black) and a Blank-style key with the indicator preset's title on page 2 of 3, to PNGs; view and report.
- [ ] **Step 3: Handoff** — do NOT push. Tell the user that CI here stays red until the Decker branch is merged and the pin in `pyproject.toml` + `uv.lock` moves to a Decker commit containing `switch_page`, the `page` type and static actions; ask whether to push and open the PR.
