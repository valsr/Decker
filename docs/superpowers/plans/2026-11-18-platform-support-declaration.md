# Platform Declaration, Filter and Tables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let plugin manifests and repository index entries declare supported platforms, let the plugin browser filter on the server's platform, and add support tables to this repo and the plugins repo.

**Architecture:** A pure module `decker.common.platforms` parses platform specs, detects the host platform and matches the two. The manifest and the repository index reuse its parser. The server exposes `platform_info` and adds `platforms`/`linux`/`supported` to catalog and installed-plugin payloads. The client browser filters on `supported`, badges mismatches and warns before installing one.

**Tech Stack:** Python 3, PyQt6, RPyC, pytest + assertpy.

**Spec:** `docs/superpowers/specs/2026-11-18-platform-support-design.md` (project 1 of 3).

## Global Constraints

- Platform model: `os` is `linux` | `windows` | `macos`; Linux hosts also have `desktop` (`kde` | `gnome` | `other`) and `session` (`wayland` | `x11`); any host value may be `unknown`.
- Manifest fields (still `format: 1`, optional): `"platforms"`: non-empty list of OS names, omitted = all platforms; `"linux"`: `{"desktops": [...], "sessions": [...]}`, each key a non-empty list, omitted = any; `linux` is only allowed when `platforms` is absent or contains `linux`.
- Unknown OS names in `platforms` are kept and never match; malformed values (not a list, empty list, non-string items, wrong types) are validation errors.
- Repository index (format v1, additive): each version entry may carry the same `platforms`/`linux` fields; an invalid value skips that version with a warning, other versions of the plugin are kept.
- Matching: spec absent -> supported; otherwise host `os` must be listed; for a Linux host each `linux` constraint must contain the host's desktop/session, and a host value of `unknown` satisfies any constraint on that axis.
- Detection: `os` from `sys.platform` (`linux*`, `win32`, `darwin`); Linux `desktop` from `XDG_CURRENT_DESKTOP` (case-insensitive, may be a colon-separated list; contains `kde` -> `kde`, contains `gnome` -> `gnome`, other non-empty -> `other`, unset/empty -> `unknown`); `session` from `XDG_SESSION_TYPE` (`wayland`/`x11`, else `unknown`).
- Install behaviour: warn and ask for confirmation for an unsupported plugin, never block; an installed plugin that does not match still loads and the server logs a warning.
- Project rules: annotate everything (tests too), methods < 50 lines, max 5 args, docstrings on public items only, black 120. Gates before done: `poe format`, `poe mypy`, `poe pylint` (>= 9.0), `poe test` (coverage >= 85%). Tests use pytest + assertpy and mirror `src/` under `tests/`.
- Standing rule (project memory): every feature and plugin change keeps the per-platform support table current.

## Review Focus

- `platforms: []`, `"platforms": "linux"` (a string), `"platforms": ["linux", 3]`, and `"linux"` present with `platforms: ["windows"]` are all rejected with a clear message (Task 2).
- A plugin listing only an unknown OS (`["freebsd"]`) is unsupported on every known host, while a manifest with no platform fields is supported everywhere (Task 1).
- A headless Linux server with no `XDG_*` variables still counts as supporting a plugin limited to `linux` + `desktops: ["kde"]` (Task 1).
- `XDG_CURRENT_DESKTOP` spellings `KDE`, `ubuntu:GNOME`, `X-Cinnamon`, `kde` (lowercase) and an empty string map as specified (Task 1).
- An index plugin whose newest version has an invalid platform field is still listed with its other versions; the catalog `supported` flag follows the latest compatible version (Tasks 3 and 4).
- With the browser filter off an unsupported plugin shows its badge and Cancel on the confirmation does not install it (Task 5).

---

### Task 1: Platform model, detection and matching

**Files:**
- Create: `src/decker/common/platforms.py`
- Test: `tests/common/test_platforms.py`

