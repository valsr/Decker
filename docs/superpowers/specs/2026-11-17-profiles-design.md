# Profiles — design

Status: awaiting approval. Size: project (two repos: `decker`, `decker-plugins`).

## Intent

Today a device has one list of pages. A **profile** is a named, switchable set of pages on a device, so one deck can be a
"Work" deck, a "Streaming" deck and so on, each with its own pages and keys. The existing single page list is, in effect, a
single unnamed profile; this story names it and lets the user add more.

## Decisions taken with the user

- **Profiles are per device** (not global). Each device has its own profiles and its own active profile; the dropdown follows
  the selected device.
- Plugins can navigate between profiles and between pages of any profile of their own device.

## Goals

- **Data:** a device has one or more profiles. Each profile owns an ordered list of pages and its own default page. A new
  profile starts with one page, `Page 1`. Names default to `Profile N` (first unused N).
- **Switching:** activating a profile hides the current page's actions, makes the profile active and shows **its default
  page**. The active profile is persisted per device and restored at server start (the active *page* is not: a start shows the
  profile's default page, as today).
- **Client:** a profile dropdown sits left of the settings button, for the selected device. Entries: each profile (current one
  marked), `Add profile`, `Edit profile…`. Double-clicking a profile entry renames it in place (click away or Enter accepts,
  Esc cancels; blank names are rejected like pages). `Add profile` creates and activates `Profile N`.
- **Edit profile dialog:** name, icon (default: the Decker icon), **Delete** (confirmation warns that its pages and keys are
  deleted too), **Clone**. The last profile of a device cannot be deleted. Deleting the active profile first switches to a
  neighbour (next, else previous), like pages.
- **Clone:** copies the name (`<name> copy`, uniquified), icon, pages (names, order, default page) and every key assignment with
  its settings and appearance. Each copied key gets a fresh action instance (new context id) so no plugin state is shared; the
  clone does not become active.
- **Variables:** `{current_profile}` (profile name) and `{profile_id}` (1-based position in the dropdown; a raw id would be
  unreadable on a key). Same rules as the page variables: opt-in `template` fields, unknown names stay, live refresh when a
  profile is renamed, added, deleted or switched.
- **Plugin settings types** (alongside `page`): `profile` (dropdown of the key's device profiles; stored as the profile id,
  `""` = follow the current profile; delivered resolved as `{profile_id, name, index, icon}`). The `page` type gains an optional
  schema key `"profile_field": "<key of a profile field>"`: its dropdown lists the pages of the profile chosen in that field
  (the current profile when it is blank), and the resolved value gains `profile_id`. Both are action settings only.
- **Protocol / SDK:** plugin to server `switch_page` accepts a page of any profile of the device (`{"page_id"}` already
  identifies the profile; the server switches profile first when needed). New `switch_profile`:
  `{"to": "next"|"previous"|"first"|"last", "wrap": false}` or `{"profile_id": "<id>"}`. SDK: `ctx.switch_profile(to=..., wrap=...)`,
  `ctx.go_to_profile(profile_id)`. Interrogation uses the resolved `profile`/`page` setting values above (the same mechanism
  as pages today); there is no free-form query RPC for plugins.
- **`com.decker.pages`** gains optional *Profile* settings on **Go to page** (default: current profile).
- **`com.decker.profiles`** (new, in `decker-plugins`): **Next profile**, **Previous profile** (Wrap around, default off) and
  **Go to profile** (a `profile` setting). Each key shows the target profile's icon (Go to profile: the chosen profile's; Next /
  Previous: a caret icon) and, for Go to profile, the profile name as the fallback title.
- Decker becomes **0.5.0**; the plugins' `decker` floor and pin move with it.

## Non-goals

- Reordering profiles; per-profile device settings (brightness etc.); importing/exporting profiles; sharing a profile across
  devices (follows from per-device); profile hot-keys.
- A query RPC for plugins; profile-level permissions.

## Anti-goals

- Losing or rewriting existing keys on upgrade; breaking stored `page` settings.
- A profile switch that deadlocks the page controller / plugin manager (keep the lock order the page switch already uses).
- Clones that share plugin instance state with the original.

## Approaches considered

1. **`profiles` table + `profile_id` on pages (chosen).** Page ids are already unique per device, so key assignments, device
   state and `page` settings need no change; the profile is just a grouping above pages. Migration is additive.
2. Prefix page ids with the profile id. Rewrites every stored key row and every stored `page` setting. Rejected.
3. One database/file per profile. Makes clone, delete and cross-profile navigation hard. Rejected.

## Design

### decker (branch `feat/profiles`)

- **Model** (`common/model.py`): `ProfileInfo(profile_id, name, icon)` (`icon` is an icon ref string, `""` = Decker icon);
  `DeviceProfiles(device_id, profiles, active_profile_id)`; `DevicePages` gains `profile_id`.
