# System icons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve the system's freedesktop icon theme as built-in virtual icon packs (`decker.system.<category>`) so the icon library shows a "System Icons" section with Actions, Applications, Categories, Devices, Emblems, Emotes, Mimetypes, Places, Status and Other.

**Architecture:** A pure-Python `SystemIcons` (index of the active theme + inheritance chain) composed into `IconPackRegistry`, which already backs the `iconpacks_list` / `iconpack_icons` / `iconpack_icon` RPCs, `read_ref` and plugin `set_icon`. The picker already renders any pack tree, so the client needs only display-name handling for dotted icon names.

**Tech Stack:** Python 3.14 (`configparser`, `os.scandir`), PyQt6 (offscreen tests), RPyC, pytest + assertpy, poe gates.

**Spec:** `docs/superpowers/specs/2026-11-18-system-icons-design.md`

## Global Constraints

- Gates after every task: `poe format`, `poe mypy`, `poe pylint` (>= 9.0), `poe test` (coverage >= 85%). Task tests first, whole suite at task end.
- Pack ids: `decker.system.<key>` with keys, labels and order exactly: `actions` Actions, `applications` Applications, `categories` Categories, `devices` Devices, `emblems` Emblems, `emotes` Emotes, `mimetypes` Mimetypes, `places` Places, `status` Status, `other` Other. `plugin_id = "decker.system"`, `plugin_name = "System Icons"`. A pack with no icons is not listed. Plugin packs may not use ids starting with `decker.system.`.
- Context mapping (case-insensitive, from a directory's `Context=`): actions, applications, categories, devices, emblems, emotes, `mimetypes` (also spelled `MimeTypes`), places, status; everything else (Animations, Panel, Stock, Legacy, unknown) and a missing context → `other`.
- Icon name = the file name minus one trailing image suffix (`.svg .png .jpg .jpeg`, case-insensitive); refs are `pack:decker.system.<key>/<name>` and store the name only.
- File choice per name: a `Type=Scalable` (or `scalable`) SVG first, else the largest `Size`; the primary theme beats inherited themes, which beat `hicolor`. Served only if the resolved file has an image suffix and is <= `MAX_ICON_BYTES` (`decker.plugin.icons`).
- Theme: `icons.system_theme` config key (default `""` in `defaults.yml`), else GTK `~/.config/gtk-3.0/settings.ini` `[Settings] gtk-icon-theme-name`, else KDE `~/.config/kdeglobals` `[Icons] Theme`, else `Adwaita` if installed, else `hicolor`. Search dirs: `$XDG_DATA_HOME/icons` (default `~/.local/share/icons`), `~/.icons`, then `<dir>/icons` for each of `$XDG_DATA_DIRS` (default `/usr/local/share:/usr/share`).
- Version string = `<theme>-<8 hex of a hash over the (path, mtime_ns) of every index.theme in the chain>`; the index is rebuilt when it changes. Builds happen outside the read lock; a separate build lock keeps two clients from building at once.
- Commit trailers: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01FG9NRh1jMLQUSqz1T3VCXN`. **Stage explicit file paths only** (the user keeps untracked files in `src/decker/assets/`; never `git add` a directory). Never push or open PRs without the user's go-ahead.

## Review Focus

- Hostile names through the RPC: `..`, absolute paths, names with `/`, empty, very long, non-str: none returns bytes of a file outside the index.
- A symlink inside a theme pointing at a non-image or oversized file is refused; a broken symlink or unreadable directory never breaks listing.
- First use on a large theme (Papirus has tens of thousands of files) stays reasonable and two concurrent callers do not both rebuild or deadlock; a theme removed after startup yields empty packs, not exceptions.
- Theme precedence: an icon in the primary theme beats the same name in an inherited theme; a name that exists only in `hicolor` is still served; Mimetypes vs "Other" mapping for odd `Context` values.
- Dotted icon names (`org.gnome.Foo`) keep their full name in refs, search and labels.

---

## Task 1: Theme discovery and index

**Files:**
- Create: `src/decker/asset/systemicons.py` (this task: constants, `category_of`, `icon_search_dirs`, `detect_theme`, `ThemeIndex`/`build_index`)
- Test: `tests/asset/test_systemicons.py`

**Interfaces:**
- Produces:
  - `CATEGORIES: tuple[tuple[str, str], ...]` (key, label) in the order of Global Constraints; `PACK_PREFIX = "decker.system."`, `SYSTEM_PLUGIN_ID = "decker.system"`, `SYSTEM_PLUGIN_NAME = "System Icons"`.
  - `category_of(context: str | None) -> str` (the pack key).
  - `icon_search_dirs(env: Mapping[str, str], home: Path) -> list[Path]` (existing and non-existing dirs in lookup order; callers check existence).
  - `detect_theme(configured: str, home: Path, search_dirs: Sequence[Path]) -> str`.
  - `build_index(theme: str, search_dirs: Sequence[Path]) -> ThemeIndex` where `ThemeIndex` is a frozen dataclass with `theme: str`, `version: str`, `icons: Mapping[str, Mapping[str, Path]]` (category key → icon name → chosen file). Unreadable themes/directories are skipped, never raised.
- Consumes: nothing.

- [ ] **Step 1: Write the failing tests** against a fake tree under `tmp_path` (helper `make_theme(root, name, inherits, dirs)` writing an `index.theme` and files):
  - `test_category_of_maps_contexts_case_insensitively`: `Actions`→`actions`, `MimeTypes`/`mimetypes`→`mimetypes`, `Animations`, `Panel`, `Stock`, `""`, `None`, `"Whatever"` → `other`.
  - `test_search_dirs_follow_xdg_with_defaults` and with `XDG_DATA_HOME`/`XDG_DATA_DIRS` set.
  - `test_detect_theme_prefers_config_then_gtk_then_kde_then_adwaita_then_hicolor`: each source alone and in priority order; a configured/GTK/KDE theme that is not installed is skipped for the next source; whitespace and quotes in `settings.ini` values are stripped.
  - `test_index_groups_files_by_context_and_names_without_extension`: two directories with different contexts, `edit-copy.svg`, `org.gnome.Foo.png` (name keeps its dots), uppercase `.SVG` accepted, a `.txt` ignored.
  - `test_scalable_beats_larger_raster_and_larger_raster_beats_smaller`.
  - `test_primary_theme_beats_inherited_beats_hicolor_and_hicolor_only_names_are_found`.
  - `test_missing_context_and_unknown_context_go_to_other`.
  - `test_unreadable_or_missing_theme_gives_an_empty_index`; `test_inherits_cycles_do_not_loop`.
  - `test_version_changes_when_an_index_theme_mtime_changes` (`os.utime`) and is `<theme>-<8 hex>`.
- [ ] **Step 2: Run** `poetry run pytest tests/asset/test_systemicons.py -q` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement** with `configparser.ConfigParser(interpolation=None, strict=False)` for `index.theme`, `settings.ini` and `kdeglobals`; walk each theme's `Directories=` (and `ScaledDirectories=` ignored) section by section with `os.scandir`; a theme's chain is itself + `Inherits` (breadth-first, visited set) + `hicolor`; first writer wins per (category, name) in chain order, then per size preference inside a theme.
- [ ] **Step 4: Run** the file — Expected: PASS. Then `poetry run pytest tests/asset -q`.
- [ ] **Step 5: Commit** `feat: freedesktop icon theme discovery and index` (explicit paths).

## Task 2: `SystemIcons` serving API

**Files:**
- Modify: `src/decker/asset/systemicons.py`
- Test: `tests/asset/test_systemicons.py`

**Interfaces:**
- Consumes: Task 1.
- Produces `SystemIcons(search_dirs: Sequence[Path] | None = None, home: Path | None = None, configured_theme: Callable[[], str] | None = None)` with: `theme_name() -> str`; `version() -> str`; `owns(pack_id: str) -> bool` (True only for the ten known ids); `list_packs() -> list[dict[str, Any]]` (entries shaped like `IconPackRegistry.list_packs`: `id`, `name` (label), `description` (`"System icons: <label>"`), `plugin_id`, `plugin_name`, `plugin_version` (= `version()`), `icon_count`; only non-empty categories, in `CATEGORIES` order); `list_icons(pack_id: str) -> list[str]` (sorted names, `[]` for unknown packs); `read_icon(pack_id: str, name: Any) -> bytes | None`.
  Defaults: `search_dirs` from `icon_search_dirs(os.environ, Path.home())`; `configured_theme` reads `decker.common.config.get_or_default("icons.system_theme", "")`.

- [ ] **Step 1: Write the failing tests** (fake tree fixture): `list_packs` shape/order/omits empty categories/`icon_count`; `list_icons` sorted and unknown pack → `[]`; `read_icon` returns the chosen file's bytes (scalable over raster) and `None` for unknown name, wrong category, non-str names (`None`, `5`, `b"x"`), empty, `..`, `../x`, `/etc/passwd`, `a/b`, a 5,000-character name; `read_icon` refuses a symlink whose target has no image suffix and a file over `MAX_ICON_BYTES` (monkeypatch the constant small) and survives a broken symlink; the index is built once for repeated calls (count `build_index` via monkeypatch) and rebuilt after an `index.theme` mtime change; two threads calling first-time `list_icons` together trigger exactly one build; a theme that disappears after the first call yields empty packs without raising; `owns` is exact (`decker.system.actions` yes, `decker.system.nope`, `com.x`, `decker.system.` no).
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.** Snapshot pattern: `_snapshot()` computes the cheap fingerprint (`version` of the current theme: stat the chain's `index.theme` files), compares it with the cached `ThemeIndex.version`, and if different takes `self._build_lock`, re-checks, runs `build_index` (no other lock held) and stores the result under `self._lock`. `read_icon` looks the name up in the category dict (never joins the name to a path), resolves the stored path, checks suffix and size, reads bytes; any `OSError` → `None` with a debug log.
- [ ] **Step 4: Run** the file and `poetry run pytest tests/asset -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: SystemIcons serves the system icon theme as virtual packs`.

## Task 3: Registry integration, config and RPC

**Files:**
- Modify: `src/decker/asset/iconpack.py`, `src/decker/common/config/defaults.yml`
- Test: `tests/asset/test_iconpack.py`, `tests/server/test_service.py`, `tests/common/test_config*.py` (if a defaults test exists)

**Interfaces:**
- Consumes: Task 2.
- Produces: `IconPackRegistry(on_failure=None, system_icons: SystemIcons | None = None)` (default `SystemIcons()`); `list_packs()` returns plugin packs (sorted by name as today) followed by `system_icons.list_packs()`; `list_icons`/`read_icon` delegate when `system_icons.owns(pack_id)`; `register` refuses a plugin pack whose id starts with `PACK_PREFIX` through `on_failure` ("reserved icon pack id"); `read_ref` works unchanged for `pack:decker.system.<key>/<name>`. `defaults.yml` gains `icons: system_theme: ""` (match the file's existing nesting style).

- [ ] **Step 1: Write the failing tests:** registry with a fake `SystemIcons` (or the fake-tree one): `list_packs` contains the system packs after plugin packs with `plugin_name == "System Icons"`; `list_icons("decker.system.actions")` and `read_icon(...)` delegate; `read_ref("pack:decker.system.actions/edit-copy")` returns bytes and an unknown name returns None; a plugin manifest with a pack id `decker.system.actions` is refused and reported, not registered; unregister of a plugin leaves system packs; existing plugin-pack tests unchanged. Service: `iconpacks_list`, `iconpack_icons("decker.system.actions")` and `iconpack_icon(...)` return the expected JSON/base64 from a registry built over the fake tree (use `PluginManager.icon_packs` replaced in the context, as other service tests inject fakes). Config: `get("icons.system_theme")` is `""` by default.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** the delegation (keep `read_icon`'s plugin-path checks untouched for non-system ids) and the config default.
- [ ] **Step 4: Run** `poetry run pytest tests/asset tests/server tests/common -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: system icon packs in the icon registry`.

## Task 4: Picker display names and tree

**Files:**
- Modify: `src/decker/common/icon_ref.py` (add `icon_display_name`), `src/decker/client/icon_picker.py`, `src/decker/client/widgets/icon_edit.py` (and any other `Path(...).stem` used for an icon's shown or searched name: `grep -rn "\.stem" src/decker/client`)
- Test: `tests/common/test_icon_ref.py`, `tests/client/test_icon_picker.py`, `tests/client/widgets/test_icon_edit.py`

**Interfaces:**
- Produces `icon_display_name(path: str) -> str`: the last path segment with one trailing image suffix (`.svg .png .jpg .jpeg`, case-insensitive) removed; names without such a suffix (system icons) are returned whole, dots included.
- Consumes: Task 3 (the pack tree needs no code change; this task proves it).

- [ ] **Step 1: Write the failing tests:** `icon_display_name("solid/house.svg") == "house"`, `("org.gnome.Foo") == "org.gnome.Foo"`, `("a/b/Icon.PNG") == "Icon"`, `("x.tar.svg") == "x.tar"`, `("") == ""`. Picker with a fake RPC returning plugin packs plus the system packs (`plugin_id "decker.system"`, `plugin_name "System Icons"`, ten ids): the tree has a top-level "System Icons" with the listed children in order (empty ones absent), selecting a child lists only its icons, search matches a dotted name by its full text (`"gnome.foo"` finds `org.gnome.Foo`), "All icons" includes system packs. IconEdit shows `org.gnome.Foo` (not `org.gnome`) for a system ref.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** `icon_display_name` and use it wherever the picker model, search filter and `IconEdit` derive a visible name.
- [ ] **Step 4: Run** `poetry run pytest tests/client tests/common -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: show system icon names whole in the picker`.

## Task 5: Docs and whole-suite gates

**Files:**
- Modify: `CLAUDE.md` (the System Icons packs exist, served from the server's freedesktop theme, `icons.system_theme`), `docs/plugins/protocol.md` and `docs/plugins/sdk-quickstart.md` (`set_icon` accepts `pack:decker.system.<category>/<name>` refs, `decker.system.` pack ids are reserved).
- [ ] **Step 1:** update the docs. **Step 2:** `poe format`, `poe mypy`, `poe pylint`, `poe test` — Expected: all green, coverage >= 85%. **Step 3: Commit** `docs: system icons`.
