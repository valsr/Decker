# Switching profiles by focused app

Decker can switch a device's active profile (and optionally page) when the focused window changes, for example to show
a terminal profile when a terminal has focus. The server does the detection, so it works with no client running. Design:
[app profile switching spec](superpowers/specs/2026-11-19-app-profile-switching-design.md); KWin findings:
[spike notes](superpowers/notes/2026-11-19-kwin-spike.md).

## Rules

Open the profile selector's **Edit profile…** entry. It opens the **Profiles and rules** dialog: the device's profiles on
one side and the selected profile's rules on the other, in an ordered list.

- Rules are per device and ordered; the **first matching rule wins**. Reorder them with move up/down.
- A rule has a name, an enabled flag, conditions, a target profile and an optional page. With no page, the target
  profile's default page is shown.
- A rule matches when **all** its conditions match (AND). There is no OR: add another rule instead.
- A condition is a field, an operator and a value. Fields: Window class, Window type, Title, Executable, Desktop file.
  Operators: `is`, `contains`, `does not contain`, `matches regex`. All comparisons are case-insensitive.
- On an empty field (for example no desktop file on X11 or Windows), `does not contain` is true and `contains` and
  `matches regex` are false; `is` compares the text with the value, so it matches only an empty value.
- `matches regex` is an unanchored search (anchor with `^` and `$`). A pattern that takes longer than 0.1 s counts as no
  match. An invalid pattern never matches, and both the editor and the server reject it on save. `contains`, `does not
  contain` and `matches regex` need a value.
- A rule with no conditions never matches.
- The **default rule** ("when no rule matches") has no conditions. It can only be enabled or disabled and retargeted
  (profile and page).
- The default rule starts disabled, targeting profile 0.
- Deleting a profile removes the rules that targeted it and resets a default rule that targeted it (disabled, back to
  profile 0). Deleting a page clears the page on rules (and the default rule) that named it.

## Behaviour

- The server detects focus itself; no client has to run. When the server starts, or a device connects, the current
  window is evaluated.
- A manual profile switch sticks until focus moves to a window whose target differs from the previous target.
- Editing rules never switches the deck. Edits apply at the next focus change.
- A window that matches no rule, with the default rule disabled, changes nothing. It also resets the server's memory of the previous
  target, so returning to the earlier window re-applies its profile, overriding a manual switch.
- A title change inside an already-focused window is not re-evaluated until focus changes.

## Window Spy

Window Spy (in the dialog) shows a window's class, type, title, executable and desktop file so you can write rules.

- **Pick window**: click the window you want to inspect (where the backend supports picking).
- **Capture in 3 s** and **Follow**: where picking is unsupported, capture the focused window after a 3 second countdown,
  or follow focus live.
- **Create rule from this window** pre-fills a new rule from the shown attributes.

## Requirements and privacy

The server must run inside the desktop session (`WAYLAND_DISPLAY` and `DBUS_SESSION_BUS_ADDRESS` on Wayland, `DISPLAY`
on X11). Started from a system service or an SSH session without them, detection reports **unavailable** and rules are
inactive.

Window titles can reveal private content, so the server sends them only to local (loopback) clients; remote clients get
an empty title.

## Platform notes and known limits

| Session | Backend | Notes |
|---|---|---|
| Linux Plasma 6 (Wayland) | `kwin` | Loads a KWin script named `decker-window-watcher` into the session and unloads it on stop. Plasma 5 reports unavailable. |
| Linux X11 | `x11` | No desktop file. |
| Windows | `windows` | No window type and no desktop file. |
| GNOME / other Wayland, macOS | none | Report unsupported for now. |

- On native Wayland (KWin) a dialog reports window type `normal`; only X11/XWayland windows report `dialog`.
- **Known limitation:** rule edits are whole-rule updates. If two clients edit different fields of the same rule at the same
  moment, the last save wins for the fields it holds (no field-level merge yet).

## RPC and events

| RPC | Purpose |
|---|---|
| `app_rules_list(device_id)` | The device's rules in order plus its default rule |
| `app_rule_add(device_id, rule)` | Append a rule; returns the stored rule, or none if invalid |
| `app_rule_update(device_id, rule)` | Replace a rule |
| `app_rule_delete(device_id, rule_id)` | Delete a rule |
| `app_rule_move(device_id, rule_id, position)` | Change a rule's priority |
| `app_default_rule_set(device_id, enabled, profile_id, page_id)` | Set the default rule |
| `window_detection_status()` | Backend state (active, unavailable, unsupported), reason and last window |
| `window_pick()` | Start a pick; the result arrives as `window_picked` for the calling client only |

`app_rule_update`, `app_rule_delete`, `app_rule_move`, `app_default_rule_set` and `window_pick` return a bool, which
the RPC layer replies as the JSON text `"true"` or `"false"`.

Events: `app_rules_changed`, `window_detection_changed`, `window_focused`, `window_picked`. Window payloads carry
`window_class`, `window_type`, `title`, `executable`, `desktop_file` and `pid`.

## Adding a backend

A backend lives in `src/decker/server/windows/` and implements the `WindowBackend` protocol (`backend.py`): `name`,
`supports_pick`, `available()`, `start(on_change, on_failure=None)`, `stop()` and `pick(on_result)`. Register it in
`select.py` (`select_backend` / `select_backend_name`). Contract:

- `stop()` must never raise.
- If the event source dies after `start`, call `on_failure(exc)` once, from the backend's thread.
- `pick` reports exactly once, with the window or `None`.
- Fields a backend cannot supply are empty strings.

Update the platform table in the README and [platform support](platform-support.md) in the same change.
