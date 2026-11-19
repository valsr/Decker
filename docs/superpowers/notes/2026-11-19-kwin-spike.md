# KWin spike: focused-window detection and window picking

Date 2026-11-19. KWin 6.7.5, Plasma 6 Wayland (Manjaro). Spike outcome: both mechanisms work; no blocker.

## Focus detection

- Load: `org.kde.KWin /Scripting org.kde.kwin.Scripting loadScript(path: s, name: s) -> i` (id, `-1` if the name is
  already loaded), then `start() -> ()`. `start` runs every script that is loaded but not yet running and the script's
  top-level code executes at once (so the "initial" report fires on `start`). Per-script objects live at
  `/Scripting/Script<id>` (`run`, `stop`) but were not needed.
- Unload: `unloadScript(name: s) -> b` (true if it was loaded, false otherwise; safe to call blindly).
- `isScriptLoaded(name: s) -> b` exists.
- Script: `src/decker/server/windows/kwin_script.js`, name `decker-window-watcher`. It uses `workspace.windowActivated`
  and calls `callDBus("org.decker.WindowWatcher", "/WindowWatcher", "org.decker.WindowWatcher", "Focused", json)`.
  Method `Focused(s)` carries one JSON string with keys:

| key | type | notes |
|---|---|---|
| `resourceClass` | string | Wayland app id (`org.kde.dolphin`), X11 WM_CLASS class (`Xmessage`); for a Qt app on XWayland it was the script name (`qtdlg.py`) |
| `windowType` | string | derived in the script from the boolean flags: `normal`, `dialog`, `utility`, `splash`, `dock`, ... |
| `caption` | string | window title |
| `pid` | int | |
| `desktopFileName` | string | `""` for XWayland apps without one (xmessage) |

- Callback is a plain method call (`sig s`); the receiver must `RequestName("org.decker.WindowWatcher")` first and
  reply to the call (we sent an empty method return; the script ignores replies). Receiver used here: `jeepney` 0.9.0
  (blocking connection, `message_bus.RequestName`, then `receive()` loop, `new_method_return`).
- Fixtures: `tests/server/windows/fixtures/kwin_focus.json` (native Wayland Dolphin, XWayland xmessage, XWayland Qt dialog).

### Contradicts / refines the spec

- **`window.windowType` is an int and is `0` for Wayland dialogs.** On native Wayland a transient `QDialog` still reports
  `windowType 0`, `dialog false`, `normalWindow true`; only `transient true`. Only X11/XWayland windows with
  `_NET_WM_WINDOW_TYPE_DIALOG` report `windowType 5`, `dialog true`. So the script maps booleans to a string and a
  native Wayland dialog shows as `normal`. Rules cannot tell a Wayland dialog from a normal window with this script;
  a `transient` flag could be added to the payload later if wanted (not done: not in the contract).
- Qt `Tool` windows did not take focus, so `utility` was not observed.
- `workspace.windowActivated` fires with `null` when focus goes to no window; the script ignores it, so the last window
  stays current.
- The script also reports once at load (`report(workspace.activeWindow)`), which is the initial-state report.
- `callDBus` with no receiver on the bus is silent; the script keeps running (still loaded after the receiver died).

## Stale-script handling

- After the scratch receiver was killed the script stayed loaded (`isScriptLoaded` true).
- `loadScript` of an already-loaded name returns `-1` (no second instance). So the backend should always
  `unloadScript(name)` first (returns false when absent, harmless), then `loadScript`, then `start`.
- After unload + load + start with a fresh receiver, one focus change produced exactly one `Focused` call.
- A second receiver claiming the same bus name queues (`RequestName` reply 2) and receives nothing while the first lives,
  so a second server instance is detectable (reply != 1).

## queryWindowInfo

- `org.kde.KWin /KWin org.kde.KWin queryWindowInfo() -> a{sv}` exists. The call blocks (reply delayed) while the picker is
  shown; the user clicks a window. Use a long D-Bus timeout (we used 15-60 s).
- Cancel with Escape: error `org.kde.KWin.Error.UserCancel`, message `User cancelled the query`.
- Already open: a second call returns **immediately** with the same error name `org.kde.KWin.Error.UserCancel`
  (no distinct "busy" error). The first call stayed pending until its own timeout and a later Escape did not answer it,
  so after this the picker state is unclear: do not issue concurrent picks.
- Bus timeout with no click: the client gets a plain "timed out"; the picker is no longer active afterwards (a new
  query worked).
- Clicking worked (via ydotool for the spike): `a{sv}` return, keys (variant type): `activities` as, `caption` s,
  `clientMachine` s, `desktopFile` s, `desktops` as, `excludeFromCapture` b, `fullscreen` b, `hasTransientParent` b,
  `height` d, `keepAbove` b, `keepBelow` b, `layer` i, `localhost` b, `maximizeHorizontal` i, `maximizeVertical` i,
  `minimized` b, `noBorder` b, `pid` i, `resourceClass` s, `resourceName` s, `role` s, `skipPager` b, `skipSwitcher` b,
  `skipTaskbar` b, `type` i, `uuid` s, `width` d, `x` d, `y` d. Fixture: `kwin_pick.json` (anonymised).
- Mapping to `WindowInfo`: `window_class` = `resourceClass`; `window_title` = `caption`; `pid` = `pid` (executable via
  psutil); `desktop_file` = `desktopFile` (note: no `Name` suffix, differs from the script's `desktopFileName`);
  `window_type` from `type` using the NET window type enum: 0 normal, 1 desktop, 2 dock, 3 toolbar, 4 menu, 5 dialog,
  8 utility, 9 splash (others by the KDE `NET::WindowType` values). `hasTransientParent` is true for transient
  Wayland dialogs and could map to `dialog` for picks (but then picks and focus events would be inconsistent unless
  the focus script is changed too). Only `type 0` (Konsole) was observed in a pick; type 5 was only observed via the
  script's `windowType`.
- A pick on this machine was synthesized with `ydotool` (the user did not click within 60 s on the first attempt).

## Misc

- `jeepney` installs into a scratch venv fine (0.9.0). KWin tools: `busctl`, `qdbus6` exist.
