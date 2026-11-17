# Decker plugin repositories — design

Status: approved in conversation 2026-11-16. Builds on plugin format v1
(`2026-11-15-decker-plugin-format-design.md`, PRs #18/#19).

## Intent

Plugins should be found, installed and kept up to date from inside Decker, not by
hand-copying `.deckerplugin` files. Decker's own plugins move out of the application
into a separate repository, `decker-plugins`, that builds, tests and publishes them on
every merge. Anyone can host a repository the same way and users can add it.

## Goals

1. Users add and remove plugin repositories (an index URL each) in the Plugins tab.
2. A "Get More Plugins…" view (like KDE Plasma's) to search, browse and install plugins
   from all repositories, showing plugin information, installed vs available version
   and what the plugin contributes. No ratings.
3. Update: download, stop the running plugin, reinstall, start — reusing the v1
   installer's swap and rollback.
4. Clients get a toast when updates are available.
5. A new GitHub repository `valsr/decker-plugins` whose CI tests and packages plugins
   on every PR and, on merge to main, publishes new versions and a JSON index.
6. Counter moves to `decker-plugins` and is removed from the Decker tree.

## Non-goals

- Ratings, reviews, download counts, screenshots carousels.
- Package signing (see Trust).
- Automatic updates without the user's action.
- Downgrade UI (the index keeps old versions so it can be added later).
- Writing the other plugins in `_plugins.user.md` — this work only moves Counter, but
  the repository layout and CI must scale to many plugins.

## Anti-goals

- A published version must never change after release (same id + version ⇒ same bytes).
- A broken or unreachable repository must never break the Plugins tab, the server or
  installs from other repositories.
- A user who upgrades Decker must not silently lose their Counter keys.

## Trust

A repository can ship any code that runs as the user. Adding a repository shows a
warning stating exactly that; install keeps its existing trust notice. Adding/removing
repositories, installing and updating are restricted to loopback clients exactly like
`plugin_install` (`server.allow_remote_plugin_install`). Each download is verified
against the index's `sha256` and `size`; this detects corruption or a swapped file, not
a malicious index. No signing in this version.

## Approaches considered (hosting)

- **A. GitHub Releases for packages + `index.json` on GitHub Pages — chosen.** Free,
  stable download URLs, every old version kept; any static host can serve a third-party
  repository the same way, only the index URL matters.
- B. Everything on Pages: simpler CI but the site grows per version, so latest-only.
- C. Commit built packages: binaries accumulate in git history.

The server, not the client, downloads (works for remote clients; one update check
notifies every client).

## `decker-plugins` repository

- Layout: `plugins/<plugin-id>/` (the plugin source as accepted by
  `poe cli plugin pack`), each with its own `tests/`; repository-level tooling in
  `tools/` (pack, index build, version check) in Python, depending on Decker's
  packaging code by installing Decker from git at a pinned ref.
- PR CI: for every plugin, run its tests and build its package (artifact upload).
  Version check: if a plugin's files differ from main but its manifest `version`
  is not greater than the latest published version, fail.
- Main CI: for every plugin whose manifest version has no release yet, create a GitHub
  Release tagged `<plugin-id>-v<version>` with the `.deckerplugin` attached; then
  rebuild and deploy the Pages site: `index.json` plus `icons/<plugin-id>.png`.
  Existing releases are never modified.
- Index format (`format: 1`):

```json
{
  "format": 1,
  "name": "Decker Plugins",
  "generated": "2026-11-16T19:00:00Z",
  "plugins": [
    {
      "id": "com.decker.counter",
      "name": "Counter",
      "author": "Decker",
      "description": "Counts key presses.",
      "category": "Utilities",
      "homepage": "https://github.com/valsr/decker-plugins",
      "icon": "icons/com.decker.counter.png",
      "versions": [
        {
          "version": "1.0.0",
          "decker": ">=0.2",
          "url": "https://github.com/valsr/decker-plugins/releases/download/com.decker.counter-v1.0.0/com.decker.counter-1.0.0.deckerplugin",
          "size": 12345,
          "sha256": "…",
          "released": "2026-11-16T19:00:00Z",
          "contributes": { "actions": ["Counter"], "icon_packs": ["Counter icons"] }
        }
      ]
    }
  ]
}
```

  Relative `icon`/`url` resolve against the index URL. `versions` is newest first.

## Decker server

- Config: `plugins.repositories` — list of index URLs, default
  `["https://valsr.github.io/decker-plugins/index.json"]`. Removing the default is allowed.
- A repository client (stdlib `urllib`, no new dependency) fetches indexes with a
  timeout and size cap, validates them strictly (unknown `format` ⇒ repository marked
  in error, others unaffected), and caches the last good copy plus its icons under
  `~/.decker/repositories/`. Plugin ids and versions are validated with the v1 manifest
  rules; entries that fail are skipped, not fatal.
- Catalog: merges all repositories. If two repositories offer the same plugin id, the
  first in the configured list wins and the duplicate is shown as such.
- Install/update from a repository: the server downloads the chosen version (size cap
  = v1 package cap), verifies size and sha256, then hands the bytes to the existing
  `PluginInstaller` (same job, progress, finished events, busy rule, rollback). The
  manifest inside must match the index's id and version, else the install fails.
- Compatibility: a version whose `decker` specifier excludes the running Decker is
  listed but not installable; "latest compatible" drives updates.
- Update checks (user decision): the repository lists are refreshed on a schedule set
  by `plugins.update_check` — `weekly` (default), `daily`, `monthly` or `manual` — plus
  on demand. The time of the last successful check is persisted under
  `~/.decker/repositories/`, so the schedule survives restarts: on start and then
  periodically the server checks only when the interval has elapsed since the last
  check (`manual` never checks on its own). At start, updates are first computed from
  the cached indexes without any network access. When the set of plugins with a newer
  compatible version changes, push a `plugin_updates_available` event to all clients.
  Updating is always the user's action. Changing the schedule is loopback-gated like
  the other repository mutations.
- Missing plugins: when key assignments reference a plugin that is not installed but a
  repository offers it, the update check reports it as "missing" so the client can
  offer to install it (this is how upgraded users get Counter back).
- RPCs (names are the builder's to finalize): list/add/remove/refresh repositories,
  catalog, install from repository (id + version), check updates / list updates.
  Mutating ones are loopback-gated.

## Decker client

- Plugins tab gains a Repositories section: list (URL, name, status/last error, plugin
  count, last checked), Add (with the trust warning), Remove; an "Update frequency"
  selector (Daily / Weekly / Monthly / Manual) and a "Check for updates" button that
  refreshes every repository now and recomputes available updates (user decision).
- "Get More Plugins…" button opens a dialog: search box, category filter, refresh;
  rows with icon, name, short description, installed → available version, and an
  Install / Update / Installed button; a details pane with full description, author,
  homepage, contributions, size, repository, required Decker version. All RPCs off the
  UI thread; progress comes from the existing install events.
- Toast on `plugin_updates_available`: "N plugin updates available" with an
  "Update all" action (runs updates one after another, since the server allows one job
  at a time); missing plugins get "Install missing plugins". The Plugins tab badges
  plugins with updates.

```
┌ Get More Plugins ──────────────────────────────────────────┐
│ [search…………………]  [All categories ▾]  [⟳ Refresh]           │
│ ▣ Counter      Counts key presses   1.0.0 → 1.1.0  [Update]   │
│ ▣ Clock        World clocks         —     1.0.0    [Install]  │
│ ▣ Media Keys   Play/pause, next…    1.2.0          [Installed]│
└────────────────────────────────────────────────────────────┘
```

## Moving Counter

- Counter's source and tests move to `decker-plugins/plugins/com.decker.counter/`.
- Decker removes `src/decker/bundled_plugins/` and the bundled-plugin mechanism (the
  `bundled` flag, launching bundled plugins on Decker's own interpreter). Tests that
  need a plugin use fixtures built in the test tree.
- The key-assignment appearance migration for Counter stays (it is data-only).

## Calls made after the builder check (executor's, not the user's)

1. **Counter transition.** Key assignments for an uninstalled plugin already survive
   (the key store never prunes by plugin). The Decker change that removes
   `bundled_plugins/` merges only after Counter's first `decker-plugins` release is live
   (a manual gate). Offline or with the repository unreachable, Counter keys keep their
   assignment and show the existing "plugin unavailable" key state; the missing-plugin
   offer appears once a repository answers.
2. **Version compatibility** uses exactly the installer's rule
   (`SpecifierSet.contains(..., prereleases=True)`); one shared `decker_version()`
   helper replaces the three duplicates in `server.py`, `plugins.py`, `environment.py`.
3. **Update = existing installer.** `_swap_in` already deactivates and reactivates live
   keys and keeps plugin settings; no new stop/start logic.
4. **Download runs inside the install job.** A repository install starts a job that
   downloads (with progress events), verifies size + sha256, then runs the normal
   install with an expected `(id, version)` that the manifest must match. All failures
   arrive as `plugin_install_finished` with `ok: false`, like any other install.
5. **Update semantics.** An installed plugin whose id appears in a repository is
   updatable when that repository's latest compatible version is greater, regardless of
   how it was installed; a local version equal or newer is up to date. When several
   repositories offer an id, only the first in the configured list is used.
6. **`decker-plugins` tooling** installs Decker from git at a pinned tag/commit and uses
   `decker.plugin.package`/`decker.cli.plugin_scaffold.pack`. Until the user approves
   creating the GitHub repository, it is built as a local git tree at
   `/work/decker/decker-plugins` with no remote.
7. **Toasts.** The server keeps the current update/missing set in memory; clients get it
   on connect and whenever it changes (not persisted, so a server restart re-announces
   once). "Update all" stays client-side and runs sequentially; a second client racing
   it gets the existing "busy" refusal.

## Order and gates

1. Decker: repositories, catalog, install/update from repository, update check, client
   UI — developed against a local test index.
2. `decker-plugins`: create the GitHub repository and its CI. **Needs the user's
   explicit go-ahead before creating the repo or pushing.**
3. Move Counter there; once its first release is live, remove it from Decker.

## Left to the builder

RPC and event names, cache file layout, the exact index validation messages, how the
Pages deploy is done (actions/deploy-pages is the obvious choice), dialog layout
details, and the pinned Decker ref used by `decker-plugins` tooling.
