# Core portability — design

Project 2 of 3 in `2026-11-18-platform-support-design.md`. Goal: Decker's **core** works at parity on Linux (all distros), Windows and macOS, and a CI matrix proves it. Features that cannot be ported are documented as Linux-only, not left broken.

## Intent

Core means the server and monitor, hardware access, the GUI client, plugin runtime and install, key rendering (titles and fonts), the CLI, user icon import and GIF animations. Windows and macOS are expected to match Linux there. System Icons (freedesktop icon themes) is explicitly a Linux-only feature.

## Goals

- Plugins launch, stop and are measured correctly on Windows and macOS (today they cannot launch on Windows at all).
- The server monitor's memory limit works on every OS.
- Key text renders with a sensible font on every OS, including the user's chosen family where the OS has it.
- System Icons is hidden on non-Linux hosts and recorded as "No (Linux-only)" in the support table.
- Setup docs per OS (hidapi, device permissions, uv), including a Linux udev section.
- GitHub Actions runs the test suite on Linux, Windows and macOS, and type-checks the per-OS code branches.
- `docs/platform-support.md` cells turn green only for what CI (or the maintainer) has verified; the legend says which.

## Non-goals

- Installers, packaging, autostart, native notifications.
- Moving data from `~/.decker` to `%APPDATA%` / `~/Library` / XDG paths (stays `<home>/.decker` everywhere; revisit separately).
- Bundling an icon theme so System Icons works off Linux.
- GNOME-specific or KDE-specific features; hardware-in-the-loop CI (no deck on runners); CI for Fedora/Debian (the Linux runner is Ubuntu; Linux-other parity is by shared code and docs).
- Porting plugins (project 3).

## Approaches considered

- **Process control — A. one module, per-OS code behind it (chosen).** POSIX keeps today's tested `killpg` path; Windows uses `CREATE_NEW_PROCESS_GROUP` plus a recursive kill; memory via `psutil` on every OS. B. `psutil` for everything changes the working Linux kill path. C. Windows Job Objects via `ctypes` is the most exact but a lot of untestable code.
- **CI — A. tests on three OSes, lint Linux-only, plus `mypy --platform` for win32 and darwin (chosen).** B. every job on every OS costs about three times as much for platform-independent checks.

## Design

**`decker.common.processes`** (new, no Qt):
- `group_popen_kwargs() -> dict[str, Any]` — `{"start_new_session": True}` on POSIX, `{"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}` on Windows; used by `plugin/runtime/process.py` and `plugin/environment.py` instead of `start_new_session=True`.
- `terminate_tree(proc: subprocess.Popen[Any]) -> None` and `kill_tree(proc) -> None` — POSIX: `os.killpg` with SIGTERM / SIGKILL; Windows: `psutil.Process(pid)` children (recursive) then the process, `terminate()` / `kill()`, ignoring already-gone processes.
- `rss_bytes(pid: int) -> int | None` — `psutil.Process(pid).memory_info().rss`, `None` when the process is gone or access is denied. Replaces the `/proc` readers in `server/monitor.py` and `plugin/runtime/process.py`.
- Platform branches use `if sys.platform == "win32":` so mypy's `--platform` flag checks both sides (`signal.SIGKILL` and `os.killpg` do not exist on Windows).
- `psutil` becomes a runtime dependency; the typing stubs package is added to the dev group if mypy needs it.
- The server's `SIGTERM`/`SIGINT` handler registration stays (Windows accepts `SIGINT`; `SIGTERM` registration is harmless there).

**Plugin interpreter path.** `plugin/runtime/launcher.py` builds `<plugin_dir>/.venv/bin/python` today. A shared `venv_python(plugin_dir: Path) -> Path` returns `Scripts/python.exe` on Windows and `bin/python` elsewhere, used by the launcher and by `plugin/environment.py` wherever it names the venv interpreter. Executable-type plugins keep running their entry directly.

