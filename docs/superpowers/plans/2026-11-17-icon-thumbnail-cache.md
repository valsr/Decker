# Icon Thumbnail Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show icon thumbnails from a memory + disk cache (memory hit, else disk hit, else fetch and render, then store in both), invalidated when a plugin's version changes.

**Architecture:** The server adds `plugin_version` to each `iconpacks_list` entry. A client-side `IconThumbnailCache` (in-memory LRU in front of PNG files under `<prefix>/.decker/cache/icons/`) is keyed by pack, plugin version, icon path, size and tint, and prunes superseded versions and uninstalled packs. The icon browser and the `IconEdit` preview use it and skip the `iconpack_icon` RPC on a hit.

**Tech Stack:** Python 3.14, PyQt6, pytest + assertpy, poetry/poe.

**Spec:** `docs/superpowers/specs/2026-11-17-icon-thumbnail-cache-design.md`

## Global Constraints

- Cache key: `(pack id, plugin version, icon path, size px, tint)`; tint is the `#rrggbb[aa]` string or `None`.
- Disk layout: `<root>/<pack>/<version>/<size>-<tint>/<sha256(path)[:32]>.png`; `<pack>` and `<version>` are used as directory names only when they match `^[A-Za-z0-9._-]{1,128}$` and are not `.`/`..`, otherwise `sha256(value)[:32]`; `<tint>` is the hex without `#`, lower case, or `none`. Nothing is ever written outside `<root>`.
- Writes are atomic (temp file in the same directory, then `os.replace`). A failed write, an unwritable directory, or an unreadable/zero-byte/corrupt PNG is a cache miss and never raises; a corrupt file is deleted.
- A pack without a known `plugin_version` (older server) is cached in memory only.
- Memory LRU holds at most 2048 pixmaps. Disk reads happen on the UI thread. No size cap on disk.
- Default root is `decker.common.paths.icon_cache()` = `home() / "cache" / "icons"`, so `--prefix` is honoured.
- Decker conventions: black 120, full annotations, <= 50-line methods, <= 5 args, mypy, pylint >= 9.0 (pre-existing warnings stay), coverage >= 85%; `poe format` first. Branch `feat/icon-thumbnail-cache` from `main`. Never push or open a PR without asking.

## Review Focus

- A corrupt, truncated or zero-byte cached PNG: miss, file removed, thumbnail re-fetched, no crash. (Task 2)
- A read-only or missing cache directory (including `OSError` on write): thumbnails still display from memory, no crash, no repeated error spam. (Task 2)
- Hostile pack ids / versions / icon paths (`..`, `/`, absolute, NUL, 5000 characters): files stay inside the cache root. (Task 2)
- Plugin update: new version used, the old version's directory removed; uninstalled pack pruned; same version keeps its files. (Task 2)
- An older server without `plugin_version`: browser and `IconEdit` still work (memory only, no disk files). (Tasks 3, 4)

---

### Task 1: `plugin_version` in the pack list

**Files:**
- Modify: `src/decker/asset/iconpack.py` (`_Pack`, `register`, `list_packs`)
- Test: `tests/asset/test_iconpack.py`

**Interfaces:**
- Produces: every `IconPackRegistry.list_packs()` entry gains `"plugin_version": str` (the manifest `version`), next to `plugin_id` and `plugin_name`.

- [ ] **Step 1: Branch** `git switch -c feat/icon-thumbnail-cache main`; commit the design doc and this plan first (`git add docs/superpowers/specs/2026-11-17-icon-thumbnail-cache-design.md docs/superpowers/plans/2026-11-17-icon-thumbnail-cache.md && git commit -m "docs: icon thumbnail cache design and plan"`).
- [ ] **Step 2: Failing tests** — update `test_list_icons_finds_images` to expect `"plugin_version": "1.0.0"` in the entry, and add `test_plugin_version_follows_the_manifest` (register a plugin whose manifest version is `"2.3.4"`; the entry says `2.3.4`).
- [ ] **Step 3: Run** `poetry run pytest tests/asset/test_iconpack.py -q` — Expected: FAIL.
- [ ] **Step 4: Implement** `_Pack.plugin_version` (from `plugin.manifest.version`) and add it to the `list_packs` entries. `tests/server/test_service.py` mocks the registry, so it needs no change.
- [ ] **Step 5: Run** `poetry run pytest tests/asset tests/server/test_service.py -q` — Expected: PASS.
- [ ] **Step 6: Commit** `feat(server): icon pack list reports the plugin version`.