**Interfaces:**
- Produces in `decker.common.platforms`:
  - `OS_NAMES: tuple[str, ...] = ("linux", "windows", "macos")`, `LINUX_DESKTOPS = ("kde", "gnome", "other")`, `LINUX_SESSIONS = ("wayland", "x11")`, `UNKNOWN = "unknown"`
  - `@dataclass(frozen=True) class HostPlatform: os: str; desktop: str = "unknown"; session: str = "unknown"` with `label(self) -> str` (`"Linux (KDE, Wayland)"`; unknown parts omitted; `"Windows"`, `"macOS"`; other OS names capitalised) and `to_payload(self) -> dict[str, str]` (keys `os`, `desktop`, `session`)
  - `detect_platform(environ: Mapping[str, str] | None = None, platform_name: str | None = None) -> HostPlatform` (defaults: `os.environ`, `sys.platform`; non-Linux hosts get `unknown` desktop/session; unrecognised platform names become the lowercased name as `os`)
  - `@dataclass(frozen=True) class PlatformSpec: os: tuple[str, ...] | None = None; desktops: tuple[str, ...] | None = None; sessions: tuple[str, ...] | None = None` with `to_payload(self) -> dict[str, Any]` returning `{"platforms": [...]}` and/or `{"linux": {"desktops": [...], "sessions": [...]}}` containing only the set keys (empty dict when nothing is set)
  - `parse_platform_spec(platforms: Any, linux: Any) -> PlatformSpec | None` — `None` when both inputs are `None`; raises `ValueError(message)` per Global Constraints; names are lowercased and stripped
  - `platform_supports(spec: PlatformSpec | None, host: HostPlatform) -> bool`

- [ ] **Step 1: Write failing tests** (names, with the assertions the Global Constraints and Review Focus give): `test_detect_platform_maps_sys_platform_names` (`linux`, `win32`, `darwin`, `freebsd13` -> `freebsd`); `test_detect_linux_desktop_spellings` for `KDE`, `ubuntu:GNOME`, `X-Cinnamon` (other), `kde`, `""` and unset (unknown); `test_detect_linux_session` (`wayland`, `x11`, `tty` -> unknown, unset -> unknown); `test_detect_non_linux_has_unknown_desktop_and_session`; `test_label_formats`; `test_parse_returns_none_when_nothing_declared`; `test_parse_rejects_malformed_values` parametrised over `([], None)`, `("linux", None)`, `(["linux", 3], None)`, `(["windows"], {"desktops": ["kde"]})`, `(None, {"desktops": []})`, `(None, "kde")`, `(None, {"sessions": "x11"})`; `test_parse_lowercases_and_keeps_unknown_names`; `test_supports_everything_without_a_spec`; `test_supports_requires_the_host_os`; `test_unknown_os_only_matches_nothing_known` (`["freebsd"]` vs linux, windows, macos hosts); `test_linux_constraints_filter_desktop_and_session`; `test_unknown_host_values_satisfy_any_constraint` (HostPlatform("linux") vs desktops `["kde"]` and sessions `["wayland"]` -> True); `test_linux_constraints_ignore_non_linux_hosts` (a Windows host vs a spec with `platforms` omitted and a `linux` block -> True); `test_to_payload_contains_only_set_keys`.
- [ ] **Step 2: Run** `poe test tests/common/test_platforms.py` — expect FAIL (module missing).
- [ ] **Step 3: Implement** the interfaces above.
- [ ] **Step 4: Run** the tests — expect PASS.
- [ ] **Step 5: Commit** `feat: platform model, detection and matching`.

---

### Task 2: Manifest platform fields

**Files:**
- Modify: `src/decker/plugin/manifest.py` (`PluginManifest`, `from_dict`)
- Test: `tests/plugin/test_manifest.py` (add)

**Interfaces:**
- Consumes: `parse_platform_spec`, `PlatformSpec` (Task 1).
- Produces: `PluginManifest.platforms: PlatformSpec | None = None` (last dataclass field, default `None`, so existing constructors keep working); `from_dict` fills it from `data.get("platforms")` and `data.get("linux")`, turning a `ValueError` into `ManifestValidationError(f"manifest {message}")`.