- **Store** — `server/pages.py` grows a profile layer (or a sibling `server/profiles.py` the plan may split out):
  - tables `profiles(profile_id PK, device_id, name, icon, position)`, `profile_defaults(profile_id PK, page_id)` (replaces
    `page_defaults`), `active_profiles(device_id PK, profile_id)`; `pages` gains `profile_id`.
  - **Migration** (idempotent, in `create`): add the column if missing; per device that has pages, create profile
    `initial_profile_id(device_id)` = `"<device>-profile-1"` named `Profile 1`, point its pages at it, carry `page_defaults`
    into `profile_defaults`, mark it active. A device with nothing gets its first profile (and `Page 1`) on first access, as
    pages do today.
  - Page API takes/uses a profile: `list_pages(device_id, profile_id=None)` (None = active profile), `add_page(..., profile_id=None)`.
    `profile_of_page(device_id, page_id)`. Profile API: `list_profiles`, `add_profile`, `rename_profile`, `set_profile_icon`,
    `delete_profile` (refuses the last; also removes its pages and default row), `clone_profile` (copies pages and, through the
    key-assignment store, assignments with new ids), `active_profile_id`/`set_active_profile`.
- **Controller** (`server/page_controller.py`): `activate_profile(device_id, profile_id)` (hide current page, record active
  profile, show the profile's default page, notify); `activate(device_id, page_id)` switches the profile first when the page is
  in another one; `delete_profile`/`clone_profile`/`add_profile`/`rename_profile`/`set_profile_icon` notify; a
  `profiles_changed` event is pushed to clients next to `pages_changed`. `restore` shows the active profile's default page.
- **Variables** (`server/page_vars.py`): `page_variables` also returns `current_profile` and `profile_id`;
  `resolve_profile`, `resolve_page` gains `profile_id`; `resolve_switch_target` accepts any page of the device and a profile
  switch resolver mirrors it for `switch_profile`. `deliver_settings` resolves `profile` fields; `stored_page_ids` /
  `stored_profile_ids` keep echoed values stored as ids. `refresh_page_dependent` also fires on profile changes.
- **Plugin layer:** `settings_schema.py` (`FIELD_TYPES += "profile"`, `page` accepts `profile_field`, both rejected in
  `global_settings`, `profile_field` must name a `profile` field); `protocol.py`/`plugin/runtime` (`switch_profile` message, SDK
  `ctx.switch_profile`, `ctx.go_to_profile`); `plugins.py` `_on_switch_profile` (same re-entrancy and lock-order care as
  `_on_switch_page`).
- **RPC** (`server/service.py`): `profiles_list(device_id)`, `profile_add(device_id, name="")`, `profile_rename`,
  `profile_set_icon`, `profile_delete`, `profile_clone`, `profile_activate`; `pages_list(device_id, profile_id="")` (blank =
  active profile). Page RPCs keep working unchanged on the active profile. Key RPCs are untouched.
- **Client:** `ConnectionManager` parses `profiles_list`; a `ProfileSelector` widget (dropdown with in-place rename editing,
  current marker, Add / Edit entries) left of the settings button; a `ProfileEditDialog` (name, `IconEdit` for the icon with the
  Decker icon as the default, Delete with the warning, Clone); `PageTabBar`/dashboard reload on `profiles_changed` and show the
  active profile's pages; `SchemaForm` gets the `profile` dropdown and the profile-dependent `page` dropdown.
- **Icon:** a profile's icon is an icon ref (what the existing icon picker yields). The "Decker icon" default is a built-in
  ref the plan must define so plugins can show it. Plugins receive it in the resolved `profile` value and set it as their key
  icon; Decker renders it with the existing icon pipeline.
- **Docs:** `CLAUDE.md`, `docs/plugins/protocol.md`, `docs/plugins/package-and-manifest.md` (`profile` type, `profile_field`,
  variables, `switch_profile`).

### decker-plugins (branch `feat/profiles`, after the Decker change merges)

- `com.decker.pages`: **Go to page** gets an optional *Profile* field (`profile` type, blank = current) and its *Page*
  field declares `profile_field`; the press calls `ctx.go_to_page(page_id)`.
- `com.decker.profiles`: three actions as above; icons from the resolved profile; tests mirror `com.decker.pages`.
- Bump the Decker pin and the `decker` manifest floor to 0.5.

## Testing

TDD per task (RED then GREEN), as in the previous stories. Store: migration of a pre-profile database (pages, defaults, keys all
intact, one `Profile 1`), add/rename/delete/clone invariants (last profile refused, default page passes on, clone makes fresh
context ids and shares nothing). Controller: profile switch hides/shows the right actions, restores the active profile after a
restart, deleting the active profile falls back. Variables and delivery: new variables, `profile` and profile-aware `page`
resolution, stale ids. Protocol/SDK: `switch_profile`, `switch_page` across profiles. Client (offscreen Qt): selector
rename/accept/cancel/blank, edit dialog (rename, icon, delete confirm, clone), dropdown refresh on `profiles_changed`.
Gates as before: `poe format/mypy/pylint/test`, coverage >= 85%.

## Left to the builder

Exact table/column spelling beyond the above, whether the profile layer is its own module, how the Decker default icon ref is
spelled, the dropdown's visual details, and the order of tasks.
