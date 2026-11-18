# User Icon Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users import GIF/JPG/PNG/SVG icons into a "User" icon library via a loopback-gated server RPC and a client import dialog that replaces "Choose file...".

**Architecture:** A new server module `decker.asset.usericons` validates ids, resizes rasters (GIFs frame by frame) and writes to `paths.user_icons()`. `IconPackRegistry` serves the folder as the reserved pack `decker.user`. `DeckerService` exposes `icon_import`, `icon_import_preview`, `icon_import_suggest`. The client picker opens a dialog that talks to those RPCs.

**Tech Stack:** Python 3, Pillow, PyQt6, RPyC, pytest + assertpy.

**Spec:** `docs/superpowers/specs/2026-11-18-user-icon-import-design.md`

## Global Constraints

- Output size is exactly 144x144 RGBA for rasters; `center` = one scale factor, fit inside, transparent padding; `stretch` = independent x/y scale.
- Defaults: `fit="center"`, `interpolation="nearest"`; other interpolations: `bilinear`, `lanczos`.
- Id charset `[a-z0-9_-]`, 1-64 chars; uniqueness is across all extensions; collision returns suggestion `id-2`, `id-3`, ...
- Stored names: `<id>.svg`, `<id>.png`, `<id>.gif`; JPEG and single-frame GIF are saved as PNG; format is detected from content, never from the file name.
- SVG is copied byte for byte; rejected if not XML with `svg` root, or contains DOCTYPE/ENTITY, `<script>`, `<foreignObject>`, `on*=` attributes, or `href`/`xlink:href` not starting with `#` or `data:image/`.
- Upload cap `MAX_ICON_BYTES` (4 MiB, `decker.plugin.icons`); GIF limits from `decker.animation.gif` (`MAX_GIF_FRAMES`, `MAX_GIF_PIXELS`, `MAX_RASTER_PIXELS`).
- Import RPC is loopback-gated via `_install_allowed()` (`PermissionError(_REMOTE_INSTALL_DENIED)`); `icon_import_suggest` and `icon_import_preview` are not gated and write nothing.
- Reserved pack id: exactly `decker.user`; plugins may not register it.
- Project rules: annotate everything, methods < 50 lines, max 5 args, docstrings on public items only, black 120. Gates before done: `poe format`, `poe mypy`, `poe pylint` (>= 9.0), `poe test` (coverage >= 85%).
- Tests use pytest + assertpy, mirror `src/` layout under `tests/`, avoid mocks of real infrastructure (use `tmp_path`).

## Review Focus

- A name like `../../etc/x`, `Ünïcode Cat!`, `   `, or 200 characters long: normalised or refused, never escapes `user-icons` (Task 2).
- Two concurrent imports of the same id: exactly one wins, the other is refused with a suggestion (Task 4).
- SVG with an entity-expansion DOCTYPE ("billion laughs"), or `<svg onload=...>`: refused, nothing written (Task 4).
- Bytes that are not an image, a file named `.png` that is really a GIF, a corrupt GIF, or an upload over the cap: refused with a reason, nothing written (Task 4).
- A GIF with transparency, odd canvas size (e.g. 1x300, 500x7), variable frame delays, and a loop count: output keeps them and stays 144x144 (Task 3).

---

### Task 1: Let `decode_gif` take a per-frame transform

**Files:**
- Modify: `src/decker/animation/gif.py` (`decode_gif`, `_shrink`)
- Test: `tests/animation/test_gif.py` (add; check the file exists, else create)

**Interfaces:**
- Produces: `decode_gif(data: bytes, transform: Callable[[Image.Image], Image.Image] | None = None) -> list[GifFrame]`. `transform` receives each composited full-canvas RGBA frame and returns the stored frame; `None` keeps today's behaviour (`_shrink`). The per-frame pixel and total budget checks still run on the source canvas.