- [ ] **Step 1: Write failing tests**: `test_manifest_without_platform_fields_has_no_spec`; `test_manifest_parses_platforms_and_linux_block` (`["linux", "windows"]` plus `{"desktops": ["kde"], "sessions": ["wayland"]}`); `test_manifest_rejects_malformed_platform_values` parametrised over the four Review Focus cases plus `"platforms": []`, asserting `ManifestValidationError`; `test_manifest_keeps_unknown_os_names`. Follow the file's existing helper for a minimal valid manifest dict.
- [ ] **Step 2: Run** `poe test tests/plugin/test_manifest.py -k platform` — expect FAIL.
- [ ] **Step 3: Implement** the field and parsing; keep `from_dict` under 50 lines by extracting a private helper if needed.
- [ ] **Step 4: Run** `poe test tests/plugin` — expect PASS.
- [ ] **Step 5: Commit** `feat: manifest declares supported platforms`.

---

### Task 3: Repository index platform fields

**Files:**
- Modify: `src/decker/plugin/repository_index.py` (`IndexVersion`, `_parse_version`)
- Test: `tests/plugin/test_repository_index.py` (add)

**Interfaces:**
- Consumes: `parse_platform_spec`, `PlatformSpec` (Task 1).
- Produces: `IndexVersion.platforms: PlatformSpec | None = None` (last field, default `None`); `_parse_version` reads `raw.get("platforms")` / `raw.get("linux")`, mapping `ValueError` to `_EntryError(f"invalid platform data: {message}")` so the version is skipped with the existing warning.

- [ ] **Step 1: Write failing tests**: `test_index_version_without_platform_fields_supports_all` (`platforms is None`); `test_index_version_parses_platform_fields`; `test_invalid_platform_data_skips_only_that_version` (two versions, the newest invalid: the plugin is listed with the older version and `index.warnings` has one entry mentioning the plugin id).
- [ ] **Step 2: Run** `poe test tests/plugin/test_repository_index.py -k platform` — expect FAIL.
- [ ] **Step 3: Implement** the field and parsing.
- [ ] **Step 4: Run** `poe test tests/plugin tests/server/test_repositories.py` — expect PASS.
- [ ] **Step 5: Commit** `feat: repository index versions declare supported platforms`.

---

### Task 4: Server RPC and payloads

**Files:**
- Modify: `src/decker/server/service.py` (`_catalog_item`, `_plugin_info`, new RPC), `src/decker/server/plugins.py` (load-time warning; find where a plugin is registered after its manifest loads)
- Test: `tests/server/test_service.py`, `tests/server/test_plugins.py`

**Interfaces:**
- Consumes: `detect_platform`, `HostPlatform`, `platform_supports`, `PlatformSpec.to_payload` (Task 1); `PluginManifest.platforms` (Task 2); `IndexVersion.platforms` (Task 3).
- Produces:
  - RPC `platform_info(self) -> str`, `@exposed`, docstring present, returns `json.dumps(detect_platform().to_payload())`, plus `"label"` (`HostPlatform.label()`); no gating.
  - Catalog item payloads (from `repository_catalog`) gain `"platforms": list[str] | None`, `"linux": dict | None` and `"supported": bool`, taken from the latest compatible version (or the newest version when none is compatible); each entry of `"versions"` gains the same `platforms`/`linux` keys. `_catalog_item` gets a `host: HostPlatform` argument (5 args max).
  - Installed-plugin payloads (`_plugin_info`) gain `"platforms"`, `"linux"` and `"supported"` from the manifest, evaluated against the same host.
  - The plugin manager logs `logging.warning("[%s] plugin does not declare support for this platform (%s)", plugin_id, host.label())` once when it registers a plugin whose spec does not match the host.

