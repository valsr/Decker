# Page navigation, templating, static actions and a built-in Blank — design

Status: awaiting approval. Size: project (two repos: `decker`, `decker-plugins`).

## Intent

Let a user flip a Stream Deck's pages from the keys themselves: **Next page**, **Previous page**, **Go to <page>**, and show
where they are. Showing "where you are" is not a plugin of its own: Decker already draws every key's title, so the title
learns **variables** (`{page_name}`, `{page_index}`, `{page_count}`) and a built-in **Blank** action gives a key that is
only a background and a title. Plugins can also ship **static actions**: ready-made presets that are just appearance.

## Goals

- **Templating (opt-in):** a text field expands `{variable}` only when its schema declares `"template": true`. Decker's own key
  Title does. Variables: `{page_name}`, `{page_index}` (1-based), `{page_count}`, for the device the key is on. `{{` and `}}`
  are literal braces; an unknown `{name}` is left exactly as typed; one pass, no recursion, plain substitution (no code
  evaluation, no format specs).
- **Live:** the title is expanded when the key is drawn; keys on a device refresh when that device's pages are renamed, added
  or deleted; a page switch redraws every key anyway.
- **`page` settings type:** a dropdown of the selected key's device pages. Stored as the page id (a rename never breaks it).
  The plugin receives `{"page_id", "name", "index"}` resolved by the server; a deleted or unset page arrives as
  `{"page_id": "", "name": "", "index": 0}`. Action settings only (rejected in `global_settings`).
- **Protocol:** plugin to server `switch_page`: `{"to": "next"|"previous"|"first"|"last", "wrap": false}` or `{"page_id": "<id>"}`.
  The server resolves it for the context's device and activates the page. SDK: `ctx.switch_page(to="next", wrap=False)`,
  `ctx.go_to_page(page_id)`.
- **Static actions:** a manifest action may declare `"static": true`: no code handles it, no process is started for it, a press
  does nothing, and the key shows its Decker-drawn appearance (defaults from the action's `appearance`, plus `states[0]`).
  A plugin with only static actions needs no `runtime`.
- **Built-in Blank:** `com.decker.blank`, one static action "Blank", ships inside Decker. It is listed like any action and cannot
  be uninstalled or replaced.
- **`com.decker.pages`** (in `decker-plugins`), gated on `"decker": ">=0.4"`:
  - **Next page** / **Previous page**: draw the Font Awesome solid `caret-right` / `caret-left` (copied into the plugin's
    `assets/`), in a configurable colour; settings: *Wrap around* (default off), *Icon colour* (RGBA, default white).
  - **Go to page**: a `page` setting; shows the title "Go To <page name>" as the plugin's fallback title (a title the user typed
    still wins); a press goes to that page; does nothing while no page is chosen.
  - Static presets **Page indicator** (title `{page_index} / {page_count}`) and **Page name** (title `{page_name}`), centred and
    large by default.
- Decker becomes **0.4.0**.

## Non-goals

- Reordering pages; selecting pages by number; long-press shortcuts (first/last page).
- More variables (device name, key index, time) — the variable provider is one small function, so adding them later is cheap,
  but none ship now.
- Nested or recursive templates, formatting (`{page_index:02d}`), expressions.
- A `pages_changed` event for plugins: the indicator needs none (it is a static, templated title).
- `page` fields in plugin-wide `global_settings` (there is no device there).

## Anti-goals

- Templating that mangles text it was not asked to touch (hence opt-in and "unknown names stay").
- A page switch that can deadlock the plugin manager (see the lock-order note below).
- A plugin that overwrites a user's raw template by writing back the expanded text.

## Approaches considered

1. **Server-side templating, opt-in per field (chosen).** Stored settings stay raw; Decker expands when it draws the title and when
   it delivers settings to a plugin. One implementation for every plugin; the user always edits what they typed.
2. Plugin-side expansion (Decker sends the variables, each plugin substitutes). Every plugin would need the same code and a
   `pages_changed` event; the indicator would need a runtime again.
3. A repository Text plugin for the indicator. Rejected by you: the title already draws text.
4. Static actions vs `"extends": "com.decker.blank.blank"` inheritance. Static actions chosen: presets need no new inheritance
   concept, only the `appearance` defaults manifests already have.

## Design

### decker (new branch `feat/page-navigation`)

