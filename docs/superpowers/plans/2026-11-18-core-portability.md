# Core Portability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Decker's core work at parity on Linux, Windows and macOS, proven by a CI matrix, and record Linux-only features honestly.

**Architecture:** A new `decker.common.processes` module hides per-OS process-group, tree-kill and memory code. A `venv_python` helper fixes the plugin interpreter path. Font lookup gets an OS-neutral index and a bundled fallback font. System Icons turns itself off on non-Linux hosts. The CI `test` job becomes a three-OS matrix and `mypy` also checks the Windows and macOS branches.

**Tech Stack:** Python 3.14, Poetry, psutil, Pillow, PyQt6, GitHub Actions, pytest + assertpy.

**Spec:** `docs/superpowers/specs/2026-11-18-core-portability-design.md` (project 2 of 3; umbrella: `2026-11-18-platform-support-design.md`).

## Global Constraints

- Platform branches use `if sys.platform == "win32":` / `sys.platform == "linux"` so `mypy --platform win32|darwin` checks both sides; `os.killpg` and `signal.SIGKILL` must only appear in the POSIX branch.
- `decker.common.processes` API: `group_popen_kwargs() -> dict[str, Any]`, `terminate_tree(proc: subprocess.Popen[Any]) -> None`, `kill_tree(proc: subprocess.Popen[Any]) -> None`, `rss_bytes(pid: int) -> int | None`. POSIX keeps `os.killpg` (SIGTERM / SIGKILL, ignoring `ProcessLookupError` and `PermissionError`); Windows uses `subprocess.CREATE_NEW_PROCESS_GROUP` and a recursive `psutil` kill; `rss_bytes` uses `psutil` on every OS and returns `None` when the process is gone or access is denied.
- `psutil` is a runtime dependency in `pyproject.toml`; add its typing stubs to the dev group only if mypy needs them.
- `venv_python(plugin_dir: Path) -> Path` returns `<plugin_dir>/.venv/Scripts/python.exe` on Windows and `<plugin_dir>/.venv/bin/python` elsewhere.
- Font resolution order: fontconfig `fc-match` when the binary exists; else a lazily built in-memory index of installed font files from OS font directories (Windows `%WINDIR%\Fonts` and the per-user fonts folder; macOS `/System/Library/Fonts`, `/Library/Fonts`, `~/Library/Fonts`; Linux XDG font directories), keyed by family and style from each font file's own metadata, case-insensitive; else the bundled DejaVu Sans (regular and bold) under `src/decker/assets/fonts/` with its licence file. The hard-coded `/usr/share/fonts/TTF/...` path is removed.
- System Icons: on `sys.platform != "linux"` `IconPackRegistry.list_packs` omits every `decker.system.*` pack, the system icon index is never built or warmed, and reads return `None`; the `icons.system_theme` setting is ignored there.
- `~/.decker` stays the data folder on every OS.
- CI: `test` job matrix `ubuntu-latest`, `windows-latest`, `macos-latest`, `fail-fast: false`, `QT_QPA_PLATFORM=offscreen`; `workflow_dispatch` trigger added; `format` and `pylint` stay Linux-only; `mypy` also runs with `--platform win32` and `--platform darwin`. Tests that cannot run on an OS use registered markers `linux_only` / `posix_only` (via `skipif`) with a reason that names the feature and its table row; no unmarked platform skips.
- `docs/platform-support.md` legend gains `CI` (verified by the matrix) beside `Yes` (maintainer-verified); System Icons is `No (Linux-only)` on Windows and macOS; hardware access stays `Not verified` there.
- The maintainer approved pushing the work branch `feat/core-portability` to GitHub and running the workflow with `gh workflow run ci.yml --ref feat/core-portability`; no PR is opened until the matrix is green.
- Project rules: annotate everything (tests too), methods < 50 lines, max 5 args, docstrings on public items only, black 120. Gates: `poe format`, `poe mypy`, `poe pylint` (>= 9.0), `poe test` (coverage >= 85%). Tests use pytest + assertpy, mirror `src/` under `tests/`, prefer real processes and files over mocks.

## Review Focus