### Task 2: `IconThumbnailCache`

**Files:**
- Create: `src/decker/client/icon_cache.py`, `tests/client/test_icon_cache.py`
- Modify: `src/decker/common/paths.py` (`icon_cache()`), `tests/common/test_paths.py`

**Interfaces:**
- Produces:
  - `paths.icon_cache() -> Path` = `home() / "cache" / "icons"`.
  - `IconThumbnailCache(root: Path | None = None, max_memory: int = 2048)`; `root=None` means `paths.icon_cache()` evaluated lazily at first use (so `--prefix` set later still applies).
  - `update_packs(packs: Iterable[Mapping[str, Any]]) -> None` — records `id -> plugin_version` for entries that have a non-empty `plugin_version`; deletes `<root>/<pack>` directories of packs not in `packs` and, for each listed pack, every version directory other than its current one; drops memory entries of removed versions. Never raises.
  - `version_of(pack_id: str) -> str | None`
  - `get(pack_id: str, path: str, size: int, tint: str | None) -> QPixmap | None` — memory, then disk; None when the pack's version is unknown or on a miss; a disk hit is promoted to memory.
  - `put(pack_id: str, path: str, size: int, tint: str | None, pixmap: QPixmap) -> None` — memory always (when the version is known), disk atomically; never raises.
  - `icon_cache() -> IconThumbnailCache` module function returning the process-wide instance (created on first call).

- [ ] **Step 1: Failing tests** (`tmp_path` roots, `qapp` fixture): `test_paths_icon_cache_is_under_home` (in `test_paths.py`, honours `configure(prefix)`), `test_get_misses_when_the_version_is_unknown`, `test_put_then_get_hits_memory_and_disk` (a second cache instance on the same root finds the PNG), `test_key_includes_size_and_tint` (same icon at 24 vs 64 px, and two tints, are separate entries), `test_disk_layout_matches_the_spec` (file at `<root>/<pack>/<version>/64-ffffff/<32 hex>.png`), `test_corrupt_png_is_a_miss_and_is_deleted`, `test_zero_byte_png_is_a_miss`, `test_unwritable_root_does_not_raise_and_memory_still_works` (root under a read-only directory or a path that is a file), `test_hostile_names_stay_inside_the_root` (pack `"../../x"`, version `"/abs"`, path with `".."`, NUL, 5000 chars; assert every created file is below `root`), `test_version_change_deletes_the_old_version_directory`, `test_same_version_keeps_files`, `test_uninstalled_pack_is_pruned`, `test_update_packs_without_plugin_version_means_memory_only` (no files created), `test_memory_lru_evicts_the_oldest` (`max_memory=2`), `test_prune_failure_does_not_raise` (monkeypatch `shutil.rmtree` to raise `OSError`), `test_default_root_follows_the_configured_prefix`, `test_process_wide_instance_is_shared`.
- [ ] **Step 2: Run** `poetry run pytest tests/client/test_icon_cache.py tests/common/test_paths.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `paths.icon_cache()` and the module. Use an `OrderedDict` LRU; `_slug(value)` as in Global Constraints; PNG read with `QPixmap(str(file))` (null → delete + miss), write with `pixmap.save(str(tmp), "PNG")` then `os.replace`; wrap disk operations in `try/except OSError` (log at `debug` once per failure kind, not per icon).
- [ ] **Step 4: Run** the same command — Expected: PASS.
- [ ] **Step 5: Commit** `feat(client): two-level icon thumbnail cache`.

### Task 3: Icon browser uses the cache

**Files:**
- Modify: `src/decker/client/icon_picker.py` (`IconBrowserDialog.__init__`, `_populate_packs`, `_pixmap_for`, `_load_next_icon`)
- Test: `tests/client/test_icon_picker.py`

**Interfaces:**
- Consumes: `IconThumbnailCache` (Task 2), `plugin_version` in `iconpacks_list` (Task 1).
- Produces: `IconBrowserDialog(parent, connection_manager, tint=None, cache: IconThumbnailCache | None = None)` — `cache=None` uses `icon_cache()`. After the pack list loads it calls `cache.update_packs(packs)`. `_pixmap_for`: dialog dict hit → pixmap; else `cache.get(pack, name, 64, tint)` hit → store in the dict and return it (no RPC); else the existing queue. `_load_next_icon` calls `cache.put(...)` only for icons that decoded successfully (never for the letter-tile fallback).

- [ ] **Step 1: Failing tests** (inject `IconThumbnailCache(tmp_path)`; the fake connection manager's pack entries gain `"plugin_version": "1.0.0"`): `test_second_dialog_shows_cached_thumbnails_without_any_icon_rpc` (open, request rows, drain; open a second dialog on the same cache: requesting the same rows makes zero `iconpack_icon` calls and returns real pixmaps at once), `test_cache_hit_survives_a_new_process` (new `IconThumbnailCache` on the same root), `test_plugin_update_refetches_and_replaces_the_cache` (list now says `"2.0.0"`: icons are requested again; the `1.0.0` directory is gone), `test_unreadable_icon_is_not_cached` (RPC returns garbage: no PNG written), `test_different_tint_is_a_different_cache_entry`, `test_server_without_plugin_version_works_memory_only` (entries lack the field: thumbnails load, no files under the cache root), `test_cache_failure_does_not_break_the_browser` (cache whose `get`/`put` raise `OSError`: browser still loads thumbnails via RPC).
- [ ] **Step 2: Run** `poetry run pytest tests/client/test_icon_picker.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement**; wrap cache calls so an unexpected exception from the cache is logged and treated as a miss.
- [ ] **Step 4: Run** `poetry run pytest tests/client -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(client): icon browser thumbnails come from the cache`.

