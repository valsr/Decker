# Decker Plugin Repositories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install and update plugins from user-configured repositories (index URLs), browse them in a "Get More Plugins" view, notify clients of updates, and move Counter into a new `decker-plugins` repository whose CI publishes packages and the index.

**Architecture:** The server owns repositories: it fetches and caches each `index.json`, merges them into a catalog, downloads and verifies packages inside the existing `PluginInstaller` job, and runs a scheduled update check that pushes `plugin_updates_available` to clients. The client adds a Repositories section, a Get More Plugins dialog and an actionable toast. `decker-plugins` is a separate repo: per-plugin folders, Python tools for pack/version-check/index, GitHub Actions publishing Releases + a Pages index.

**Tech Stack:** Python 3.14, stdlib `urllib`/`http.server` (no new dependency), RPyC, PyQt6, pytest + assertpy, GitHub Actions (`actions/deploy-pages`), `gh`.

**Spec:** `docs/superpowers/specs/2026-11-16-decker-plugin-repositories-design.md` (builds on `2026-11-15-decker-plugin-format-design.md`).

## Global Constraints

- Quality gates before every commit that ends a task: `poe format`, `poe mypy`, `poe pylint` ≥ 9.0, `poe test` coverage ≥ 85%. Code style per `CLAUDE.md` (annotations everywhere, methods < 50 lines, ≤ 5 args, docstrings on public only).
- Tests must not touch the network or the real HOME: use a local `http.server` thread on 127.0.0.1 and `tmp_path`-configured paths (`decker.common.paths.configure`).
- No new runtime dependencies; HTTP via `urllib.request`.
- Config keys: `plugin.repositories` (list of URLs, default `["https://valsr.github.io/decker-plugins/index.json"]`), `plugin.update_check` (one of `daily`, `weekly`, `monthly`, `manual`; default `weekly`; intervals 1, 7, 30 days).
- Limits: index ≤ 4 MiB, request timeout 20 s, package download ≤ `MAX_PACKAGE_BYTES` (64 MiB), icon ≤ 512 KiB.
- Index `format` is `1`; download/icon URLs must be `http`/`https` (or `file` only when the index URL itself is `file:`); relative URLs resolve against the index URL.
- Repository add/remove, schedule change, install-from-repository and update are allowed only when `plugin_install_allowed()` is true for the caller (loopback, or `server.allow_remote_plugin_install`).
- Server events: `plugin_updates_available` with payload `{"updates": [{"id", "name", "installed", "available"}], "missing": [{"id", "name", "version", "keys"}]}`. Install progress/finished reuse the existing `plugin_install_progress` / `plugin_install_finished`.
- Repository trust warning (exact copy): "A repository can provide any plugin, and plugins run with your user's permissions. Only add repositories you trust."
- Update-check schedule labels (exact): "Daily", "Weekly", "Monthly", "Manual"; button "Check for updates"; dialog title "Get More Plugins"; toast "N plugin update(s) available" with action "Update all", and "N missing plugin(s) available" with action "Install".
- Never create the GitHub repository, push to it, or enable Pages without the user's explicit go-ahead (Task 12 is gated).
- Commit trailer: `Co-Authored-By: <model> <noreply@anthropic.com>` + `Claude-Session: https://claude.ai/code/session_01FG9NRg8GUrsD61JkRc9neG`.

## Review Focus

1. A repository that is down, slow or returns garbage: the catalog still shows other repositories and the last good cached copy; the repository row shows the error; nothing blocks the UI or the server (Task 3 tests).
2. A hostile or broken index: oversize body, wrong types, duplicate ids, bad sha256, non-http download URL, path-like plugin ids — bad entries are skipped, the rest load (Task 2 tests).
3. A download that is truncated, oversize or has the wrong sha256, or whose manifest id/version differs from the index: the install fails with a clear message and the installed version is untouched (Task 4 tests).
4. Server restarts: a weekly schedule does not re-check on every start; updates are computed from cache offline at start; `manual` never checks by itself (Task 5 tests).
5. "Update all" while another install runs, or from two clients: the second job gets the busy refusal and the runner reports it rather than hanging (Task 9 tests).

