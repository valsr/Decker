# Switch profiles by focused app — design

Status: awaiting approval. Size: project (one repo: `decker`).

## Intent

Like the Elgato software, a device should change profile on its own when a given application comes into focus, so one deck
can be a "Browser" deck while the browser is focused and a "Streaming" deck while OBS is. The user thinks of the Decker
server as the product and the client as a UI frontend, so detection must work with **no client running**.

## Decisions taken with the user

- The **server** detects the focused window (not the client).
- **In-process backends** behind one interface (approach 1 below). GNOME comes later.
- Rules are **one flat, ordered list per device**: "if this window matches, activate this profile (and optionally this
  page)". **First match wins.**
- A rule can match window class, window type, window title and other window attributes.
- A page is optional; with none the target profile's default page is shown.
- One **default rule** picks a profile/page when no other rule matches. It can only be **enabled or disabled**
  (its target is editable, it cannot be deleted, reordered or given match conditions).
- The per-profile Edit dialog is replaced by **one dialog for all profiles and the rule list**.

## Goals

- **Detection:** the server learns the focused window's attributes whenever focus changes, on Plasma/Wayland, X11 and
  Windows, with no client connected.
- **Rules:** per device, ordered, each with match conditions and a target profile and optional page. Evaluated on every
  focus change; the first enabled rule that matches switches the device (via `PageController`).
- **Default rule:** per device, enabled or not, with a target profile (initially profile `0`) and optional page.
- **Edit dialog:** one "Profiles and rules" dialog: profile list (add, rename, icon, delete, clone: today's
  `ProfileEditDialog` features) plus the rule list (add, edit, delete, reorder, enable/disable), the default rule pinned at the
  end, and a status line showing whether detection is working and the last seen window (class, type, title) so the user can
  write rules from real values.
- **Status:** the server reports detection state (`active`, `unavailable: <reason>`, `unsupported`).

## Non-goals

- GNOME (needs a shell extension), macOS and Sway/other compositors in v1: they report `unsupported`. The backend
  interface must make adding them a new module only.
- Per-device detection differences (one focused window drives all devices; each device has its own rules).
- Matching on window geometry, workspace/virtual desktop, or screen.
- Clients detecting windows; a client-side fallback.
- Rule import/export; per-rule key brightness or other device settings.

## Anti-goals

- A server crash or hang because of a detector. Backends run in threads, never block the page controller, and a backend that
  raises is logged, marked `unavailable`, and retried with backoff.
- A profile switch loop or flicker (focus bouncing between windows should not thrash the deck; see Debounce).
- Silently clobbering a manual switch (see Manual switches).
- Reading window titles for any purpose other than matching and the status display; titles are not logged above debug level.
- Any dependency on a running client, or the server calling into Qt.

## Constraints

- **Platform:** Plasma/Wayland (tier 1), X11 (tier 3, also covers many GNOME/X sessions), Windows (tier 4) in v1.
  Update the README platform table and `docs/platform-support.md` in the same change. GNOME and macOS rows say "not yet".
- The server must run in the desktop session to see it (Wayland needs `WAYLAND_DISPLAY`/`DBUS_SESSION_BUS_ADDRESS`; X11 needs
  `DISPLAY`). Without them detection reports `unavailable: no desktop session`; rules stay stored and inactive.
- Rules use the same lock order as page switching (`PageController`); detection calls `activate_profile`/`activate`, never
  holds a lock while calling a backend.
- RPCs that change rules or profiles follow the existing loopback gating rules where `plugin_install` does not apply; rule
  changes are ordinary device settings like page edits (no gating).

## Approaches considered

1. **In-process thread backends behind one interface (chosen).** Plasma: a KWin script (loaded over D-Bus) reports
   `activeWindow` changes by calling a method on a D-Bus service the server registers. X11: listen for
   `_NET_ACTIVE_WINDOW` changes. Windows: poll `GetForegroundWindow` (~300 ms). Least machinery, fits the headless server.
   Trade-off: a native crash in a backend library takes the server down, which the monitor would restart.
2. **Out-of-process detector child per session** (JSON lines, supervised like plugins). Contains crashes and hangs and keeps
   native event loops out of the server, at the cost of a new protocol and supervision. Rejected for v1; the interface keeps
   this open.