- Killing a plugin process tree leaves no surviving grandchild, and a process that already exited never raises (Task 2).
- `rss_bytes` for a pid that does not exist or cannot be read returns `None`, never raises (Task 2).
- A plugin directory whose path contains spaces still yields a correct interpreter path and launch argv (Task 3).
- Font families match case-insensitively ("dejavu sans" vs "DejaVu Sans"), and a corrupt font file in a scanned directory does not break the index or crash rendering (Task 4).
- On a non-Linux host the icon pack list contains the user pack but no system packs, and no warm thread starts (Task 5).
- No test is skipped on an OS without a registered marker and a reason naming a table row (Task 7).
- `cairosvg` needs a native Cairo library; SVG rendering must work on the Windows and macOS runners, or the task stops and reports instead of redesigning rendering (Tasks 1 and 7).

---

### Task 1: CI matrix, manual trigger and first triage run

**Files:**
- Modify: `.github/workflows/ci.yml`, `.github/actions/setup-poetry/action.yml`, `pyproject.toml` (register pytest markers `linux_only`, `posix_only`)

**Interfaces:**
- Produces: the workflow described in Global Constraints and a triage list used by later tasks.

- [ ] **Step 1:** Edit `ci.yml`: add `workflow_dispatch:` to `on:`; turn the `test` job into a matrix over the three OSes (`fail-fast: false`) with per-OS system dependencies (keep the apt line on Linux; `brew install hidapi cairo` on macOS; on Windows install what the `streamdeck` loader and Cairo need, finding the working steps by running the job); set `QT_QPA_PLATFORM: offscreen`; add `poetry run mypy --platform win32 .` and `poetry run mypy --platform darwin .` steps to the `mypy` job. Make `setup-poetry` OS-neutral (every `run` already uses `shell: bash`; check `pip install poetry` and caching on Windows and macOS). Install `uv` on every OS if the slow tests need it (`astral-sh/setup-uv`).
- [ ] **Step 2:** Register the markers in `[tool.pytest.ini_options]`: `linux_only: needs Linux-only behaviour`, `posix_only: needs POSIX process behaviour`.
- [ ] **Step 3:** Commit `ci: test on Linux, Windows and macOS and check per-OS typing`, push `feat/core-portability`, run `gh workflow run ci.yml --ref feat/core-portability`, watch it (`gh run watch`), and read failures with `gh run view <id> --log-failed`.
- [ ] **Step 4:** Write the triage to the report file: per OS, the failing steps and tests grouped by cause (for example "plugin launch uses `.venv/bin/python`", "fonts", "cairo missing", "hidapi missing", "`/proc`", "POSIX signals"), with the log lines that show each cause. Fix only CI-environment problems (missing system libraries, workflow syntax) in this task; leave code failures to Tasks 2-5. Re-run until the only failures left are code failures, and record each iteration. If Cairo or hidapi cannot be made available on a runner by any reasonable install step, stop with BLOCKED and say what was tried.

---

### Task 2: `decker.common.processes` and `psutil`

**Files:**
- Create: `src/decker/common/processes.py`
- Modify: `src/decker/plugin/runtime/process.py` (`start`, `stop`, `_signal_group`, `rss_bytes`), `src/decker/plugin/environment.py` (`_kill_group`, `_run`), `src/decker/server/monitor.py` (`_read_rss_bytes`), `pyproject.toml` (dependency)
- Test: `tests/common/test_processes.py`, update the existing tests of the three callers

**Interfaces:**
- Produces: `group_popen_kwargs`, `terminate_tree`, `kill_tree`, `rss_bytes` as in Global Constraints. Callers use them in place of `start_new_session=True`, `os.killpg(...)`, `signal.SIGTERM/SIGKILL` on groups and the two `/proc` readers.

- [ ] **Step 1: Write failing tests** with real processes (the helper spawns `sys.executable -c ...` using `group_popen_kwargs()`): `test_kill_tree_stops_the_process_and_its_grandchild` (parent starts a child that sleeps and prints its pid; after `kill_tree(parent)` neither pid is alive, checked with `psutil.pid_exists` within a short timeout); `test_terminate_tree_stops_a_sleeping_process`; `test_terminate_and_kill_on_an_exited_process_do_not_raise`; `test_rss_bytes_of_the_current_process_is_positive`; `test_rss_bytes_of_a_missing_pid_is_none` (a pid from a just-reaped process); `test_group_popen_kwargs_matches_the_platform` (POSIX: `start_new_session` is True; Windows: `creationflags` contains `CREATE_NEW_PROCESS_GROUP`, using `pytest.mark.skipif` markers `posix_only` / a Windows skip with a reason naming "plugin runtime"). Update the callers' tests so they no longer patch `/proc` reads or `os.killpg`.
- [ ] **Step 2: Run** `poe test tests/common/test_processes.py` — expect FAIL (module missing).
- [ ] **Step 3: Implement** the module and migrate the three callers; add `psutil` to dependencies (`poetry add psutil`) and stubs if mypy asks; keep every moved method under 50 lines.
- [ ] **Step 4: Run** `poe test tests/common tests/plugin tests/server` and `poe mypy` plus `poetry run mypy --platform win32 .` and `--platform darwin` — expect PASS.
- [ ] **Step 5: Commit** `feat: cross-platform process groups, tree kill and memory reading`.