---

## Part A — Decker (branch `feat/plugin-repositories`)

### Task 1: Shared Decker version and compatibility helper

**Files:**
- Create: `src/decker/common/version.py`
- Modify: `src/decker/server/server.py`, `src/decker/server/plugins.py`, `src/decker/plugin/environment.py`, `src/decker/server/plugin_installer.py` (`_check_decker_version`)
- Test: `tests/common/test_version.py`

**Interfaces:**
- Produces: `decker_version() -> str` (package metadata, `"0"` when not installed); `is_compatible(specifier: str | None, version: str | None = None) -> bool` (None/empty specifier ⇒ True; invalid specifier ⇒ False; `SpecifierSet.contains(v, prereleases=True)`).

- [ ] **Step 1: Write failing tests** `test_none_specifier_is_compatible`, `test_prerelease_matches` (`is_compatible(">=0.2", "0.3.0.dev1")` is True), `test_excluded` (`is_compatible(">=1.0", "0.2.0")` is False), `test_invalid_specifier_is_incompatible` (`"not a spec"` ⇒ False), `test_default_uses_decker_version` (monkeypatch `decker_version`).
- [ ] **Step 2: Run** `poetry run pytest tests/common/test_version.py -v` — FAIL (module missing).
- [ ] **Step 3: Implement**, replace the three `_decker_version` copies and the installer's specifier check with the helper (installer error message unchanged).
- [ ] **Step 4: Run** the new tests plus `tests/server/test_plugin_installer.py` — PASS.
- [ ] **Step 5: Gates, commit** `refactor: share decker_version and compatibility check`.

### Task 2: Repository index parser

**Files:**
- Create: `src/decker/plugin/repository_index.py`
- Test: `tests/plugin/test_repository_index.py`

**Interfaces:**
- Consumes: v1 manifest id/semver validators from `decker.plugin.manifest` (reuse, do not duplicate the regexes).
- Produces (frozen dataclasses): `IndexVersion(version: str, decker: str | None, url: str, size: int, sha256: str, released: str, contributes: dict[str, list[str]])`; `IndexPlugin(id, name, author, description, category, homepage, icon_url: str | None, versions: tuple[IndexVersion, ...])` (newest first, sorted by `packaging.version.Version`); `RepositoryIndex(name: str, generated: str, plugins: tuple[IndexPlugin, ...], warnings: tuple[str, ...])`; `parse_index(data: bytes, index_url: str) -> RepositoryIndex`; `RepositoryIndexError(Exception)`; `MAX_INDEX_BYTES = 4 * 1024 * 1024`.

- [ ] **Step 1: Write failing tests:**
  - `test_parses_spec_example` — the spec's example index ⇒ one plugin, one version, `icon_url == "https://valsr.github.io/decker-plugins/icons/com.decker.counter.png"` for index URL `https://valsr.github.io/decker-plugins/index.json`.
  - `test_rejects_unknown_format` (`format: 2` ⇒ `RepositoryIndexError`), `test_rejects_oversize` (`MAX_INDEX_BYTES + 1` ⇒ error), `test_rejects_non_object_json`.
  - `test_skips_bad_entries_with_warning` — entries with id `../x`, version `1.0`, sha256 `"zz"`, size `-1`, url `ftp://…`, url `file:///etc/passwd` (index on https) are skipped; one good entry survives; `len(warnings) == 6`.
  - `test_file_urls_allowed_for_file_index` — index URL `file:///tmp/r/index.json`, relative url ⇒ `file:///tmp/r/…`.
  - `test_duplicate_ids_keep_first` (warning added), `test_versions_sorted_newest_first`, `test_plugin_without_valid_versions_skipped`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** with `urllib.parse.urljoin`; strings stripped and length-capped (name 100, description 2000); unknown keys ignored.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Gates, commit** `feat(plugin): repository index format and parser`.