3. **Shell out to `kdotool`/`xdotool`/`swaymsg`.** Cheapest, but adds system dependencies and polling. Rejected as the main path.

## Design

### Data model (`common/model.py`)

- `WindowInfo(window_class: str, window_type: str, title: str, executable: str, desktop_file: str, pid: int = 0)`; every string field may be `""` (`pid` is for the Window Spy only, never matched).
  `window_class` is the app id on Wayland (e.g. `org.kde.dolphin`) and `WM_CLASS` on X11; `window_type` is the compositor's
  type (`normal`, `dialog`, `utility`, ...); `executable` is the process basename via `psutil`; `desktop_file` is
  Plasma-only.
- `MatchCondition(field: str, op: str, value: str)`, `field` one of the `WindowInfo` fields, `op` one of
  `equals`, `contains`, `not_contains`, `regex` (shown as "is", "contains", "does not contain", "matches regex"). All are
  case-insensitive; `regex` is `re.search`, invalid patterns are rejected when saved. `not_contains` is true when the value
  does not occur in the field, including when the field is empty or the backend does not supply it (my call: "title does
  not contain X" should not fail just because a platform has no such field); the other three are false on an empty field.
  The rule editor warns when a rule uses a field the active backend does not supply.
- `AppRule(rule_id: str, name: str, enabled: bool, conditions: list[MatchCondition], profile_id: int, page_id: str)`: all
  conditions must match (AND, across any mix of fields; there is no OR: use a second rule); `page_id == ""` means the profile's default page. A rule with no conditions never matches.
- `DefaultRule(enabled: bool, profile_id: int, page_id: str)`.
- `DeviceRules(device_id, rules: list[AppRule], default_rule: DefaultRule)`.

### Store (`server/app_rules.py`, new, in `decker.db`)

- `app_rules(device_id, rule_id TEXT, position INTEGER, name, enabled, conditions_json, profile_id, page_id, PRIMARY KEY
  (device_id, rule_id))`; `default_rules(device_id PRIMARY KEY, enabled, profile_id, page_id)`. A device with no row has a
  disabled default rule targeting profile `0`: a fresh install keeps today's behaviour.
- Deleting a profile removes rules targeting it (and disables the default rule, resetting its target to the first profile);
  deleting a page clears `page_id` on rules that named it. Hook this where the controller deletes profiles/pages.
- Validate on write: known profile, page belongs to that profile, valid conditions.

### Detection (`server/windows/`, new package)

- `WindowBackend` protocol: `name`, `available() -> BackendStatus`, `start(on_change: Callable[[WindowInfo], None])`,
  `stop()`, `supports_pick: bool` and `pick(on_result: Callable[[WindowInfo | None], None])` (the user clicks a window;
  `None` = cancelled). Pick per backend: KWin calls `org.kde.KWin /KWin queryWindowInfo` (the same D-Bus call KDE's rules
  dialog uses; KWin shows the picker and returns the window's properties); X11 grabs the pointer with a crosshair cursor and
  takes the clicked top-level window (as `xprop`/`xwininfo` do); Windows installs a one-shot low-level mouse hook and takes
  `WindowFromPoint` of the click, walking up to the top-level window. Modules: `kwin.py` (Plasma/Wayland), `x11.py`, `windows.py`, `unsupported.py`. `select_backend(env, platform)`
  picks by platform and session (`XDG_SESSION_TYPE`, `XDG_CURRENT_DESKTOP`, `WAYLAND_DISPLAY`, `DISPLAY`).
- `WindowWatcher` (`server/window_watcher.py`) owns the backend, keeps the last `WindowInfo`, debounces (~150 ms: only the
  last change in the window counts, identical consecutive `WindowInfo` are dropped), and calls the rule engine from its own
  thread. It exposes `status()` for the RPC and always pushes `window_detection_changed` / `window_focused` events (they
  are small).
- Library choices for D-Bus and X11 (a pure-Python D-Bus client such as `jeepney`, `python-xlib`) and Windows `ctypes` are the
  builder's call; add them as normal dependencies (Linux/Windows-only via environment markers where needed).
- The KWin script is loaded with `org.kde.KWin /Scripting loadScript`, started, and unloaded on stop; the server registers
  one D-Bus name and path for the callback. If KWin scripting is unavailable the backend reports `unavailable: <reason>`.

### Rule engine (`server/app_rule_engine.py`, new)

- `on_focus(window: WindowInfo)`: for each device (`device_manager` devices), `target = first enabled rule that matches, else
  the default rule if enabled, else None`. If `target` is not None and it differs from where the device already is
  (active profile and, when `page_id` is set, the active page), call `PageController.activate_profile` /
  `activate(page_id)`; if the profile is already active and `page_id == ""` do nothing.
- **Manual switches (my call, user did not object):** a manual switch (key, dropdown, plugin `switch_*`) sticks until the next
  *focus change to a window whose evaluated target differs from the previous target*. Implementation: remember the last
  target per device; apply only when the new target differs from it. Moving focus between two windows that match the same
  rule therefore never overrides a manual choice. Unfocusing to a window with no matching rule and a disabled default rule
  changes nothing.
- Devices connected later get the current window evaluated against their rules when they appear.
- Runs off the watcher thread; the controller call is the same one RPCs use.

### RPC (`server/service.py`) and CLI

`app_rules_list(device_id)`, `app_rule_add(device_id, rule)` / `app_rule_update(device_id, rule_id, rule)` /
`app_rule_delete` / `app_rule_move(device_id, rule_id, position)`, `app_default_rule_set(device_id, enabled, profile_id,
page_id)`, `window_detection_status()` (state, backend name, last window, `supports_pick`), `window_pick()` (starts a
pick, returns at once; one pick at a time, a second call while one is open is refused; a pick times out after 60 s). The
result arrives as a `window_picked` event (`WindowInfo` or empty on cancel/timeout) to the client that started it, with the
same title rule as `window_focused`. Events: `app_rules_changed`,
`window_detection_changed`, `window_focused`. The CLI picks these up through `commands()`; no CLI code is needed.

### Client

- `ProfileEditDialog` becomes `ProfilesDialog` ("Profiles and rules"): left, profile list with the existing add/rename/icon/delete/clone
  controls; right, the rule list (drag or buttons to reorder, enable checkbox, name, "-> Profile / Page" summary) and an
  editor for the selected rule (name, a condition list of field/operator/value rows, profile dropdown, page dropdown
  limited to that profile with a "profile default" entry). The default rule is the last, fixed row (enable checkbox, target).
  A status strip shows the detection state and a **Window Spy** button (see below).
- **Window Spy** (`widgets/window_spy.py`, a non-modal dialog opened from the rules dialog and the rule editor): shows every
  property the active backend supplies for a window (class, type, title, executable, pid, desktop file; fields the backend
  cannot supply are greyed as "not available on this system"), a copy button per value, and the detection state. The primary
  action is **Pick window**, which works like "Detect Window Properties" in KDE's window rules: the pointer becomes a picker
  and the next click selects a window, whose properties are then shown. The pick happens on the server's desktop through the
  backend (see Detection). Where a backend cannot pick (`supports_pick` false), the button is replaced by **Capture in 3 s**
  (countdown, then the next focused window is shown, so the user can switch to the target app), plus a live **Follow** mode
  (ignores Decker's own windows, so it shows the last other window focused). **Create rule from this window** opens a new
  rule with conditions prefilled from the shown values (class `equals`, plus type if not `normal`; title and others left for
  the user to add). Escape or a click on nothing cancels a pick. The Spy is available whenever detection is `active`;
  otherwise it shows the reason.
- `ProfileSelector`'s "Edit profile..." entry opens this dialog on the current profile. `ConnectionManager` parses the new
  RPCs and events; the dialog refreshes on `app_rules_changed`/`profiles_changed`.
- Offscreen Qt tests as for the existing dialogs.

### Docs

`README.md` platform table and `docs/platform-support.md` (new feature row and footnote), `CLAUDE.md` (server architecture
paragraph: window detection, rules), and a short `docs/app-profile-switching.md` for users and for adding a backend.

## Testing

TDD per task. Pure logic with no desktop: condition matching (each op, case, invalid regex, empty rule never matches), first-match
order, default-rule fallback, "target unchanged = no switch", the manual-switch rule, debounce and duplicate suppression
(fake clock). Store: round trip, migration-free first use, reordering, cascade on profile and page delete. Engine against a
real `PageController`/page store with a fake backend that emits `WindowInfo`s (integration style, no mocks of the store).
Backends: parse/translate tests on recorded samples (KWin callback payload, X11 property values, Windows struct results), and
`select_backend` environment cases; real-desktop smoke tests skipped when no session. RPC and client tests through the
in-process service and offscreen Qt. Gates: `poe format/mypy/pylint/test`, coverage >= 85%, CI on Linux/Windows/macOS runners
where the backend modules import cleanly.

## Details settled after review (my calls; flagged for the user to check)

- **Engine state** is per device and in memory: the last applied target, the last debounce window. Initial value is "none".
  When the server starts, or a device connects, the engine evaluates the *current* window and applies its target (like the
  Elgato app: the deck follows the focused app from the start, which can override the profile restored from the last run).
  A server restart (including exit 75) is the same as a start. The remembered target is reset to "none" for that device by
  a start/connect only, not by rule edits.
- **Rule edits do not switch the deck.** They take effect at the next focus change, so editing a rule never makes the deck
  jump under the user. Deleting a profile or page still reconciles stored rules as above. A user returning to window A after
  a manual switch while B had the same target as A is "no change" (target equals the remembered one).
- **Application edge cases:** if a rule's page no longer exists when it fires, show the profile's default page. "Profile's
  default page" is the existing `profile_defaults` page the store already keeps. A profile always has at least one page.
- **Plasma backend:** target Plasma 6 / KWin 6 (`workspace.activeWindow`, `windowActivated`); Plasma 5 reports
  `unavailable: KWin 6 required`. The KWin script reports `resourceClass`, `windowType`, `caption` and `pid`; `executable` is
  the pid's basename through `psutil`. At start the backend unloads any script already loaded under its fixed name (stale
  after a crash) before loading a new one; if the D-Bus callback name cannot be registered it reports `unavailable`. The first
  plan task is a short spike that proves this on a real Plasma session before the rest is built on it.
- **Windows `window_type`** is `""` in v1 (no clean equivalent); X11 maps `_NET_WM_WINDOW_TYPE`; `desktop_file` is Plasma-only.
  The rule editor marks fields the active backend does not supply as "not available on this system".
- **RPC shapes:** rules cross RPyC as plain dicts (the existing model dataclasses already do this); the server generates
  `rule_id` (uuid hex) and `app_rule_add` returns the stored rule.
- **Privacy of titles:** `window_detection_status` and `window_focused` carry the title only to loopback clients; remote
  clients get class/type/executable with an empty title. Events go to all clients; they are small.
- **Dialog:** non-modal like the Settings dialog; every edit is saved immediately through its RPC (no OK/Apply, no
  cross-edit transaction) and the dialog refreshes on `app_rules_changed`/`profiles_changed`, so another client's change just
  shows up.
- **Dependencies:** new runtime dependencies are acceptable (`jeepney` for D-Bus, `python-xlib` for X11, both
  Linux-only through markers; Windows uses `ctypes`). Backend modules import their library lazily so the package still
  imports on the other platforms.
- **Window Spy and Decker's own windows:** the client tells the server nothing about itself; the Spy ignores a focus event
  whose `pid` equals the client's own pid (sent by the Spy when it subscribes) in Follow mode. Capture mode counts down in
  the client and takes the first `window_focused` event after the countdown that is not the client's own window. The
  `WindowInfo` therefore carries `pid: int` (0 when unknown). Rule matching ignores `pid`.
- **Per-device:** the debounce window and remembered target are per device; a device with no rules and a disabled default
  rule is never touched.

- **Picking and the spike:** the Plasma spike must also prove `queryWindowInfo` (method name, returned keys and how they map
  to `WindowInfo`) on a real session, since the pick design leans on it. A pick uses the same title-privacy rule: the picker
  runs for the loopback client; a remote client's pick returns an empty title. A pick does not trigger rule evaluation.

## Left to the builder

Library choices for D-Bus/X11/Windows access, exact table and column spelling beyond the above, the debounce constant and polling
interval, the dialog's layout details and widget classes, how rule ids are generated, and the order of tasks.