**Fonts** (`server/appearance.py`). Resolution order: (1) fontconfig `fc-match` when the binary exists (Linux; macOS if installed); (2) a lazily built, in-memory index of installed font files from the OS font directories (`%WINDIR%\Fonts` and the per-user Windows fonts folder, `/System/Library/Fonts`, `/Library/Fonts`, `~/Library/Fonts`, and the XDG font directories on Linux), keyed by family and style from each file's own metadata (`ImageFont.truetype(...).getname()`); (3) a bundled fallback, DejaVu Sans (regular and bold, with its licence file) under `src/decker/assets/fonts/`, replacing the hard-coded Arch path, so every OS and Linux distro has the same last resort. A font that cannot be found logs once at debug level and falls through.

**System Icons.** On non-Linux hosts `IconPackRegistry.list_packs` omits every `decker.system.*` pack and the system index is never built or warmed; reads return `None`. The `icons.system_theme` setting is ignored there. The client simply does not see the packs. (Detection uses `sys.platform`, via the same host model as project 1.)

**Docs.** README gets a per-OS setup section: Linux (Debian/Ubuntu, Fedora, Arch, with a udev rule for Elgato vendor id `0fd9` and the group/permission steps), Windows (hidapi library placement and uv), macOS (Homebrew `hidapi`, uv). The exact steps are verified by the builder against the `streamdeck` library's loader and each OS's behaviour; anything unverifiable is written as such. Stale `CLAUDE.md` lines (`--daemon`, "psutil fallback") are corrected in this project, since psutil really does become the memory reader.

**CI** (`.github/workflows/ci.yml`):
- `test` job becomes a matrix over `ubuntu-latest`, `windows-latest`, `macos-latest`, `fail-fast: false`, with per-OS system dependencies (apt as today; Homebrew `hidapi` on macOS; the hidapi library for Windows as the builder finds necessary), `QT_QPA_PLATFORM=offscreen` on all, and the same pytest command. Shell steps use `bash` where the composite action needs it; `.github/actions/setup-poetry` is made OS-neutral.
- `mypy` job additionally runs `mypy --platform win32 .` and `mypy --platform darwin .`.
- The workflow gains a `workflow_dispatch` trigger. It currently runs only on pull requests and on pushes to `main`/`release/**`, so a pushed work branch would not run; with the trigger, `gh workflow run ci.yml --ref feat/core-portability` runs the matrix on the pushed branch (the maintainer has approved pushing the work branch for this), and `gh run watch`/`gh run view --log-failed` read the results.
- `format` and `pylint` stay on Linux only.
- Tests that cannot run on an OS carry a registered marker (`linux_only`, `posix_only`) via `pytest.mark.skipif` with a reason naming the feature and its table row; no silent skips.
- The matrix jobs become required checks in branch protection once green (a GitHub setting the maintainer applies; noted in the PR).

**Support table.** `docs/platform-support.md` gains a legend entry `CI` (verified by the matrix) next to `Yes` (maintainer-verified). Rows move as work lands: plugin runtime, server monitor, key rendering/fonts and the setup docs turn `Yes`/`CI` on Windows and macOS; System Icons stays `No (Linux-only)` there; hardware access stays `Not verified` on Windows and macOS (no deck on runners). A new row records key fonts.

## Order of work

1. CI matrix first, so every later fix shows up as a red-to-green change; the first runs also reveal failures this design did not predict (the builder triages and records them).
2. `decker.common.processes` and the `psutil` dependency; migrate the callers.
3. `venv_python`.
4. Fonts and the bundled fallback.
5. System Icons gating.
6. Docs, `CLAUDE.md` fixes and the table.

## Left to the builder

The exact Windows hidapi step; how much of the tests need markers versus fixes; font style matching rules (weight/italic from file metadata); the module split inside the font code; wording in the docs.

## Calls I made (for review)

Bundling DejaVu Sans as the last-resort font; `psutil` as a hard dependency; keeping `~/.decker` on every OS; Ubuntu as the only Linux runner; `mypy --platform` checks instead of full-OS lint; correcting the stale `CLAUDE.md` lines here.

## Risks

CI is the only Windows/macOS verification, so surprises will come in rounds (the work branch is pushed early and run through `workflow_dispatch`, with no PR until green); `streamdeck`/hidapi loading on the runners may need workarounds or test stubs; fonts are matched by metadata, which can differ from the names the client's font picker shows.