### Task 3: Repository store, fetcher and catalog

**Files:**
- Create: `src/decker/server/repositories.py`
- Modify: `src/decker/common/paths.py` (`repositories() -> Path` = `home()/"repositories"`), `src/decker/common/config/defaults.yml` (`plugin.repositories`, `plugin.update_check`)
- Test: `tests/server/test_repositories.py`, `tests/server/http_fixture.py` (local `ThreadingHTTPServer` on 127.0.0.1:0 serving a tmp dir, with knobs for delay and status)

**Interfaces:**
- Consumes: Task 2 `parse_index`, `RepositoryIndex`.
- Produces:
  - `fetch(url: str, max_bytes: int, timeout: float = 20.0) -> bytes` — schemes http/https/file only; raises `FetchError` on HTTP error, timeout, oversize (stop reading at `max_bytes + 1`).
  - `RepositoryInfo(url, name, plugin_count, last_checked: float | None, error: str | None)`; `CatalogEntry(plugin: IndexPlugin, repository_url: str, shadowed_by: str | None)`.
  - `class RepositoryStore` with `__init__(self, cache_dir: Path)`, `urls() -> list[str]` (from config), `list() -> list[RepositoryInfo]`, `add(url: str) -> RepositoryInfo` (fetch + parse first; raises `RepositoryError` and does not save on failure; duplicates rejected), `remove(url: str) -> bool` (deletes cache), `refresh_all() -> list[RepositoryInfo]` (each repo independently; on failure keep the cached index and record the error), `catalog() -> list[CatalogEntry]` (first configured repository wins per id), `find(plugin_id: str) -> CatalogEntry | None` (non-shadowed), `icon(plugin_id: str) -> bytes | None` (fetched lazily, cached, ≤ 512 KiB), `last_check() -> float | None`, `mark_checked(when: float) -> None`.
  - Cache layout: `cache_dir/<sha1(url)[:16]>/index.json`, `meta.json` (`url`, `last_checked`, `error`), `icons/<plugin-id>`; `cache_dir/state.json` (`last_check`). All writes atomic (tmp + `os.replace`). Thread-safe (one lock).
- Config writes go through `decker.common.config.set("plugin.repositories", [...])`.

- [ ] **Step 1: Write failing tests:** `test_add_valid_repository_persists_url`, `test_add_invalid_repository_not_saved` (404 and bad JSON), `test_add_duplicate_rejected`, `test_remove_clears_cache`, `test_refresh_failure_keeps_cached_catalog` (serve, refresh, stop server, refresh ⇒ catalog unchanged, `error` set), `test_timeout` (server delay > timeout passed as 0.5 s ⇒ `FetchError`), `test_oversize_body_rejected`, `test_first_repository_wins` (same id in two repos ⇒ second has `shadowed_by`), `test_icon_cached_after_first_fetch`, `test_state_persists_last_check` (new store instance reads it), `test_rejects_unsupported_scheme` (`ftp://`).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Gates, commit** `feat(server): plugin repository store and catalog`.

### Task 4: Install from repository (download inside the job)