- [ ] **Step 1: Write failing test** `test_decode_gif_applies_the_transform_to_each_full_size_frame`: build a 3-frame 300x200 GIF with Pillow (durations 50/120/80), call `decode_gif(data, transform=lambda im: im.resize((10, 10)))`, assert 3 frames, every `frame.image.size == (10, 10)`, delays `[50, 120, 80]`. Add `test_decode_gif_without_transform_still_shrinks_to_144` asserting the long side is 144 for the same input.
- [ ] **Step 2: Run** `poe test tests/animation/test_gif.py -k transform` — expect FAIL (unexpected keyword).
- [ ] **Step 3: Implement** the optional `transform` parameter in `decode_gif`; default to `_shrink`; the transform input is `frame.convert("RGBA")`.
- [ ] **Step 4: Run** the same tests plus the whole `tests/animation` folder — expect PASS.
- [ ] **Step 5: Commit** `feat: let decode_gif take a per-frame transform`.

---

### Task 2: Ids and the user-icon store

**Files:**
- Create: `src/decker/asset/usericons.py`
- Test: `tests/asset/test_usericons.py`

**Interfaces:**
- Produces in `decker.asset.usericons`:
  - `USER_PACK_ID = "decker.user"`, `USER_PLUGIN_ID = "decker.user"`, `USER_PLUGIN_NAME = "User"`
  - `normalize_id(name: str) -> str` — returns the normalised id or `""` when nothing usable remains
  - `class UserIcons` with `__init__(self, directory: Path | None = None)` (default resolved lazily via `decker.common.paths.user_icons()` on each use so tests can monkeypatch the home), plus:
    - `list_icons() -> list[str]` sorted file names of `.svg/.png/.gif` files
    - `read_icon(name: str) -> bytes | None` (looked up by listing, never joins untrusted names; capped at `MAX_ICON_BYTES`)
    - `pack_info() -> dict[str, Any]` shaped like a plugin pack entry (`id`, `name`="User", `description`, `plugin_id`, `plugin_name`, `plugin_version`="1", `icon_count`)
    - `exists(icon_id: str) -> bool` (any extension)
    - `suggest_id(name: str) -> str` first free `id`, else `id-2`, `id-3`, …; `"icon"` when the name normalises to nothing

- [ ] **Step 1: Write failing tests** (each with `tmp_path`): `test_normalize_id_lowercases_and_replaces_runs_of_other_characters` (`"Ünïcode Cat!"` → `"n-code-cat"`, `"My  Icon.png"` stays name-based by the caller — assert `"My  Icon"` → `"my-icon"`); `test_normalize_id_strips_path_traversal` (`"../../etc/x"` → `"etc-x"`); `test_normalize_id_returns_empty_for_blank_or_symbols_only` (`"   "`, `"!!!"`); `test_normalize_id_truncates_to_64` ; `test_exists_is_true_across_extensions` (write `cat.gif`, `exists("cat")` true); `test_suggest_id_appends_the_first_free_number` (`cat.png`, `cat-2.png` exist → `cat-3`); `test_list_icons_ignores_other_files_and_sorts`; `test_read_icon_refuses_names_outside_the_listing` (`"../x.png"`, `"nope.png"` → None); `test_pack_info_counts_icons_and_lists_when_empty`.
- [ ] **Step 2: Run** `poe test tests/asset/test_usericons.py` — expect FAIL (module missing).
- [ ] **Step 3: Implement** the interfaces above. `normalize_id`: NFKD-decompose and drop non-ASCII marks is NOT required — just lowercase, replace every run of characters outside `[a-z0-9_-]` with `-`, trim `-`/`_` from both ends, cut to 64, trim again.
- [ ] **Step 4: Run** the tests — expect PASS.
- [ ] **Step 5: Commit** `feat: user icon ids and store`.

---

### Task 3: Raster resize (stills and GIFs) and preview

**Files:**
- Create: `src/decker/asset/iconresize.py`
- Test: `tests/asset/test_iconresize.py`

**Interfaces:**
- Consumes: `decode_gif(data, transform=...)` (Task 1), `GifError`, `is_gif`, `is_animated_gif` from `decker.animation.gif`.
- Produces in `decker.asset.iconresize`:
  - `ICON_SIZE = 144`
  - `@dataclass(frozen=True) class ImportOptions: fit: str = "center"; interpolation: str = "nearest"` with `@classmethod from_json(cls, text: str) -> "ImportOptions"` (empty string → defaults; unknown value → `ValueError`)
  - `class ImageImportError(ValueError)`
  - `resize_image(image: Image.Image, options: ImportOptions) -> Image.Image` — 144x144 RGBA
  - `convert_raster(data: bytes, options: ImportOptions) -> tuple[bytes, str]` — returns `(output_bytes, extension)`; extension `"png"` for still PNG/JPEG/single-frame GIF, `"gif"` for animated; detects format from content; raises `ImageImportError` for non-images, corrupt data, over-cap data (size, pixels via `Image.MAX_IMAGE_PIXELS` guard)
  - `preview_png(data: bytes, options: ImportOptions) -> bytes` — PNG of the first frame at 144x144