- [ ] **Step 1: Write failing tests**: `test_platform_info_reports_the_detected_host` (monkeypatch `decker.server.service.detect_platform` to return `HostPlatform("linux", "kde", "wayland")`; JSON has `os`, `desktop`, `session` and `label == "Linux (KDE, Wayland)"`); `test_platform_info_is_not_gated_for_remote_clients`; `test_catalog_item_marks_unsupported_plugins` (a catalog entry whose latest version is `platforms: ["windows"]` on a Linux host -> `supported is False`, `platforms == ["windows"]`); `test_catalog_supported_follows_the_latest_compatible_version` (newest version incompatible with this Decker and unsupported, older compatible version supported -> `supported is True`); `test_catalog_item_without_platform_data_is_supported_with_none_fields`; `test_installed_plugin_info_includes_platform_fields`; in `test_plugins.py` `test_registering_a_mismatching_plugin_logs_a_warning_but_loads_it` (use `caplog`; the plugin is still in `plugins()`). Follow the existing fixtures for building catalog entries and manifests.
- [ ] **Step 2: Run** the new tests — expect FAIL.
- [ ] **Step 3: Implement** as above; keep `repository_catalog` passing the host once (`detect_platform()` per call is fine).
- [ ] **Step 4: Run** `poe test tests/server` — expect PASS, including `test_protocol_conformance.py` (if it fails for an undocumented RPC, add the `platform_info` row to `docs/plugins/protocol.md` in this task).
- [ ] **Step 5: Commit** `feat: platform_info RPC and platform data in plugin payloads`.

---

### Task 5: Browser filter, badges and install confirmation

**Files:**
- Modify: `src/decker/client/widgets/get_more_plugins.py`, `src/decker/client/widgets/plugins_tab.py`
- Test: `tests/client/widgets/test_get_more_plugins.py`, `tests/client/widgets/test_plugins_tab.py` (extend the existing modules; create only if absent, following their sibling tests for fixtures and fake connection managers)

**Interfaces:**
- Consumes: catalog items with `supported`, `platforms`, `linux`; RPC `platform_info` (Task 4); installed-plugin items with `supported`.
- Produces: in `GetMorePluginsDialog` a checkbox `_platform_only` labelled `Only show plugins that support this system (<host label>)`, checked by default; its state is stored and restored through the client's `UiStateStore` under the key `plugins.platform_filter` (follow how other client widgets read and write that store); `_apply_filter` skips items whose `supported` is `False` while it is checked; unsupported rows show the text `Not supported on <host label>` (badge) when visible; `_on_install` for an unsupported plugin asks `QMessageBox.question` ("<name> does not declare support for <host label>. Install anyway?") and returns without installing on No. A small pure helper `platform_badge(plugin: dict[str, Any], host_label: str) -> str` (empty string when supported) is shared with `plugins_tab.py`, which appends the badge to rows of installed plugins whose `supported` is `False`.

- [ ] **Step 1: Write failing tests**: `test_platform_badge_is_empty_for_supported_plugins_and_names_the_host_otherwise`; `test_filter_hides_unsupported_plugins_by_default`; `test_unchecking_the_filter_shows_unsupported_plugins_with_a_badge`; `test_install_of_an_unsupported_plugin_asks_and_cancel_does_not_install`; `test_install_of_an_unsupported_plugin_proceeds_on_yes`; `test_filter_choice_is_remembered`; `test_installed_plugin_rows_show_the_badge`. Patch `QMessageBox.question` the way sibling tests patch dialogs; use a fake caller returning canned `repository_catalog` and `platform_info` payloads.
- [ ] **Step 2: Run** `poe test tests/client/widgets -k "platform or badge"` — expect FAIL.
- [ ] **Step 3: Implement** the checkbox, filter, badge, confirmation and installed-list badge. `platform_info` is fetched with the catalog on the worker thread (`_run`), never on the UI thread.
- [ ] **Step 4: Run** `poe test tests/client` — expect PASS.
- [ ] **Step 5: Commit** `feat: filter and badge plugins by the server platform`.