- **Templating** — `common/template.py`: `expand_template(text: str, variables: Mapping[str, str]) -> str` (regex
  `\{([a-z_][a-z0-9_]*)\}` with `{{`/`}}` escapes). Schema: `text` and `text_style` fields accept `"template": bool` (default
  false; validated like `multiline`); `APPEARANCE_SCHEMA`'s `title` declares `"template": True`. `PluginManager` builds the
  variables for a live key from `page_controller.device_pages(device_id)` (position of the active page, its name, the count).
  `_compose` expands the title text; `_send_will_appear`/`settings_changed` deliver an expanded copy of the settings (the stored
  copy stays raw). A new `PluginManager.refresh_page_dependent(device_id)` recomposes the device's live keys and re-sends
  `settings_changed` to those whose expanded or page-resolved settings changed; `PageController._notify` calls it.
- **`page` type** — `settings_schema.py`: `FIELD_TYPES += "page"`, value a string id (default `""`), rejected in
  `global_settings`. A server-side resolver turns the stored id into `{page_id, name, index}` when settings are delivered.
  Client: `SchemaForm` builds a dropdown from `pages_list(device_id)` of the selected key's device (a small form context carries
  the device id and the RPC); it shows a "(deleted page)" entry for a stored id that no longer exists and is disabled with a hint
  when no device is selected.
- **Protocol** — `PluginManager._route_context_message` handles `switch_page` outside the manager lock (page switches take the
  controller lock and deactivate actions, which take the manager lock; doing it under the manager lock would invert the order).
  Unknown page, a single page, or a no-wrap edge are logged and ignored. `decker_plugin_sdk`: `ActionContext.switch_page`,
  `go_to_page`.
- **Static actions** — `manifest.py`: `"static": bool` on actions; `runtime` optional when every action is static; a static action
  may not declare `settings` or `gestures`. `PluginManager.activate_action` composes a static key without `supervisor.acquire`
  or `will_appear`; key and gesture events for it are dropped.
- **Built-in Blank** — `src/decker/builtin_plugins/com.decker.blank/` (manifest + icon) shipped in the package; `PluginLoader`
  also scans that folder, read-only; the installer and repository installs refuse its id ("built into Decker") and Settings,
  Plugins shows it without an Uninstall button. `CLAUDE.md` and the overview docs change from "ships no plugins" to "ships one
  built-in static plugin, Blank".
- Docs: `settings-schema.md` (`template`, `page`), `package-and-manifest.md` (`static`, built-in plugins), `protocol.md`
  (`switch_page`, settings delivery), `sdk-quickstart.md`.

### decker-plugins (new branch)

- `plugins/com.decker.pages/` (python runtime, no requirements, `decker >=0.4`): manifest with the five actions above,
  `plugin.py` (Next/Previous share one class with a direction; Go To), `assets/caret-left.svg`, `assets/caret-right.svg` (copied
  byte-for-byte from `com.decker.fontawesome/solid/`, with a short notice file crediting Font Awesome Free, CC BY 4.0), tests.
- The caret is drawn by replacing `currentColor` in the plugin's own SVG with the chosen colour and sending it as `set_image`
  (format svg); the plugin widens the SVG's `viewBox` so the caret sits at about 60% of the key.

## Constraints

- Decker conventions (black 120, full annotations, <= 50-line methods, <= 5 args, mypy, pylint, coverage >= 85%); decker-plugins:
  ruff, plugin tests under the plugin's `tests/`, the version rule, Decker pin moved after the Decker branch is pushed.
- Existing manifests and stored settings keep working: `template` and `static` default to false; no behaviour changes for plugins
  that use neither.

## Calls made without you

- `{page_index}` is 1-based (page 3 of 5 shows `3`).
- Wrap around defaults to **off**; Next on the last page does nothing, Previous on the first does nothing.
- Static presets live in `com.decker.pages`; Blank is the only built-in.
- A deleted page in a Go To key shows the key with no title and does nothing (and the dropdown marks it "(deleted page)").
- Expanded settings go to plugins; a plugin that writes settings back with `set_settings` should send only what it changed
  (documented). Stored templates are not overwritten by delivery.

## Open points

- Whether the `{page_*}` variables should also expand in plugin text fields that declare `"template": true` on a **global** setting:
  no device there, so they would stay literal. Proposed: they stay literal and the docs say so.
- Built-ins and "Update all"/repository shadowing: proposed that a repository plugin with a built-in id is ignored with a warning.

## Left to the builder

The exact variable-provider shape, the form-context object for `SchemaForm`, icon artwork for Blank, how the plugin pads the
caret's `viewBox`, test layout.
