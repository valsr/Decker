# Decker plugin format v1

## Intent

Decker gets its own plugin format, modelled on what Elgato's Stream Deck SDK got right, that **anyone** can
write plugins for and share. Plugins are therefore untrusted third-party code: a broken or misbehaving plugin
must never take down the server, other plugins, or the user's devices.

The same package format is Decker's **one way of adding things**: a plugin package *contributes* one or more
kinds of content — key actions, icon packs, and in future other Decker features such as screensavers. Icon packs
are installed as plugins (replacing today's separate Elgato-style `.streamDeckIconPack` install); the icon
library's own content structure (icon metadata, search, tags) is a separate design that plugs into the
`icon_packs` contribution defined here.

## Goals

- A documented, versioned package format and manifest that a third party can build against without reading
  Decker's source.
- One package format for every kind of contribution: `actions` and `icon_packs` in v1, with room to add new
  kinds (e.g. `screensavers`) without changing the package, install or uninstall machinery.
- A package that contributes no actions (e.g. a pure icon pack) has no code and no process.
- Every plugin runs in **its own process**, talking to the server over a **language-neutral JSON protocol on
  stdin/stdout**. Decker ships a **Python SDK** so authors keep writing `@action` classes much like today.
- Each Python plugin gets **its own private environment**, built at install time with `uv` from the
  requirements its manifest declares.
- Action settings are **declared in the manifest**; the client renders a native form from the declaration.
  No plugin code runs in the client, and the client never hard-codes a plugin's form.
- **Title and background are drawn by Decker for every action** from per-key appearance settings, so plugins
  don't each reimplement them.
- Install from the client by dropping a `.deckerplugin` file on the main window or via
  Settings → Plugins → Install; uninstall from Settings → Plugins. No restart of server or client.
- The bundled Counter plugin is ported to the new format and is the reference example.

## Non-goals (v1)

- Marketplace / online catalogue, plugin updates from the internet.
- Enforcing permissions or verifying signatures (the manifest reserves fields for both).
- SDKs for languages other than Python (the protocol allows them; see the `executable` runtime).
- The icon library's content structure (separate design; reserved reference syntax below) and screensavers
  (the contribution kind is reserved, not designed).
- Keeping the Elgato `.streamDeckIconPack` / `.sdIconPack` install path.
- Stream Deck+ dials/touch strip, profiles, multi-actions, localisation of plugin strings.
- Backwards compatibility with today's in-process `plugin.py` format — Decker is early alpha and the only
  plugin is the bundled Counter, which is ported.

## Anti-goals

- A plugin crash, hang or memory leak restarts the server or drops devices.
- A plugin's dependencies conflict with Decker's or another plugin's.
- Unpacking a package can write outside its own plugin folder.
- The client executes plugin code (e.g. to render a settings form).

## Trust model (v1)

Plugin code — including the build steps of its Python dependencies — runs as the user, with the user's
permissions; v1 has **no sandbox**. Isolation in v1 is about *stability* (a plugin can't crash or hang the server,
devices or other plugins), not security. Installing a plugin means trusting its author, as with any desktop
app; the UI says so on install. `permissions` and signatures are reserved so a later version can add real
restrictions.

## Constraints

- Server is headless, supervised by the monitor (1 GiB RSS limit on the *server* process — plugin processes
  are children but measured separately). Multiple clients, possibly remote.
- Page model: only the active page's actions are live; `PageController` owns switches. Plugin instances get
  appear/disappear exactly when native actions are activated/deactivated today.
- Quality gates: `poe format`, mypy, pylint ≥ 9.0, coverage ≥ 85%.

## Approaches considered

**Language of plugins** (decided by the user):
1. Python-only via a Python-specific channel (e.g. RPyC) in a subprocess — fastest, but locks out other
   languages.
2. **Language-neutral JSON protocol over stdio + a Python SDK — chosen.** More protocol design up front;
   any language can implement it later; authoring stays `@action` classes.
3. Several language SDKs from day one — much more work with no non-Python authors yet.

**Third-party Python libraries** (decided by the user):
1. **Per-plugin environment built at install from declared requirements, using `uv` — chosen.** Isolated;
   install needs internet when requirements are declared.
2. Libraries bundled inside the package — offline, but large and platform-specific for compiled wheels.
3. No extra libraries — simplest, too limiting.

**Settings UI** (proposed, not contested): declarative schema rendered natively by the client, instead of
Elgato-style HTML property inspectors (which need a browser engine and run plugin code in the client).

## Design

### 1. Package

- A plugin is a folder whose contents are packaged as a zip with the extension `.deckerplugin`
  (e.g. `com.example.weather-1.2.0.deckerplugin`). `manifest.json` sits at the **archive root**.
- Installed to `~/.decker/plugins/<plugin id>/` with its environment in `~/.decker/plugins/<plugin id>/.venv`
  (or an equivalent location chosen by the builder, as long as uninstall removes it).
- Paths inside the archive use `/`; entries with `\`, absolute paths, `..` components or symlinks are rejected.

### 2. Manifest (`manifest.json`)

JSON, snake_case keys. Unknown keys are ignored (forward compatibility); unknown `format` versions are rejected.

```json
{
  "format": 1,
  "id": "com.decker.counter",
  "name": "Counter",
  "version": "1.0.0",
  "author": "Decker",
  "description": "Counts key presses.",
  "homepage": "https://github.com/valsr/Decker",
  "icon": "icons/plugin",
  "category": "Utilities",
  "decker": ">=0.2",
  "runtime": {
    "type": "python",
    "entry": "plugin.py",
    "python": ">=3.12",
    "requirements": []
  },
  "permissions": [],
  "global_settings": [],
  "contributes": {
   "icon_packs": [
    { "id": "com.decker.counter.icons", "name": "Counter icons", "path": "iconpack" }
   ],
   "actions": [
    {
      "id": "com.decker.counter.counter",
      "name": "Counter",
      "tooltip": "Press to count, long press to reset",
      "icon": "icons/counter",
      "gestures": ["press", "long_press"],
      "states": [{ "image": "icons/counter" }],
      "settings": [
        { "section": "Counting" },
        { "key": "step", "type": "int", "label": "Step", "default": 1, "min": 1, "max": 9999 },
        { "key": "double_step", "type": "int", "label": "Double press step", "optional": true,
          "placeholder": "None (presses register immediately)" },
        { "key": "max", "type": "int", "label": "Max count", "default": 0, "min": 0,
          "special_value": "∞ (no limit)" }
      ]
    }
   ]
  }
}
```

- `id`: reverse-domain identifier (existing `_UUID_PATTERN`); every contribution id (action, icon pack, …) is
  prefixed by the plugin id.
- `contributes`: an object keyed by contribution kind; at least one kind must be present. v1 kinds:
  - `actions` — key actions (below). Requires `runtime`.
  - `icon_packs` — `{id, name, path, description?}`; `path` is a folder inside the package holding the pack's
    icons in the structure defined by the icon library design (until then: image files, optionally with an
    `icons.json` index). Needs no `runtime`.
  - Reserved for later: `screensavers`, `themes`. A package using a kind this Decker doesn't know is refused at
    install with "requires a newer version of Decker" (the `decker` version field should normally catch it first).
- `runtime` is required only if a contribution needs code (in v1: `actions`); packages without it never start a
  process or create an environment.
- `version`: semver. `decker`: version specifier for the minimum Decker version; install refuses a mismatch.
- `runtime.type`:
  - `python` — run `entry` with the plugin's own environment; `requirements` are pip requirement strings;
    `python` is an optional version specifier (`uv` provides the interpreter if needed). Requirements must be
    package-index requirements (name + version specifier, optional extras/markers); URL, git and local-path
    requirements are rejected. uv's normal shared cache is used. *(My call, from the builder check.)*
  - `executable` — run `entry` directly (any language implementing the protocol). Supported in v1 with no SDK.
- `icon` / `states[].image`: a path inside the plugin folder, extension optional (existing lookup: `.svg`,
  `@2x.png`, `.png`). Values starting with `pack:` are **reserved** for the icon library
  (`pack:<pack id>/<icon name>`) and treated as missing until that design lands.
- `permissions`, and a future `signature` file in the archive, are reserved and ignored in v1.
- `gestures`: the default gesture set for the action (`press`, `double_press`, `long_press`); a running plugin
  can change it per key instance (protocol `set_gestures`), replacing today's `gestures(settings)` method.
- `states`: optional list of visual states (image and/or default title), selected by `set_state`.
- `appearance`: optional per-action defaults for the Decker-drawn appearance (section 4), e.g.
  `{"background": "#1f618d", "title_position": "bottom"}`, used until the user changes them. The Counter uses
  this to keep its blue look. *(My call, from the builder check.)*

### 3. Settings schema

An ordered list of entries rendered top to bottom as a form. Entry kinds:

- `{ "section": "Title" }` — a heading.
- Fields: `key`, `type`, `label`, `default`, optional `optional` (empty allowed → `null`), `placeholder`,
  `help`. Types and their extra keys:
  - `int` (`min`, `max`, `step`, `special_value` shown at `min`), `float` (`min`, `max`, `step`, `decimals`)
  - `text` (`multiline`), `bool`, `choice` (`options: [{ "label", "value" }]`), `color` (`#rrggbb`),
    `font` (family name), `icon` (reserved for the icon library; a plain file path until then)
- The **server** validates values against the schema and fills defaults, so plugins always receive a complete,
  typed settings dict, and the client never duplicates defaults.
- `global_settings` uses the same schema and is shown in Settings → Plugins for that plugin.

### 4. Decker-drawn appearance

Every key has appearance settings managed by Decker, independent of the plugin: background colour, title
text, title position (top/middle/bottom), font, size, colour, outline colour/width, and show/hide title.
The server composes the key image: background → plugin image (or current state image) → title. The plugin's
`set_title` supplies a title shown only when the user hasn't set one (Elgato behaviour). The ported Counter
draws the count in its image and no longer calls `set_title`, so the count isn't shown twice. The client's config
panel shows an **Appearance** section for every action, followed by the plugin's own settings. The Counter's
current background/title fields move here; its plugin settings shrink to step, double-press step and max.

### 5. Protocol (stdin/stdout, newline-delimited JSON)

Every message is one JSON object per line: `{"event": "...", "context": "...", "payload": {...}}`
(`context` = Decker's per-key context id; omitted for plugin-wide events). stdout is reserved for the protocol;
stderr is captured into the server log, prefixed with the plugin id. The SDK redirects `print` to stderr.

Server → plugin:
- `hello` — `{protocol: 1, decker_version, plugin_id, global_settings}`; first message.
- `will_appear` / `will_disappear` — `{action, device, key: {index, column, row}, settings, state}`.
- `key_down` / `key_up` (raw), `press` / `double_press` / `long_press` (recognised by the server's existing
  gesture recogniser, per the instance's registered gestures).
- `settings_changed` — `{settings}`; `global_settings_changed` — `{global_settings}`.
- `device_connected` / `device_disconnected` — `{device}`.
- `ping` (expects `pong`), `shutdown` (process should exit within a grace period).

Plugin → server:
- `ready` — sent after `hello`; events are queued until it arrives.
- `set_image` — `{image: <base64>, format: "png"|"jpeg"|"svg"}` or `{image: null}` to clear.
- `set_title`, `set_state` (`{state: n}`), `show_alert`, `show_ok`.
- `set_settings` (per context), `set_global_settings`.
- `set_gestures` — `{gestures: [...]}` for that context.
- `log` — `{level, message}`; `open_url` — `{url}`: only `http`/`https` URLs are accepted; the event is pushed
  to every connected client, and each client asks the user before opening it ("<plugin> wants to open <url>").
  *(My call, from the builder check.)*
- `pong`.

Malformed messages are logged and dropped; a plugin that sends a flood or never answers `ping` is killed.

### 6. Process lifecycle and isolation (server)

- A plugin's process starts when its first action instance appears and stops after its last one disappears,
  following a short idle grace period so page flips don't respawn it.
- Crash: restart with backoff; after repeated crashes within a window the plugin is marked failed, its keys
  show an alert, and a `PluginLoadFailedEvent`-style notice reaches clients. It is retried on the next
  activation after the user intervenes (e.g. re-saves settings) or on server restart.
- Resource limits: the server samples each plugin process's RSS and kills it over a configurable limit
  (default 256 MiB); an unanswered `ping` within a timeout counts as a hang.
- The process runs with the plugin folder as its working directory and a minimal environment.

### 7. Python SDK

- A small dependency-free package (`decker_plugin_sdk`, living in this repo) installed into each plugin's
  environment at install time. It provides `DeckerPlugin`, `@action`, `ActionContext` (same handler names as
  today: `on_will_appear`, `on_press`, … plus `on_global_settings_changed`), runs the stdio loop, and maps
  `ctx.set_image(...)` etc. to protocol messages.
- Handlers run off the reading thread so a slow handler doesn't block `ping`.
- `poe cli plugin pack <folder>` validates a plugin folder and writes the `.deckerplugin` archive;
  `poe cli plugin new <id>` scaffolds a template (manifest, `plugin.py`, icon).

### 8. Contribution registry (server)

Installed and bundled packages are loaded into a registry keyed by contribution kind. Each kind has a handler
that knows how to validate, register and unregister its contributions:

- `actions` → the plugin process manager and action list (`list_actions`).
- `icon_packs` → the existing icon pack store/picker (`IconPackStore`, `icon_picker.py`), now fed from installed
  packages instead of `~/.decker/assets/iconpacks/`, with listings and images served by the server rather than
  read from the client's disk. The `pack:` reference syntax is reserved for the icon library design.

Install and uninstall are kind-agnostic; adding a future kind (e.g. screensavers) means adding a handler, not
changing the package format or install flow.

### 9. Install / uninstall

- Client: **Install…** button in Settings → Plugins and drag-and-drop of `.deckerplugin` files onto the main
  window send the bytes to a new RPC `install_plugin(filename, data)`. Install runs in the background on the
  server and reports progress/result via pushed events (environment creation can take a while). The CLI's
  install/remove/list go through the same server RPCs, so no restart is needed anywhere.
- Who may install/uninstall: by default only clients connecting from the server's own machine (loopback). A
  config setting (`server.allow_remote_plugin_install`, default `false`) allows remote clients too. Remote
  clients can always use, configure and browse plugins; when installing isn't allowed, their Install button and
  drop target are disabled with an explanation. The CLI follows the same rule. *(User decision.)*
- Server validation before writing anything: size caps (upload and uncompressed), zip safety (above),
  manifest schema, `format` supported, `decker` version satisfied, not a bundled plugin id.
- Extract to a temporary folder in the plugins dir; for `python` runtimes create the environment with `uv`
  (`requirements` + the SDK); on success atomically move into place. Installing an id that is already
  installed replaces it (live instances are stopped and re-appear after).
- Uninstall (user-installed plugins only): confirmation states how many keys use it; the server stops the
  process, clears those key assignments on all pages/devices along with their settings and images, removes
  the folder and environment, and pushes the change to clients.
- Settings → Plugins lists plugins (icon, name, version, author, bundled/installed, and what each contributes,
  e.g. "2 actions · 1 icon pack") with Uninstall, the global settings form when declared, and the existing
  load-failure list.
- In v1, icon packs are installed, listed and browsable (the server serves pack listings and icon images to
  clients over RPC, so remote clients work). Assigning a pack icon to a key, and the stored reference format,
  belong to the icon library design, which follows next. *(My call, from the builder check.)*
- Existing icon packs in `~/.decker/assets/iconpacks/` are not migrated automatically (early alpha); the CLI's
  `iconpack` commands are replaced by the plugin commands.

### 10. Bundled plugins

- Ship inside Decker in the same format. They run with Decker's own interpreter (no per-plugin environment)
  and may only use libraries Decker already depends on (e.g. Pillow for the Counter). They cannot be
  uninstalled.
- The Counter is ported: manifest above, `gestures`/`set_gestures` replaces `gestures(settings)` (double press
  registered only when `double_step` is set), image rendering keeps the count, appearance moves to Decker.
  Existing users' counter settings for background/title are migrated into the new per-key appearance settings.

### 11. Removed

The in-process native loader (`native_loader.py`, in-process `ActionRegistry`/`PluginExecutor` dispatch) and
the client's hard-coded counter form (`ActionConfigPanel` counter page, `COUNTER_DEFAULTS`), and the Elgato-style
icon pack install path (`IconPackManager.install` for `.streamDeckIconPack`/`.sdIconPack`, `poe cli iconpack`).

## Left to the builder

Module layout; where environments live; exact size caps, timeouts, backoff and grace periods; how the SDK is
installed into environments (local wheel or path); progress-event shape; schema validation implementation;
how appearance settings are stored; whether `executable`-runtime support gets more than a protocol-level test.

## Success check

1. `poe cli plugin new com.example.hello` → edit → `poe cli plugin pack` → drop the `.deckerplugin` on the
   window → its action appears without restarting anything, and its settings form renders from the manifest.
2. A plugin declaring `requests` installs into its own environment and uses it.
3. A plugin that raises, hangs or allocates without limit is killed/restarted alone; devices and other plugins
   keep working.
4. Counter works as before (press, double press only when set, long press reset), with title and background
   now set in the Appearance section.
5. Uninstalling a plugin clears its keys and removes its folder and environment.
6. A package containing only an icon pack installs without creating an environment or starting a process, and
   its icons can be browsed in the icon picker (including from a remote client); uninstalling removes them.