---

### Task 6: Docs, support table and standing rule

**Files:**
- Create: `docs/platform-support.md`
- Modify: `docs/plugins/package-and-manifest.md`, `docs/plugins/repositories.md`, `docs/plugins/protocol.md` (only where not already updated), `CLAUDE.md`

**Interfaces:** none (documentation).

- [ ] **Step 1: Write `docs/platform-support.md`**: the five platform tiers as columns (Linux Arch/Plasma/Wayland, Linux Ubuntu/Debian/Fedora/GNOME, Linux other, Windows, macOS), a legend (`Yes`, `Partial` with a footnote, `Planned`, `No`, `Not verified`), and one row per core feature: server and monitor, hardware access (HID), GUI client, system tray, plugin runtime (process isolation), plugin install and repositories, System Icons, user icon import, GIF animations, CLI, daemon mode. Fill the cells honestly by reading the code (for example plugin process control uses POSIX process groups and `/proc`, the monitor reads `/proc` RSS, System Icons need freedesktop themes): tier 1 is `Yes` where the author has verified it, everything unverified is `Not verified`, known gaps are `No` or `Partial` with a footnote naming the cause. State the standing rule at the top and that the plugins repo has its own table.
- [ ] **Step 2: Document the fields**: `package-and-manifest.md` gets `platforms` and `linux` (table rows, the matching rules, the `unknown` host note, an example); `repositories.md` gets the per-version fields, the new `supported`/`platforms`/`linux` catalog keys and the filter behaviour; `protocol.md` gets `platform_info` if Task 4 did not add it. Keep the docs in sync with Global Constraints.
- [ ] **Step 3: `CLAUDE.md`**: add one short section "Platform support" stating the five tiers in priority order, that every feature and plugin must target them, and that `docs/platform-support.md` (and the plugins repo's table) must be updated in the same change.
- [ ] **Step 4: Commit** `docs: platform support table, manifest fields and standing rule`.

---

### Task 7: Plugins repo (separate repo, separate branch)

**Files (in `/work/decker/decker-plugins`):**
- Modify: `tools/release_meta.py` (`version_entry`), `README.md`
- Create: `docs/platform-support.md`
- Test: `tests/tools/test_release_meta.py` (add), `tests/tools/test_build_index.py` (add)

**Interfaces:**
- Consumes: `PluginManifest.platforms` and `PlatformSpec.to_payload()` from the Decker package this repo imports (`decker.plugin.package.read_manifest`); check `pyproject.toml` for how the repo depends on decker and run against the local checkout with the new fields (e.g. an editable/path install); if the dependency cannot see the new fields locally, record that in the report and stop for ruling.
- Produces: `version_entry(package, url, released)` copies `platforms` and `linux` from the package's manifest into the entry (keys omitted when not declared), so `build_index` carries them into `index.json` unchanged.

- [ ] **Step 1:** In `/work/decker/decker-plugins` create a branch `feat/platform-support-table` from its default branch (pull first).
- [ ] **Step 2: Write failing tests**: `test_version_entry_includes_declared_platforms` (a temp plugin whose manifest declares `"platforms": ["linux", "macos"]` and a `linux` block -> entry has `platforms` and `linux` equal to the declared values); `test_version_entry_omits_platform_keys_when_undeclared`; `test_build_index_keeps_platform_keys_on_versions`. Run `uv run pytest tests/tools -q` — expect FAIL.
- [ ] **Step 3: Implement** the `version_entry` change; run the tests — expect PASS.
- [ ] **Step 4: Create `docs/platform-support.md`**: plugins (rows: counter, fontawesome, icon, pages, profiles) against the five tiers, every cell `Not audited` (project 3 fills them), a legend matching the Decker repo's, and a note that every plugin change must update it; link it from `README.md`.
- [ ] **Step 5: Commit** `feat: carry platform declarations into the index and add the support table` in that repo. Do not push or open a PR.