---

### Task 3: Plugin interpreter path

**Files:**
- Modify: `src/decker/plugin/runtime/launcher.py` (`launch_argv` or the function that builds the argv), `src/decker/plugin/environment.py` (wherever it names the venv interpreter; find with `grep -n "bin/python\|\.venv" -r src`)
- Test: `tests/plugin/runtime/test_launcher.py`, `tests/plugin/test_environment.py`

**Interfaces:**
- Produces: `venv_python(plugin_dir: Path) -> Path` in `decker/plugin/environment.py`, used by the launcher and by every place that built `.venv/bin/python` by hand.

- [ ] **Step 1: Write failing tests**: `test_venv_python_uses_scripts_on_windows` (monkeypatch `sys.platform` to `win32`; expected `<dir>/.venv/Scripts/python.exe`); `test_venv_python_uses_bin_elsewhere` (`linux` and `darwin`); `test_launch_argv_uses_the_interpreter_in_a_directory_with_spaces` (a `tmp_path / "my plugins" / "p"` directory; the argv's first item equals `str(venv_python(dir))`).
- [ ] **Step 2: Run** the new tests — expect FAIL.
- [ ] **Step 3: Implement** `venv_python`, use it everywhere the old literal appeared (no remaining `.venv/bin/python` strings in `src/`).
- [ ] **Step 4: Run** `poe test tests/plugin` and the three-platform `mypy` runs — expect PASS.
- [ ] **Step 5: Commit** `fix: locate the plugin interpreter per platform`.

---

### Task 4: Fonts

**Files:**
- Create: `src/decker/server/fonts.py` (font index and resolution moved out of `appearance.py`), `src/decker/assets/fonts/DejaVuSans.ttf`, `src/decker/assets/fonts/DejaVuSans-Bold.ttf`, the DejaVu licence file next to them (copy from the system's DejaVu package or the upstream release; state the source in the report)
- Modify: `src/decker/server/appearance.py` (use the new module; delete `_FALLBACK_FONT` and `/usr/share/fonts/TTF/...`)
- Test: `tests/server/test_fonts.py`, update `tests/server/test_appearance.py`

**Interfaces:**
- Produces in `decker.server.fonts`: `font_file(family: str, bold: bool = False, italic: bool = False) -> tuple[str | None, bool]` (same return contract as the old `_font_file`: path or `None`, and whether the file is really bold; cached), `build_font_index(directories: Sequence[Path]) -> dict[tuple[str, str], str]` (key: lower-cased family, style `regular|bold|italic|bolditalic`), `font_directories() -> list[Path]` (per OS), `BUNDLED_REGULAR: Path`, `BUNDLED_BOLD: Path`. `appearance._font` keeps its signature and never falls back to Pillow's tiny default font while the bundled files exist.

- [ ] **Step 1: Write failing tests**: `test_build_font_index_reads_family_and_style_from_the_files` (copy the bundled fonts into `tmp_path` under unrelated file names; index has `("dejavu sans", "regular")` and `("dejavu sans", "bold")`); `test_font_lookup_is_case_insensitive`; `test_a_corrupt_font_file_is_skipped` (a text file named `x.ttf` in the directory; the index still contains the real fonts); `test_font_file_uses_the_index_when_fc_match_is_missing` (monkeypatch `shutil.which` to return `None`); `test_font_file_falls_back_to_the_bundled_font_when_nothing_matches`; `test_font_directories_per_platform` (monkeypatch `sys.platform` and environment for `win32`, `darwin`, `linux`); `test_appearance_font_never_returns_the_pillow_default_font` (unknown family with empty font directories -> a `FreeTypeFont`).
- [ ] **Step 2: Run** `poe test tests/server/test_fonts.py` — expect FAIL.
- [ ] **Step 3: Implement** the module and rewire `appearance.py`; build the index lazily, once, under a lock; log failures at debug level only.
- [ ] **Step 4: Run** `poe test tests/server` and the three-platform `mypy` runs — expect PASS; confirm the bundled font files are included in the built package (`poetry build` then list the wheel, or confirm `packages` covers them) and say how.
- [ ] **Step 5: Commit** `feat: find fonts on every OS and bundle a fallback`.

---

### Task 5: System Icons are Linux-only

**Files:**
- Modify: `src/decker/asset/systemicons.py` (`SystemIcons`), `src/decker/asset/iconpack.py` (only if the registry needs to pass the flag)
- Test: `tests/asset/test_systemicons.py`, `tests/asset/test_iconpack.py`

**Interfaces:**
- Produces: `SystemIcons(..., enabled: bool | None = None)` where `None` means `sys.platform == "linux"`; when disabled `owns(pack_id)` is `False`, `list_packs()` and `list_icons(...)` are empty, `read_icon(...)` is `None`, `warm()` does nothing (no thread). The `decker.system.` pack id prefix stays reserved for plugin ids on every OS.

- [ ] **Step 1: Write failing tests**: `test_disabled_system_icons_expose_nothing` (`enabled=False`: no packs, no icons, `read_icon` is `None`, `owns` is `False`); `test_disabled_warm_starts_no_thread` (`threading.active_count()` unchanged); `test_default_enabled_follows_the_platform` (monkeypatch `sys.platform`); in `test_iconpack.py`, `test_registry_lists_the_user_pack_but_no_system_packs_when_disabled`; `test_plugin_still_cannot_register_a_decker_system_pack_when_disabled`.
- [ ] **Step 2: Run** the new tests — expect FAIL.
- [ ] **Step 3: Implement** the flag and gating.
- [ ] **Step 4: Run** `poe test tests/asset tests/server` — expect PASS.
- [ ] **Step 5: Commit** `feat: System Icons are Linux-only`.

---

### Task 6: Docs, `CLAUDE.md` fixes and the support table

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `docs/platform-support.md`

**Interfaces:** none (documentation); statements must match the code and the CI results recorded in Task 1.

- [ ] **Step 1: README** gets a per-OS setup section: Linux (Debian/Ubuntu, Fedora, Arch; a udev rule for Elgato vendor id `0fd9` with the group/permission steps), Windows (hidapi library placement, Cairo for SVG rendering, uv) and macOS (Homebrew `hidapi` and `cairo`, uv). Take the exact Windows and macOS steps from what made the CI jobs pass (Task 1 triage) and say so; mark anything not confirmed as unverified.
- [ ] **Step 2: `CLAUDE.md`**: remove `poe server --daemon --verbose` from "Running the project", replace "via `/proc/<pid>/status` or `psutil`" with the real `psutil` behaviour, and mention `decker.common.processes` in the architecture notes in one line.
- [ ] **Step 3: `docs/platform-support.md`**: add the `CI` legend entry; update rows to the verified state (plugin runtime, server monitor, key rendering and fonts as a new row, plugin install, setup docs); System Icons `No (Linux-only)` on Windows and macOS; remove footnotes that no longer apply; only mark a Windows or macOS cell `CI` when the matrix passes the tests for that feature in Task 7.
- [ ] **Step 4: Commit** `docs: per-OS setup, corrected CLAUDE.md and updated support table` (after Task 7 turns the CI results into cells, amend the table in a follow-up commit if needed).

---

### Task 7: Drive the matrix to green and finish

**Files:** any file the triage shows needs a fix; tests that cannot run on an OS get a marker.

- [ ] **Step 1:** Push the branch and run the workflow; read `gh run view <id> --log-failed` for each failing job.
- [ ] **Step 2:** Fix each remaining failure at its cause. A test that cannot run on an OS is marked `linux_only` or `posix_only` with a `skipif` reason that names the feature and its table row; never skip silently, and never skip a test that a small fix would make pass. Commit each fix with a descriptive message and re-run; record every iteration (failing job, cause, fix) in the report. Stop with BLOCKED and a summary if a failure needs a design decision (for example replacing `cairosvg`), or after 8 workflow runs without converging.
- [ ] **Step 3:** When all three `test` jobs, `mypy` (including both `--platform` runs), `format` and `pylint` pass on the pushed branch, run the Decker gates locally (`poe format`, `poe mypy`, `poe pylint` >= 9.0, `poe test` coverage >= 85%) and update the support-table cells to match the green results.
- [ ] **Step 4: Commit** `ci: matrix green on Linux, Windows and macOS` (and any table update). Do not open a PR.