### Task 4: `IconEdit` preview uses the cache

**Files:**
- Modify: `src/decker/client/widgets/icon_edit.py` (`__init__`, `_preview_pixmap`, new `_ensure_versions`)
- Test: `tests/client/widgets/test_icon_edit.py`

**Interfaces:**
- Consumes: `IconThumbnailCache` (Task 2).
- Produces: `IconEdit(rpc=None, parent=None, cache: IconThumbnailCache | None = None)`. In `_preview_pixmap`: `cache.get(pack, path, 24, color)` hit → use it with no RPC. On a miss with an unknown pack version, call `iconpacks_list` once per `IconEdit` (flag) and `cache.update_packs(...)`; then fetch/decode/scale as today and `cache.put(...)` only when decoding succeeded.

- [ ] **Step 1: Failing tests** (fake rpc also answers `iconpacks_list` with `plugin_version`; inject `IconThumbnailCache(tmp_path)`): `test_cached_preview_makes_no_icon_rpc`, `test_first_preview_lists_packs_once_then_caches`, `test_second_edit_with_the_same_icon_hits_the_cache`, `test_colour_change_uses_a_separate_cache_entry_without_refetching_the_icon` (the existing `_raw` memory path still works), `test_older_server_without_plugin_version_still_previews` (no files written), `test_failed_pack_list_does_not_break_the_preview`.
- [ ] **Step 2: Run** `poetry run pytest tests/client/widgets/test_icon_edit.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `poetry run pytest tests/client -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(client): IconEdit preview uses the thumbnail cache`.

### Task 5: Gates and measurement

**Files:** none new.

- [ ] **Step 1: Run** `poetry run poe format`, `poe mypy`, `poe pylint`, `poe test`. Expected: mypy clean, pylint no new warnings, coverage >= 85%, all green (re-run only for failures outside files this plan touched).
- [ ] **Step 2: Measure** against the real `com.decker.fontawesome` solid pack (a fake rpc over `IconPackRegistry`, as in the earlier offscreen check): time to fill the first 200 thumbnails cold (RPC + render) versus warm (disk) versus hot (memory), with a temp cache root. Report the three numbers and that no file was written outside the temp root.
- [ ] **Step 3: Commit** any formatting fixes: `chore: format`.