**Files:**
- Modify: `src/decker/server/plugin_installer.py`
- Test: `tests/server/test_plugin_installer.py` (new tests; reuse Task 3's `http_fixture`)

**Interfaces:**
- Consumes: Task 2 `IndexVersion`, Task 3 `fetch` constants.
- Produces: `PluginInstaller.install_from_repository(plugin_id: str, version: IndexVersion) -> str` (job id; same busy rule as `install`). The job: progress `Downloading <id> <version> (NN%)` at most every 10 %, verify `len == size` and sha256 (`hashlib`), then the normal install path with `expect=(plugin_id, version.version)`; manifest mismatch raises `PluginInstallError("package is <id> <ver>, index says <id> <ver>")`. `_install(job_id, data, progress, expect: tuple[str, str] | None = None)`.

- [ ] **Step 1: Write failing tests:** `test_repository_install_succeeds` (serve a packed fixture plugin; job finishes ok; `plugin_install_finished` pushed with id/version), `test_sha_mismatch_fails_and_keeps_installed_version`, `test_truncated_download_fails` (size larger than served bytes), `test_manifest_mismatch_fails`, `test_busy_while_job_running`, `test_download_progress_events` (at least one `Downloading` progress message).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** (download streamed in 64 KiB chunks via `urllib`, capped at `min(version.size, MAX_PACKAGE_BYTES)`; the op lock is held for the whole job).
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Gates, commit** `feat(plugin): install plugins from a repository with verified downloads`.

### Task 5: Update checker and schedule

**Files:**
- Create: `src/decker/server/update_checker.py`
- Test: `tests/server/test_update_checker.py`

**Interfaces:**
- Consumes: Task 1 `is_compatible`, Task 3 `RepositoryStore`, `PluginManager.plugins()` (installed id → version), `KeyAssignmentStore.assignments_for_plugin` / a new `KeyAssignmentStore.plugin_ids() -> set[str]`.
- Produces:
  - `SCHEDULES = {"daily": 1, "weekly": 7, "monthly": 30, "manual": None}` (days).
  - `UpdateReport(updates: tuple[dict, ...], missing: tuple[dict, ...])` with `to_payload() -> dict` matching the Global Constraints event payload.
  - `class UpdateChecker`, `__init__(self, store, plugin_manager, key_store, push: Callable[[str, dict], None], clock: Callable[[], float] = time.time)`; `start() -> None` (computes a report from cache without network, pushes if non-empty, then starts a daemon thread waking every hour that calls `check_if_due()`); `stop()`; `check_if_due() -> bool`; `check_now() -> UpdateReport` (refresh_all, mark_checked, recompute, push on change); `report() -> UpdateReport`; `schedule() -> str`; `set_schedule(name: str) -> None` (validates, writes `plugin.update_check`).
  - Update = installed plugin whose non-shadowed catalog entry has a greater latest *compatible* version; missing = plugin id referenced by key assignments, not installed, offered by a repository (latest compatible), `keys` = assignment count.

- [ ] **Step 1: Write failing tests** (fake clock, fake store/plugin manager where needed, real `KeyAssignmentStore` on tmp db): `test_update_detected`, `test_newer_local_version_is_up_to_date`, `test_incompatible_version_ignored`, `test_missing_plugin_reported_with_key_count`, `test_weekly_not_due_after_restart` (state last_check 2 days ago ⇒ `check_if_due()` False, no fetch), `test_due_after_interval`, `test_manual_never_due`, `test_start_uses_cache_without_network` (store whose fetch raises ⇒ report still computed), `test_push_only_on_change`, `test_set_schedule_rejects_unknown`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Gates, commit** `feat(server): scheduled plugin update checks`.

### Task 6: Repository RPCs and server wiring

**Files:**
- Modify: `src/decker/server/server_context.py`, `src/decker/server/server.py` (create store + checker, `start()`/`stop()` with the server), `src/decker/server/service.py`
- Test: `tests/server/test_service.py`

**Interfaces:**
- Consumes: Tasks 3–5.
- Produces RPCs on `DeckerService` (JSON-safe return values; mutating ones return `False`/raise-free error strings when not allowed):
  - `repositories_list() -> list[dict]`, `repository_add(url: str) -> str` (empty string on success, else error message), `repository_remove(url: str) -> bool`, `repositories_check() -> dict` (runs `check_now()` off the RPC thread is not required; returns the report payload).
  - `repository_catalog() -> list[dict]` (per plugin: id, name, author, description, category, homepage, repository, shadowed_by, installed_version, latest_compatible, versions[{version, decker, size, released, compatible, contributes}]), `repository_icon(plugin_id: str) -> str` (base64 or "").
  - `plugin_install_from_repository(plugin_id: str, version: str = "") -> str` (job id; empty version = latest compatible; error message prefixed `error:` when refused).
  - `plugin_updates() -> dict` (current report payload), `update_check_schedule() -> str`, `update_check_set_schedule(name: str) -> bool`.

- [ ] **Step 1: Write failing tests:** each RPC's happy path through a `DeckerService` with a configured context (existing test helpers), plus `test_mutating_repository_rpcs_refused_for_remote_peer` (add, remove, schedule, install-from-repo with a non-loopback peer and the setting off), and `test_install_incompatible_version_refused`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement**; the `commands()` introspection exposes them to the CLI automatically.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Gates, commit** `feat(server): repository and update RPCs`.

### Task 7: Client — events and Repositories section

**Files:**
- Modify: `src/decker/client/events/__init__.py` (`PluginUpdatesAvailableEvent(updates: list[dict], missing: list[dict])`), `src/decker/client/connection_manager.py` (route `plugin_updates_available`; fetch `plugin_updates` once on connect and push the event)
- Create: `src/decker/client/widgets/repositories_section.py` (`RepositoriesSection(QWidget)`)
- Modify: `src/decker/client/widgets/plugins_tab.py` (embed the section and a "Get More Plugins…" button that Task 8 wires)
- Test: `tests/client/widgets/test_repositories_section.py`, `tests/client/test_connection_manager.py`

**Interfaces:**
- Produces: `RepositoriesSection.refresh() -> None`; Add asks for a URL then shows the trust warning (exact copy) before calling `repository_add`; Remove confirms; schedule combo ("Daily", "Weekly", "Monthly", "Manual") calls `update_check_set_schedule`; "Check for updates" calls `repositories_check` on a worker thread and refreshes; rows show URL, name, plugin count, last checked, error. Mutating controls disabled when `install_allowed()` is false. All RPCs off the UI thread (same worker pattern as `install_package_file`).

- [ ] **Step 1: Write failing tests:** `test_lists_repositories_with_error`, `test_add_shows_trust_warning_and_calls_rpc` (monkeypatched dialog), `test_add_cancelled_on_warning_does_not_call`, `test_schedule_change_calls_rpc`, `test_check_for_updates_runs_off_ui_thread`, `test_controls_disabled_when_not_allowed`, `test_updates_event_routed` (connection manager).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Gates, commit** `feat(client): repositories section and update events`.

### Task 8: Client — Get More Plugins dialog

**Files:**
- Create: `src/decker/client/widgets/get_more_plugins.py` (`GetMorePluginsDialog(QDialog)`)
- Modify: `src/decker/client/widgets/plugins_tab.py` (button opens it, non-modal, single instance)
- Test: `tests/client/widgets/test_get_more_plugins.py`

**Interfaces:**
- Consumes: `repository_catalog`, `repository_icon`, `plugin_install_from_repository`, existing install progress/finished events.
- Produces: search (name, id, description, author; case-insensitive), category combo built from catalog ("All categories" first), Refresh (re-reads catalog); rows: icon, name, short description, `installed → available` or `available`, button Install / Update / Installed (disabled) / "Requires Decker X" (disabled when no compatible version); details pane: description, author, homepage link, contributions, size (human-readable), repository, required Decker. Icons load incrementally (`QTimer.singleShot(0)` chain, like the icon picker). While a job runs, its row button shows progress text and all Install/Update buttons are disabled; on finish the catalog refreshes.

- [ ] **Step 1: Write failing tests:** `test_filters_by_search_and_category`, `test_button_states` (not installed / update / installed / incompatible), `test_install_calls_rpc_and_disables_buttons`, `test_finished_event_refreshes`, `test_details_pane_shows_size_and_repository`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Gates, commit** `feat(client): Get More Plugins dialog`.

### Task 9: Client — update toast, Update all, badges

**Files:**
- Modify: `src/decker/client/window.py` (toast gets an optional action button; shown for `PluginUpdatesAvailableEvent` only when its content differs from the last one shown)
- Create: `src/decker/client/update_runner.py` (`UpdateRunner`, Qt-free)
- Modify: `src/decker/client/widgets/plugins_tab.py` (badge "Update available: X" on rows)
- Test: `tests/client/test_update_runner.py`, `tests/client/test_window.py` (or the existing window test module), `tests/client/widgets/test_plugins_tab.py`

**Interfaces:**
- Produces: `UpdateRunner(call: Callable[..., Any])` with `run(plugin_ids: list[str]) -> None` (sequential: start `plugin_install_from_repository(id)`, wait for the matching `plugin_install_finished` via `on_finished(job_id, ok, message)`, then the next), `on_finished(...)`, `results: dict[str, str]` (ok / error text), `busy` refusal recorded as an error for that id and the runner continues. Toast text per Global Constraints; "Update all" runs the runner over `updates`, "Install" over `missing`; on completion a toast summarises successes/failures.

- [ ] **Step 1: Write failing tests:** `test_runner_sequential` (second call only after first finished), `test_runner_records_busy_and_continues`, `test_toast_action_shown_for_updates`, `test_toast_not_repeated_for_same_report`, `test_plugins_tab_badges_updates`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Gates, commit** `feat(client): update notifications and Update all`.

### Task 10: Docs for repositories

**Files:**
- Create: `docs/plugins/repositories.md` (index format v1 with the spec example, URL rules and limits, hosting your own repository on GitHub Releases + Pages, trust model, update schedule)
- Modify: `docs/plugins/README.md` (link), `README.md` (plugins section: repositories, Get More Plugins), `CLAUDE.md` (plugins paragraph: repositories served by the server, `plugin_updates_available`, loopback gating)

- [ ] **Step 1:** Write the docs; every number matches Global Constraints and the code.
- [ ] **Step 2:** `poe format && poe pylint` (unchanged), commit `docs: plugin repositories`.

---

## Part B — `decker-plugins` (local tree `/work/decker/decker-plugins`, no remote)

### Task 11: Repository tree, Counter, tools and CI workflows

**Files (in `/work/decker/decker-plugins`, `git init -b main`):**
- `plugins/com.decker.counter/` — copied from Decker `src/decker/bundled_plugins/com.decker.counter/` (no `__pycache__`); `plugins/com.decker.counter/tests/test_counter.py` ported from Decker `tests/bundled_plugins/test_counter.py` to run against the plugin dir.
- `pyproject.toml` (uv project; dev deps: pytest, assertpy; `decker @ git+https://github.com/valsr/Decker.git@<pinned commit or tag>`), `README.md` (how to add a plugin, version rule, how to add this repository to Decker), `.gitignore`.
- `tools/pack_all.py` — `pack_all(plugins_dir: Path, out_dir: Path) -> list[Path]` using `decker.cli.plugin_scaffold.pack`.
- `tools/check_versions.py` — `check_versions(repo: Path, base_ref: str) -> list[str]` (errors): for each plugin changed vs `base_ref`, manifest version must be greater than the highest `<id>-v*` git tag; also manifest `version` must be valid semver.
- `tools/release_meta.py` — `version_entry(package: Path, url: str, released: str) -> dict` (the index `versions[]` entry: version, decker, url, size, sha256, released, contributes names) written as `<package>.json` sidecar.
- `tools/build_index.py` — `build_index(entries: list[dict], plugins_dir: Path, out_dir: Path) -> Path`: groups sidecar entries by plugin id, takes name/author/description/category/homepage from the current manifest, copies each plugin's icon to `icons/<id>.png`, writes `index.json` (`format: 1`, newest version first). Its output must parse with Decker's `parse_index` (test imports it).
- `tests/tools/test_*.py` for each tool.
- `.github/workflows/ci.yml` (PR + push): per-plugin tests, `check_versions` against `origin/main` (PR) , `pack_all`, upload artifacts.
- `.github/workflows/publish.yml` (push to main, `permissions: contents: write, pages: write, id-token: write`): pack all; for each package without a release tag, `gh release create <id>-v<ver> <pkg> <pkg>.json`; download every release's `*.json` sidecar (`gh release download --pattern '*.json'`); `build_index`; `actions/upload-pages-artifact` + `actions/deploy-pages`. Never edits existing releases.

- [ ] **Step 1: Write failing tool tests:** `test_pack_all_packs_counter`, `test_check_versions_flags_unbumped_change` (temp git repo with a tag), `test_check_versions_passes_bumped`, `test_version_entry_sha_and_size`, `test_build_index_parses_with_decker` (via `decker.plugin.repository_index.parse_index`), `test_build_index_keeps_older_versions`.
- [ ] **Step 2: Run** `uv run pytest` — FAIL.
- [ ] **Step 3: Implement** tools, copy Counter, port its tests, write workflows (validate YAML syntax with `python -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))"`).
- [ ] **Step 4: Run** `uv run pytest` — PASS; `uv run python tools/pack_all.py` produces `com.decker.counter-1.0.0.deckerplugin` that installs into a Decker test server via `install_from_repository` served from a local index built by `build_index` (end-to-end test in Decker's suite is not required; run it manually and record the output in the report).
- [ ] **Step 5: Commit** in `/work/decker/decker-plugins` (`feat: decker-plugins repository with Counter`). Do not add a remote.

### Task 12: Publish `decker-plugins` (GATED — user go-ahead required)

- [ ] **Step 1:** Ask the user. On approval: `gh repo create valsr/decker-plugins --public --source /work/decker/decker-plugins --push` (HTTPS), set Pages source to GitHub Actions (`gh api -X POST repos/valsr/decker-plugins/pages -f build_type=workflow`).
- [ ] **Step 2:** Watch `publish.yml`; verify `https://valsr.github.io/decker-plugins/index.json` lists Counter 1.0.0 and the release asset's sha256 matches.

## Part C — Decker without bundled plugins

### Task 13: Remove bundled Counter and the bundled mechanism (merge only after Task 12 is live)

**Files:**
- Delete: `src/decker/bundled_plugins/`, `tests/bundled_plugins/`
- Modify: `src/decker/server/plugins.py` (drop `_BUNDLED_PLUGINS_DIR`, `_bundled_loader`), `src/decker/plugin/loader.py` / `InstalledPlugin` (drop `bundled`), `src/decker/plugin/runtime/launcher.py` (drop the `bundled` parameter; always the plugin venv), `src/decker/server/plugin_installer.py` (drop bundled guards), `src/decker/cli/app.py` (drop the "(bundled)" suffix), tests that relied on Counter (`test_plugins.py`, `test_plugin_installer.py`, `test_contributions.py`, `test_action_icons.py`, `test_sidebar.py`, `test_manifest.py`, `test_key_assignments.py`) now use a fixture plugin under `tests/fixtures/plugins/` with the same shape (action with settings + an icon pack).
- Modify: `src/decker/server/plugins.py` — a key whose plugin is not installed keeps its assignment and gets the label "Plugin missing" (the existing failure-label path), so offline users see why the key is blank.
- Test: `tests/server/test_plugins.py` (`test_key_for_missing_plugin_keeps_assignment_and_label`), `tests/server/test_update_checker.py` already covers the missing report.

- [ ] **Step 1: Write the failing test** `test_key_for_missing_plugin_keeps_assignment_and_label`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** the removal and fixture migration; `grep -rn "bundled" src tests` returns only unrelated hits (asset `default-key.svg`).
- [ ] **Step 4: Run** full `poe test` — PASS, coverage ≥ 85%.
- [ ] **Step 5: Gates, commit** `feat!: plugins come from repositories; remove bundled Counter`. PR note: merge after `decker-plugins` Counter 1.0.0 is published.
