# Bundled DejaVu Family, SDK Font Helper and Plugin Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decker bundles the full DejaVu family and hands plugins a font through the SDK; Counter uses it on every OS; the plugins repo CI runs on Linux, Windows and macOS and its support table is filled from evidence.

**Architecture:** Decker (`/work/decker/decker`, branch `feat/bundled-dejavu-sdk-fonts`) gets 19 more font files, folder-based Qt registration, a bundled-font index in the server's font lookup, `DECKER_FONT_DIR` in `launch_env` and `decker_plugin_sdk.fonts.font_path`. The plugins repo (`/work/decker/decker-plugins`, new branch from `main`) then switches Counter to the helper, adds a CI matrix and fills `docs/platform-support.md`.

**Tech Stack:** Python 3.14, Pillow, PyQt6, pytest + assertpy, GitHub Actions, uv (plugins repo).

**Spec:** `docs/superpowers/specs/2026-11-19-bundled-fonts-and-plugin-audit-design.md` (in the Decker repo).

## Global Constraints

- Fonts: the DejaVu 2.37 TrueType files installed at `/usr/share/fonts/TTF/` on this machine (`DejaVuSans{,-Bold,-Oblique,-BoldOblique,-ExtraLight}.ttf`, `DejaVuSansCondensed{,-Bold,-Oblique,-BoldOblique}.ttf`, `DejaVuSansMono{,-Bold,-Oblique,-BoldOblique}.ttf`, `DejaVuSerif{,-Bold,-Italic,-BoldItalic}.ttf`, `DejaVuSerifCondensed{,-Bold,-Italic,-BoldItalic}.ttf`) = 21 files in `src/decker/assets/fonts/` (two already there; do NOT bundle `DejaVuMathTeXGyre.ttf`). Keep `LICENSE-DejaVu.txt`. Existing constants `BUNDLED_REGULAR`/`BUNDLED_BOLD` keep working.
- `decker_plugin_sdk.fonts.font_path(family: str = "DejaVu Sans", bold: bool = False, italic: bool = False) -> str | None`: families `DejaVu Sans`, `DejaVu Sans Condensed`, `DejaVu Sans Mono`, `DejaVu Serif`, `DejaVu Serif Condensed` (case-insensitive); the mapping from (family, bold, italic) to file name is a data table (Serif's italic faces are `-Italic`, the others `-Oblique`); returns the absolute path string, or `None` when `DECKER_FONT_DIR` is unset, the family is unknown, or the file does not exist. Never raises. The SDK stays dependency-free (stdlib only).
- `launch_env` (`src/decker/plugin/runtime/launcher.py`) adds `DECKER_FONT_DIR` = absolute path of the bundled fonts folder on every OS.
- Server lookup (`src/decker/server/fonts.py`): a request for a bundled DejaVu family must never resolve to a non-DejaVu face when the bundled file exists (fontconfig answers every query with some fallback font, so an unknown-to-the-OS family such as `DejaVu Serif Condensed` must still reach the bundled file); other families keep today's order (fc-match, OS index, bundled DejaVu Sans). The client registers every `*.ttf` in the bundled folder with Qt.
- Counter (plugins repo): `from decker_plugin_sdk.fonts import font_path` inside a try/except ImportError, `font_path(bold=True)`; `None` or an unopenable file falls back to `ImageFont.load_default(size)`; `fc-match`, `subprocess` and the Arch font path are deleted; manifest version `1.1.0`.
- Plugins CI: matrix `ubuntu-latest`, `windows-latest`, `macos-latest` (`fail-fast: false`) for the plugin and tool test steps only; lint, version check and pack stay on Linux; add `workflow_dispatch`.
- Support table (plugins repo `docs/platform-support.md`): add a `CI` legend entry (verified by the matrix); the four pure plugins and Counter get `CI` on Windows and macOS only where the runs show their tests passing; the Ubuntu/Debian/Fedora/GNOME cells get `CI` for what the tests cover; Linux Arch and Linux other cells stay `Not verified`; footnotes say what CI does not cover (no real Stream Deck, no real Decker UI). Do NOT add `platforms` to any manifest.
- Project rules (both repos' conventions): Decker: annotate everything, methods < 50 lines, max 5 args, docstrings on public items only, black 120; gates `poe format`, `poe mypy` (+ `poetry run mypy --platform win32 .` and `--platform darwin .`), `poe pylint` (>= 9.0), `poe test` (coverage >= 85%; never run `tests/client` blindly, it can hang, run specific client test files); tests use pytest + assertpy and mirror `src/`; skips use registered markers with a reason naming the feature and its `docs/platform-support.md` row. Plugins repo: `uv run ruff check .`, `uv run pytest`.
- Every commit message: subject, a BLANK LINE, then the trailer lines `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01FG9NRj5PgFFP8CrgR6aMLZ`.
- The maintainer approved pushing work branches to GitHub for CI verification (`gh workflow run ci.yml --ref <branch>`, `gh run list/watch/view`): Decker branch `feat/bundled-dejavu-sdk-fonts`, plugins branch `feat/counter-font-and-ci-matrix`. HTTPS with the gh token, never print it. No PRs in this plan.

## Review Focus

- `font_path` with the variable unset, an unknown family, a missing file, or a Windows-style path never raises and returns `None` or a real file (Task 3).
- A bundled family the OS lacks resolves to the bundled file even where `fc-match` returns a fallback (Task 2).
- The new fonts are inside the built package (not just the git tree) and the client registers all of them (Tasks 1, 4).
- Counter renders a non-empty PNG both with the helper and when the SDK has no `fonts` module or returns `None` (Task 5).
- CI really ran the plugin tests on Windows and macOS (not skipped or filtered out) (Task 6).

---

### Task 1: Bundle the family and register it with Qt

**Files:**
- Add: the 19 missing font files under `src/decker/assets/fonts/` (copy from `/usr/share/fonts/TTF/`)
- Modify: `src/decker/client/fonts.py`, `tests/client/test_client_fonts.py`; check `pyproject.toml` includes the assets in the built package

**Interfaces:**
- Produces: `register_bundled_fonts()` registers every `*.ttf` in the folder (sorted, same return contract); a module-level `BUNDLED_FONT_DIR: Path` in `decker.server.fonts` (the existing `_ASSET_FONTS`, made public, no behaviour change) used by later tasks.

- [ ] **Step 1: Write failing tests** in `tests/client/test_client_fonts.py`: the bundled folder holds exactly the 21 expected file names plus the licence; `register_bundled_fonts()` returns at least the families `DejaVu Sans`, `DejaVu Serif`, `DejaVu Sans Mono` (use the existing offscreen Qt fixture style in that file).
- [ ] **Step 2: Run** `poe test tests/client/test_client_fonts.py` — expect FAIL.
- [ ] **Step 3: Implement**: copy the files (verify with `fc-scan`/size that they are DejaVu 2.37 and the existing licence text covers them; if the licence needs a change, say so in the report), list the folder in `client/fonts.py`, expose `BUNDLED_FONT_DIR`. Run `poetry build` and confirm the wheel lists all 21 fonts and the licence; if `pyproject.toml` excludes them, fix the include.
- [ ] **Step 4: Run** `poe test tests/client/test_client_fonts.py tests/server/test_fonts.py` and the three `mypy` runs — expect PASS.
- [ ] **Step 5: Commit** `feat: bundle the full DejaVu font family`.

---

### Task 2: Resolve bundled DejaVu families on the server

**Files:**
- Modify: `src/decker/server/fonts.py`, `tests/server/test_fonts.py`

**Interfaces:**
- Consumes: `BUNDLED_FONT_DIR`.
- Produces: `font_file`/`font_face` resolve any bundled DejaVu family and style as in Global Constraints; the public signatures do not change.

- [ ] **Step 1: Write failing tests**: with `_fc_match` monkeypatched to return a non-DejaVu fallback and an OS index lacking DejaVu, `font_file("DejaVu Serif", bold=True)` returns the bundled `DejaVuSerif-Bold.ttf`, `font_file("DejaVu Sans Mono", italic=True)` the `-Oblique` file, `DejaVu Serif Condensed` and `DejaVu Sans Condensed` resolve to their bundled files; an unrelated family (`"Arial"`) still follows the old order (fc-match result used when present); case-insensitive family names.
- [ ] **Step 2: Run** `poe test tests/server/test_fonts.py` — expect FAIL.
- [ ] **Step 3: Implement**: build a lazily created, cached index of the bundled folder with the existing `build_face_index` machinery and consult it first for names present in it (check how Pillow's `getname()` reports the Condensed and Serif style names; if `_style_of` cannot model a face, extend the index mapping, minimally); keep `clear_font_cache` clearing it for tests.
- [ ] **Step 4: Run** `poe test tests/server tests/client/test_client_fonts.py`, three `mypy` runs, `poe pylint` — expect PASS.
- [ ] **Step 5: Commit** `feat: resolve the bundled DejaVu families when the OS lacks them`.

---

### Task 3: SDK `font_path` and `DECKER_FONT_DIR`

**Files:**
- Create: `src/decker_plugin_sdk/fonts.py`, `tests/sdk/test_fonts.py`
- Modify: `src/decker/plugin/runtime/launcher.py`, `tests/plugin/runtime/test_launcher.py`, `docs/plugins/sdk-quickstart.md`, `docs/plugins/README.md` if it lists SDK modules, `CLAUDE.md` (plugins bullet: the helper and the env var)

**Interfaces:**
- Consumes: `BUNDLED_FONT_DIR`.
- Produces: `font_path` and `DECKER_FONT_DIR` as in Global Constraints.

- [ ] **Step 1: Write failing tests**: `font_path` for each family x bold x italic combination returns an existing file inside a temp folder populated with empty files of the expected names and pointed at by monkeypatched `DECKER_FONT_DIR`; variable unset -> `None`; unknown family -> `None`; missing file -> `None`; case-insensitive family; a test against the real bundled folder that every supported combination exists; `launch_env(None)` and `launch_env(path)` contain `DECKER_FONT_DIR` equal to the bundled folder's absolute path (all OSes).
- [ ] **Step 2: Run** `poe test tests/sdk/test_fonts.py tests/plugin/runtime/test_launcher.py` — expect FAIL.
- [ ] **Step 3: Implement** `fonts.py` (data table, stdlib only, no raising) and the env var; export `font_path` from the module (do not add it to the package `__all__`; plugins import `decker_plugin_sdk.fonts`). Document it in `sdk-quickstart.md` with the fallback pattern Counter uses and the note that an older Decker has no such module.
- [ ] **Step 4: Run** `poe test tests/sdk tests/plugin`, three `mypy` runs, `poe pylint` — expect PASS.
- [ ] **Step 5: Commit** `feat: let plugins locate Decker's bundled fonts through the SDK`.

---

### Task 4: Decker CI to green and docs

**Files:** `docs/platform-support.md` (the key fonts/plugin rows), any file a failure needs.

- [ ] **Step 1:** Run the local gates (`poe format`, `poe mypy` x3, `poe pylint`, `poe test tests/common tests/server tests/plugin tests/sdk` and the client font tests), push `feat/bundled-dejavu-sdk-fonts`, run `gh workflow run ci.yml --ref feat/bundled-dejavu-sdk-fonts`, read failures with `gh run view <id> --log-failed`.
- [ ] **Step 2:** Fix each failure at its cause (one cause per commit); stop with BLOCKED if one needs a design decision or after 6 runs.
- [ ] **Step 3:** When all jobs are green, update `docs/platform-support.md` (key fonts row: the family is bundled and resolvable on every OS, plugin SDK font helper; cells `CI` only where the runs prove the new tests) and record the run id; commit `docs: record bundled font CI coverage`. Report the pushed commit SHA (the plugins repo pins it).

---

### Task 5: Counter uses the SDK font (plugins repo)

**Repo:** `/work/decker/decker-plugins` (run `git checkout main && git pull`, then `git checkout -b feat/counter-font-and-ci-matrix`).

**Files:**
- Modify: `plugins/com.decker.counter/plugin.py`, `plugins/com.decker.counter/manifest.json` (version `1.1.0`), `plugins/com.decker.counter/tests/` (the existing render tests), `pyproject.toml` (Decker pin) and `uv.lock`

**Interfaces:**
- Consumes: `decker_plugin_sdk.fonts.font_path` from the Decker commit reported by Task 4.

- [ ] **Step 1: Write failing tests**: `render(5)` returns a PNG with non-transparent pixels using the SDK font (set `DECKER_FONT_DIR` to the Decker bundle via the pinned install, assert the font used is the bundled bold, e.g. by monkeypatching `ImageFont.truetype` to record the path); with `font_path` patched to return `None`, and with the `decker_plugin_sdk.fonts` import blocked (simulate ImportError), `render(5)` still returns a non-empty PNG; no `subprocess` import remains.
- [ ] **Step 2: Run** `uv run pytest plugins/com.decker.counter` — expect FAIL.
- [ ] **Step 3: Implement** per Global Constraints; point the `decker @ git+...@<sha>` pin in `pyproject.toml` at the Task 4 commit (a later action, outside this plan, moves it to the merge commit on Decker's `main`) and run `uv lock`.
- [ ] **Step 4: Run** `uv run ruff check .` and `uv run pytest` — expect PASS.
- [ ] **Step 5: Commit** `feat: draw the Counter number with Decker's bundled font`.

---

### Task 6: Plugins CI matrix to green

**Files:** `.github/workflows/ci.yml`, any file a failure needs.

- [ ] **Step 1:** Split the workflow: a Linux `lint-and-package` job (ruff, version checks, pack, artifact upload) and a `test` job on the OS matrix (checkout, uv, `uv sync --locked`, tool tests, the per-plugin test loop written so it also works under Windows's shell, e.g. `shell: bash`); add `workflow_dispatch`. Push `feat/counter-font-and-ci-matrix`, run `gh workflow run ci.yml --ref feat/counter-font-and-ci-matrix`.
- [ ] **Step 2:** Fix failures at their cause (one per commit); installing the Decker pin on Windows/macOS may need system packages (see Decker's `.github/workflows/ci.yml` for MSYS2/Homebrew Cairo and hidapi setup) or `QT_QPA_PLATFORM=offscreen`. Stop with BLOCKED if the pin cannot install on a runner after reasonable effort, or after 6 runs. Confirm from the log that plugin tests ran on all three OSes (use `-rs` to list skips).
- [ ] **Step 3: Commit** `ci: run the plugin and tool tests on Linux, Windows and macOS` (plus fixes as separate commits).

---

### Task 7: Fill the plugin support table

**Files:** `docs/platform-support.md` (plugins repo), `README.md` (Platform support paragraph if it needs the matrix mention)

- [ ] **Step 1:** Add the `CI` legend entry; set the table cells per Global Constraints from the Task 6 run (cite the run id in a footnote); describe the Counter font behaviour (SDK font on a Decker with `font_path`, Pillow default otherwise) and what CI does not cover.
- [ ] **Step 2: Commit** `docs: fill the plugin platform support table from CI`; push and confirm the final run is green; do not open a PR.