- [ ] **Step 1: Write failing tests**: `test_center_fit_scales_by_one_factor_and_pads_transparent` (200x100 opaque red → size 144x144, pixel (72,72) red alpha 255, pixel (72,5) alpha 0, red band height 72); `test_stretch_fills_the_square` (200x100 → pixel (0,0) and (143,143) opaque); `test_nearest_keeps_hard_pixel_edges` (2x2 checker of four colours, centre fit → only those four colours + transparent appear); `test_lanczos_blends_edges` (same input has more than 5 distinct colours); `test_options_from_json_defaults_and_rejects_unknown_values`; `test_jpeg_becomes_png`; `test_single_frame_gif_becomes_png`; `test_animated_gif_keeps_frame_count_durations_loop_and_transparency` (3 frames, durations 50/120/80, loop=3, transparent background; output gif: `n_frames == 3`, durations match, `info["loop"] == 3`, size 144x144, a corner pixel transparent); `test_odd_canvas_gifs_stay_144` for 1x300 and 500x7; `test_format_is_detected_from_content_not_name` (GIF bytes handed with png expectation still produce gif/png by content); `test_non_image_bytes_raise_image_import_error`; `test_corrupt_gif_raises_image_import_error`; `test_preview_png_returns_a_144_png`.
- [ ] **Step 2: Run** `poe test tests/asset/test_iconresize.py` — expect FAIL.
- [ ] **Step 3: Implement.** `resize_image`: map options to `Image.Resampling.NEAREST/BILINEAR/LANCZOS`; `center` → compute one scale `s = 144 / max(w, h)`, resize to `(max(1, round(w*s)), max(1, round(h*s)))`, paste on a transparent 144x144 canvas centred; `stretch` → resize straight to 144x144. `convert_raster`: sniff with `Image.open(...).format`; GIFs go through `decode_gif(data, transform=lambda f: resize_image(f, options))` and are saved with `save_all=True, append_images, duration=[...], loop=<source loop or 0>, disposal=2, transparency` handling; read the source loop count from `Image.open(...).info.get("loop", 0)`. Wrap `GifError`, `UnidentifiedImageError`, `OSError`, `DecompressionBombError` into `ImageImportError`.
- [ ] **Step 4: Run** the tests — expect PASS.
- [ ] **Step 5: Commit** `feat: resize imported icons (stills and GIFs)`.

---

### Task 4: Import orchestration, SVG validation, atomic write

**Files:**
- Modify: `src/decker/asset/usericons.py`
- Create: `src/decker/asset/svgcheck.py`
- Test: `tests/asset/test_usericons.py` (extend), `tests/asset/test_svgcheck.py`

**Interfaces:**
- Consumes: `convert_raster`, `ImportOptions`, `ImageImportError` (Task 3); `normalize_id`, `UserIcons` (Task 2).
- Produces:
  - `decker.asset.svgcheck.validate_svg(data: bytes) -> None` raising `ValueError(reason)`
  - `@dataclass(frozen=True) class ImportResult: ok: bool; icon_id: str = ""; file: str = ""; error: str = ""; suggestion: str = ""` with `to_json() -> str` (keys `ok`, `id`, `file`, `error`, `suggestion`)
  - `UserIcons.import_icon(name: str, data: bytes, options: ImportOptions) -> ImportResult` — id from `normalize_id(name)`; empty id → `ok=False, error="invalid name"`; duplicate → `ok=False, error="id already exists", suggestion=<free id>`; over `MAX_ICON_BYTES` → refused; SVG detected by content (XML whose root tag ends with `svg`) → `validate_svg` then copy bytes as `<id>.svg`; otherwise `convert_raster`. The existence check and the write happen under one `threading.Lock`; the write goes to a temp file in the same folder then `os.replace`; the folder is created if missing; nothing is left behind on any refusal.
  - `UserIcons.preview(data: bytes, options: ImportOptions) -> bytes` — SVG: the bytes unchanged after `validate_svg`; else `preview_png`; refusals raise `ImageImportError`/`ValueError`.

