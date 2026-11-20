# Plugin variables and plugin lifecycle — design

Status: draft for approval. Date: 2026-11-20. Project 1 of 2: the Media plugin (project 2, `com.decker.media` in
`decker-plugins`) is designed afterwards and builds on this.

## Intent

Today templated text (`{page_name}` and friends) can only use five variables the server owns. Plugins need to export
their own values (a volume, a counter, a track title) for other plugins' cards and the user's own key text to use.
This adds **plugin variables**, and the **plugin lifecycle** (`init`, `main`) a plugin needs to keep those values
current while no card of it is on a key.

## Behaviour

### Declaring and owning variables

- A plugin declares its variables in the manifest, under `contributes.variables`:

  ```json
  "variables": [
    { "name": "media_default_volume", "description": "Volume of the default output, 0-100" },
    { "pattern": "media_{device}_volume", "description": "Volume of an output device, 0-100" }
  ]
  ```

  An entry has either `name` (an exact variable) or `pattern` (a family whose concrete names the plugin registers at
  runtime). `{device}`-style placeholders each stand for one or more `[a-z0-9_]` characters.
- Names are lowercase `[a-z][a-z0-9_]*`, at most 64 characters (the template syntax already accepts exactly this).
- **Ownership is the declaration.** The declaring plugin owns the name or pattern. No other plugin can set it.
  The loader rejects (a recorded plugin load failure) a plugin that declares a name equal to a core variable
  (`page_name`, `page_index`, `page_count`, `current_profile`, `profile_id`), to another loaded plugin's exact name,
  or to another plugin's identical pattern. A concrete name a plugin registers at runtime that another plugin
  already owns, or that matches no pattern of its own, is refused with a log line.
- Variables are global. They are not per device or per key. (Page and profile variables stay per device and stay
  server-owned.)

### Values

- A variable's value is produced by a **getter** in the plugin's code. The getter returns `str`, `int`, `float`,
  `bool` or `None`; the server stores its text form (`None` = unset).
- The server keeps a **cache** of the last value of each variable. Text expansion only ever reads the cache; the
  server never calls a plugin while drawing a key.
- The server asks the plugin for a value (a `get_variable` request, answered off-thread with a timeout) at plugin
  start for every registered variable, and again whenever the plugin signals that one changed. A getter that fails or
  times out keeps the old value and logs.
- A plugin signals a change with `signal_variable_updated(name)`. The server then refreshes the cache and redraws
  every live key whose text uses that variable (a key text uses it when it has a `template: true` text containing
  `{name}`).
- **Unset values:** a declared (exact or matching a pattern) but unset or stopped variable expands to an empty
  string. A name nobody declared stays as typed, as it does today. A plugin that stops or crashes drops its cached
  values (they are never shown stale); they return when it restarts and its getters answer.

### Reading variables from the SDK

- `get_variable(name)` returns the value of any global variable as a string, or `None` if it is unset or unknown;
  `has_variable(name)` returns whether it is set. They read a local copy, so they are instant: the server pushes
  changes of all global variables to every running plugin. A plugin's own signals update its copy at once.
- Page and profile variables (per device) are not readable from the SDK in v1.

### Always-on plugins and the lifecycle hooks

- A plugin whose manifest declares at least one variable is **started with the server and kept running** (it holds a
  permanent supervisor reference). Crash restarts, back-off and the watchdog work as for any plugin. Plugins that
  declare no variables keep today's lazy start.
- A Python plugin can define two hooks, each with a sync or an `async` form:
  - `init`: run once per process start, in its own thread, after the plugin has sent `ready`. It registers
    variables, reads initial state and restores saved values. `ready` is not delayed by it, so a slow `init` cannot
    trip the 10 s ready timeout or delay `will_appear`. If `init` raises, the error is logged, `main` does not
    start, and the process keeps serving actions and cards.
  - `main`: optional. If present, it is called repeatedly in its own thread, with a pause of `interval` seconds
    between calls (default **2.0**, set with `@main(interval=...)`), until the plugin shuts down. An exception is
    logged and the loop continues. An `async def main` with `@main(interval=None)` is called once and runs for
    the life of the plugin (for event-driven watchers). If `main` is absent, the thread simply ends; the process
    stays up and variables change only through card and action events.
- Both hooks get a `PluginContext`, and the same functions are available at module level in `decker_plugin_sdk`
  (`register_variable`, `unregister_variable`, `signal_variable_updated`, `get_variable`, `has_variable`) so cards and
  actions can signal too.

## SDK surface (Python)

```python
@init                      # or async def
def setup(ctx: PluginContext) -> None: ...

@main(interval=2.0)        # or async def; interval=None for a run-once async watcher
def poll(ctx: PluginContext) -> None: ...

@variable("media_default_volume")            # exact name declared in the manifest
def default_volume() -> int | None: ...

@variable("media_{device}_volume")           # a family: the getter receives the placeholder values
def device_volume(device: str) -> int | None: ...

ctx.register_variable("media_speakers_volume")   # a concrete name inside a declared pattern
ctx.unregister_variable("media_speakers_volume") # the device went away
ctx.signal_variable_updated("media_default_volume")
```