- [ ] **Step 1: Write failing tests**: `test_import_png_writes_a_144_png_named_by_id`; `test_import_svg_copies_bytes_unchanged`; `test_import_refuses_a_duplicate_id_and_suggests_the_next` (second `cat` → `error == "id already exists"`, `suggestion == "cat-2"`, only one file on disk); `test_import_refuses_blank_names`; `test_import_refuses_over_cap_and_leaves_no_files`; `test_import_refuses_non_images_and_leaves_no_files`; `test_import_creates_the_folder_when_missing`; `test_concurrent_imports_of_one_id_have_one_winner` (8 threads, same name; exactly one `ok`, the rest `ok=False`; one file); `test_import_leaves_no_temp_files_on_a_failed_write` (make the folder read-only path via a file in its place? simpler: pass bytes that fail conversion and assert `list(dir.iterdir()) == []`). In `test_svgcheck.py`: accepts a plain `<svg xmlns=...><rect/></svg>` and an `<use href="#a"/>`; rejects `<script>`, `<foreignObject>`, `<svg onload="x">`, `<image href="http://x/y.png"/>`, `xlink:href="file:///etc/passwd"`, a DOCTYPE with `<!ENTITY`, a non-svg root, non-XML bytes.
- [ ] **Step 2: Run** `poe test tests/asset/test_usericons.py tests/asset/test_svgcheck.py` — expect FAIL.
- [ ] **Step 3: Implement** `validate_svg` with `xml.etree.ElementTree` after rejecting any `<!DOCTYPE`/`<!ENTITY` in the first bytes of the text (case-insensitive) before parsing; walk all elements checking tag local names and attributes per Global Constraints. Implement `import_icon` and `preview` as described.
- [ ] **Step 4: Run** the tests — expect PASS.
- [ ] **Step 5: Commit** `feat: import user icons with validation and atomic writes`.

---

### Task 5: Serve the User pack and expose the RPCs

**Files:**
- Modify: `src/decker/asset/iconpack.py` (`IconPackRegistry`), `src/decker/server/service.py`, `docs/plugins/` page that describes System Icons (find with `grep -rn "System Icons" docs`)
- Test: `tests/asset/test_iconpack.py`, `tests/server/test_service.py`

**Interfaces:**
- Consumes: `UserIcons`, `USER_PACK_ID`, `USER_PLUGIN_ID`, `USER_PLUGIN_NAME`, `ImportOptions` (Tasks 2-4).
- Produces: `IconPackRegistry.__init__(..., user_icons: UserIcons | None = None)` and public attribute `user_icons: UserIcons`. `list_packs()` appends `user_icons.pack_info()` (always, even empty) after the plugin packs and before the system packs; `list_icons`/`read_icon` route `decker.user` to it; `register()` refuses a plugin pack whose id equals `decker.user` using the same failure path as the reserved system prefix. Service RPCs (all `@exposed`):
  - `icon_import(self, name: str, filename: str, data: bytes, options: str) -> str` — calls `_install_allowed()` first (raise `PermissionError(_REMOTE_INSTALL_DENIED)`), returns `ImportResult.to_json()`; `filename` is only used to pre-fill the name when `name` is blank
  - `icon_import_suggest(self, name: str) -> str`
  - `icon_import_preview(self, filename: str, data: bytes, options: str) -> str` — base64 PNG, or `""` when refused
  - `icon_import_allowed` is NOT added; the client reuses `plugin_install_allowed`.

- [ ] **Step 1: Write failing tests**: in `test_iconpack.py` `test_user_pack_is_listed_even_when_empty`, `test_user_pack_icons_are_served_by_name`, `test_a_plugin_cannot_register_the_user_pack_id`; in `test_service.py` (follow the file's existing fixtures for a service with a context and `_peer_host`) `test_icon_import_stores_and_lists_the_icon_in_the_user_pack`, `test_icon_import_is_refused_for_remote_clients`, `test_icon_import_reports_a_duplicate_with_a_suggestion`, `test_icon_import_suggest_returns_a_free_id`, `test_icon_import_preview_works_for_remote_clients_and_writes_nothing`.
- [ ] **Step 2: Run** those tests — expect FAIL.
- [ ] **Step 3: Implement** registry changes and the three RPCs (docstrings as the surrounding RPCs do, since `commands()` lists them). Add a short "User library" paragraph to the docs page found above. Note the import RPC in `CLAUDE.md`'s loopback-gated list (`plugin_install`/… sentence) in one clause.
- [ ] **Step 4: Run** `poe test tests/asset tests/server` — expect PASS, including `test_protocol_conformance.py`.
- [ ] **Step 5: Commit** `feat: serve the User icon pack and add import RPCs`.

---

### Task 6: Client import dialog replaces "Choose file..."

**Files:**
- Create: `src/decker/client/icon_import_dialog.py`
- Modify: `src/decker/client/icon_picker.py` (remove `copy_to_user_icons`, `_choose_file` rewired, drop now-unused imports)
- Test: `tests/client/test_icon_import_dialog.py`, `tests/client/test_icon_picker.py`

**Interfaces:**
- Consumes: `RpcCaller` protocol from `icon_picker.py` (`call(method, *args)`), RPCs `icon_import`, `icon_import_suggest`, `icon_import_preview`, `plugin_install_allowed`.
- Produces: `class IconImportDialog(QDialog)` with `__init__(self, parent: QWidget | None, connection_manager: RpcCaller, path: Path)` and signal `imported = pyqtSignal(str)` carrying the stored file name (e.g. `cat.png`). Controls: id line edit (prefilled with `suggest` of the file's stem), fit combo (Center/Stretch), interpolation combo (Nearest/Bilinear/Lanczos), preview label (server-rendered, refreshed on option change, debounced), Import button, error label. For SVG paths (`.svg`) the fit/interpolation rows are hidden. A duplicate result shows `error` and a "Use <suggestion>" button that fills the id field. `IconPickerWidget._choose_file` opens the file dialog (filter without `*.webp`: `*.svg *.png *.jpg *.jpeg *.gif`), then the dialog; on `imported` it emits `pack_icon_selected("decker.user", <file>)`. If `plugin_install_allowed` is false, the button shows an information message saying importing needs a local connection and does nothing else.

- [ ] **Step 1: Write failing tests** using a fake `RpcCaller` class recording calls (infrastructure-free, as `test_icon_picker.py` does): `test_dialog_prefills_the_id_from_the_suggestion`; `test_import_sends_id_bytes_and_options_and_emits_imported`; `test_duplicate_shows_error_and_use_suggestion_fills_the_id`; `test_svg_hides_fit_and_interpolation`; `test_options_change_refreshes_the_preview`; in `test_icon_picker.py` replace the `copy_to_user_icons` tests with `test_choose_file_opens_the_import_dialog_and_emits_the_pack_icon` and `test_choose_file_explains_when_import_is_not_allowed`.
- [ ] **Step 2: Run** `poe test tests/client/test_icon_import_dialog.py tests/client/test_icon_picker.py` — expect FAIL.
- [ ] **Step 3: Implement** the dialog and rewire the picker. Keep `_IMAGE_FILE_FILTER` in sync. Preview RPC failures show a neutral placeholder, not an exception.
- [ ] **Step 4: Run** `poe test tests/client` — expect PASS.
- [ ] **Step 5: Commit** `feat: import dialog replaces the local file copy`.

---

### Task 7: Quality gates and a live check

**Files:** none new.

- [ ] **Step 1:** `poe format`, then `poe mypy`, `poe pylint` (>= 9.0), `poe test` (>= 85% coverage). Fix findings in the owning task's files.
- [ ] **Step 2:** Run the app with `poe server` and `poe client`; import a PNG, an animated GIF and an SVG, pick each on a key, confirm the duplicate-name suggestion; use the `run` skill if available. Report anything not verified.
- [ ] **Step 3: Commit** any fixes `chore: quality gate fixes for user icon import`.