`register_variable`/`unregister_variable` take only a name; its getter is the `@variable` function whose pattern
matches it. The SDK is the only Python-specific part: the wire protocol below is language-neutral.

## Protocol additions (additive; `hello.protocol` becomes 2, older plugins ignore the new events)

| Direction | Event | Payload |
|-----------|-------|---------|
| plugin to server | `register_variable` | `{"name": "media_speakers_volume"}` |
| plugin to server | `unregister_variable` | `{"name": "..."}` |
| plugin to server | `variable_updated` | `{"name": "..."}` |
| server to plugin | `get_variable` | `{"request": "<id>", "name": "..."}` |
| plugin to server | `variable_value` | `{"request": "<id>", "ok": true, "value": "…"\|null}` or `{"request", "ok": false, "error"}` |
| server to plugin | `variables_changed` | `{"set": {"name": "value", ...}, "removed": ["name", ...]}`; the full set is sent after `ready` |

Exact names declared in the manifest need no `register_variable`: the server asks for them at start.

## Goals

- Any plugin can export global variables other plugins' cards and key text can template on.
- Ownership is explicit and checked at load, with no first-set races and no prefix registry.
- The server never blocks a draw or an expansion on a plugin; a slow or dead plugin only affects its own variables,
  which read as unset instead of showing an old value.
- Plugins that export variables work with no card on screen.

## Non-goals

- A client picker or autocomplete for variables in text fields (a `variables_list` RPC and the CLI show what exists;
  UI comes later).
- Per-device or per-key plugin variables; reading page/profile variables from the SDK.
- Writing another plugin's variable; computed or derived variables; variable history.
- SDKs for languages other than Python (the protocol is ready for them).

## Anti-goals (a failure even if it works)

- The server calling a plugin on the draw path, or a plugin able to overwrite `page_name` or another plugin's value.
- Background plugins that quietly run without declaring anything: only a manifest `variables` entry makes a plugin
  always-on.

## Constraints

- Server and client stay decoupled; the server owns the cache; the client never reads plugin processes.
- Pure Python, no OS-specific code: all five platform tiers alike.
- Plugin docs (`docs/plugins/`: `protocol.md`, `package-and-manifest.md`, `sdk-quickstart.md`, `settings-schema.md` for
  `template`, `limits.md`), `CLAUDE.md` and `README.md` change with it. A manifest using `contributes.variables`
  needs `"decker": ">=<version that ships this>"` so older Decker refuses it.
- Limits (proposal, set in `limits.md`): 256 variables and patterns per plugin, 1024-character values, 64-character
  names.

## Approaches considered

- **A. Manifest-declared ownership, plugin-side getters, server cache (chosen).** Explicit, checked at load,
  language-neutral on the wire, no draw-path calls. Cost: always-on processes for variable-declaring plugins, and a
  new contribution type.
- **B. Plugins push values with `set_variable`, ownership by first set or by declared prefix.** Simple on the wire, but
  needs a prefix registry or has first-set races, and has no variable list before a value exists. Rejected.
- **C. The server polls getters on a schedule.** Puts the cadence and the plugin calls in the server and wastes calls
  when nothing changed. Rejected in favour of plugin-signalled refreshes.

## Design

### Server

- New contribution `variables` handled like `cards` and `actions` (`server/contributions.py`): the manifest parser
  (`plugin/manifest.py`) reads `contributes.variables` into `VariableSpec(name | pattern, description)`, validates
  names and placeholders, and the loader rejects collisions as described above.
- New `VariableStore` (`server/variables.py`): declared specs with owners, the value cache, `get`, `set_from_plugin`,
  `drop_plugin`, `matches(plugin_id, name)`, and a change callback. Thread-safe; never calls out while holding its lock.
- `PluginManager` handles the new events (`_route_message`), asks for values off-thread with a 5 s timeout (like
  `ActionRunner`), pushes `variables_changed` to running plugins, and redraws the keys that use a changed variable
  (a scan of live keys' templated text, next to `refresh_page_dependent`). Expansion merges the global variables into
  the per-device page variables (`page_vars.page_variables` stays pure; the merge happens where expansion is called).
- Supervisor: plugins that declare variables are acquired once at startup with a permanent reference, and asked for
  all values on `ready`; the plugin's cached values are dropped when its process stops.
- RPC: `variables_list` (declared variables, owner, current value) so the CLI and later a client picker can show
  them. Docs list the `variable_*` protocol events; `status` is unchanged.

### SDK (`decker_plugin_sdk`)

- Decorators `init`, `main`, `variable`; `PluginContext`; module-level helpers; a lifecycle thread per hook with an
  asyncio loop for async hooks; getters run in the existing worker pool and answer `get_variable`; a local variable
  copy fed by `variables_changed`. `shutdown` stops `main` cleanly.

## Left to the builder

- Exact module and class names, the placeholder-matching implementation, how `main` async cancellation is done,
  the precise limit values, and the docs wording.
