# Platform support

**Standing rule:** every new feature and every plugin must target all five platform tiers below. Whoever changes a
feature updates this table in the same change. Plugins live in their own repository (`valsr/decker-plugins`), which
keeps its own plugins x platforms table in `docs/platform-support.md`; update that one in the same change as well. A
plugin may skip a platform when porting is too onerous, but it must say so in its manifest (`platforms`, `linux`; see
[package and manifest](plugins/package-and-manifest.md)) so users can see and filter on it.

## Priority tiers

1. Linux (Arch/Manjaro, Plasma, Wayland): the primary target.
2. Linux (Ubuntu/Debian/Fedora, GNOME): parity with the primary target.
3. Linux (other): 90-100% of the functionality.
4. Windows: 75%+ of the functionality.
5. macOS: 75%+ of the functionality.

Core functionality is expected at parity on every platform.

## Legend

| Value | Meaning |
|-------|---------|
| Yes | Works, and the author has verified it on that platform |
| CI | Verified by the CI matrix on that OS: the test suite passes there. Weaker than `Yes`: no human has used it, and no hardware is attached to the runners |
| Partial | Works with known gaps; the footnote names the cause |
| Planned | Not working yet, on the roadmap |
| No | The code clearly cannot work there today |
| Not verified | Nobody has tried it; it may or may not work |

## Features

| Feature | Linux (Arch/Plasma/Wayland) | Linux (Ubuntu/Debian/Fedora/GNOME) | Linux (other) | Windows | macOS |
|---------|------|------|------|------|------|
| Server and monitor | Yes | Not verified | Not verified | CI [1] | CI [1] |
| Hardware access (HID) | Yes | Not verified [2] | Not verified [2] | Not verified [3] | Not verified [3] |
| GUI client | Yes | Not verified | Not verified | CI [4] | CI [4] |
| System tray | Yes | Not verified [5] | Not verified | Not verified | Not verified |
| Plugin runtime (process isolation) | Yes | Not verified | Not verified | CI [6] | CI [6] |
| Plugin install and repositories | Yes | Not verified | Not verified | CI [7] | CI [7] |
| Key rendering and fonts | Yes | Not verified | Not verified | CI [8] | CI [8] |
| System Icons | Yes | Not verified | Not verified | No (Linux-only) [9] | No (Linux-only) [9] |
| User icon import | Yes | Not verified | Not verified | CI [10] | CI [10] |
| GIF animations | Yes | Not verified | Not verified | CI | CI |
| CLI | Yes | Not verified | Not verified | CI [11] | CI [11] |
| Daemon mode | No [12] | No [12] | No [12] | No [12] | No [12] |

The Linux (Arch/Plasma/Wayland) column is `Yes` where the maintainer uses the feature, and CI also runs the suite on
Ubuntu. The other Linux columns stay `Not verified` because nobody has used them (CI on Ubuntu only shows the tests
pass there).

Footnotes:

1. CI ran the RPC service layer (with real stores on sqlite), the monitor logic and `decker.common.processes` (process
   groups, tree kill, memory read via psutil, so no `/proc` is needed) on all three OSes. On Windows the tree kill does
   not clean up orphaned helpers once the leader has exited (the pid may be recycled). Not covered: a full
   `poe server` run, memory-limit restarts of a long-lived server, and `poe cli` against a live server.
2. The README documents `libhidapi` setup for Debian/Ubuntu, Fedora and Arch and a conventional udev rule; the udev
   steps are not verified on every distribution, and other distributions need their own package name.
3. The README documents hidapi and Cairo installation for Windows (MSYS2) and macOS (Homebrew) as the CI runners
   needed them, but device permissions and drivers there are unverified. CI never tested hardware access on any OS
   (the runners have no Stream Deck).
4. PyQt6 widget and view tests run offscreen on all three OSes (`QT_QPA_PLATFORM=offscreen`). This is not a human check:
   real window manager behaviour, HiDPI and drag and drop are not covered.
5. GNOME has no system tray by default, and the behaviour there is untested. The tray is not covered by CI on any OS.
6. Plugin children start in their own process group (`CREATE_NEW_PROCESS_GROUP` on Windows, a new session elsewhere).
   They are stopped by a recursive psutil kill on Windows and by `os.killpg` (SIGTERM/SIGKILL) on the process group
   elsewhere; on Windows terminate then kill are both hard kills (`TerminateProcess`). Windows has no process-group
   semantics here, so helpers an executable plugin leaves behind after its leader exits are not cleaned up; the
   follow-up that would remove that whole class is Windows Job Objects with `KILL_ON_JOB_CLOSE` (not implemented). On
   Windows the monitor stops the server with `multiprocessing.Process.terminate()`, which is `TerminateProcess`, so the
   SIGTERM handler and the graceful plugin shutdown do not run on monitor restarts and plugins then rely on stdin EOF;
   POSIX gets SIGTERM and a graceful stop. The launcher uses the plugin venv's interpreter (`Scripts\python.exe` on
   Windows, `bin/python` elsewhere), and on Windows it passes only a minimal environment plus the Windows system
   variables (`SYSTEMROOT`, `TEMP`, ...); a test starts a real interpreter with that environment on every OS. CI ran the
   real `uv venv` build tests (`test_build_creates_venv_with_server_python_when_no_spec` and
   `test_build_installs_requirements`) on Windows and macOS as well as Linux (run 44454336780: all passed, none
   skipped), plus real plugin child processes, the watchdog and orphan checks. `test_venv_is_built_relocatable` uses a
   fake `uv` and only checks the arguments. Builds that
   fetch from a network index are not covered (the requirements test uses a local wheel).
7. CI ran package read/extract (including zip path safety per OS), install, uninstall and repository RPCs against local
   fixtures. Live repository fetches and update checks over the network are not covered.
8. Fonts resolve in this order: `fc-match` when present, an index of the OS font folders, then the bundled DejaVu
   Sans. CI ran the lookup and `compose_key_image` on all three OSes. FreeType rasterisation differs per OS, so only
   Linux asserts a byte-exact image hash; Windows and macOS check structure (size, colours, title region). User-installed
   fonts beyond the runners' defaults are not covered.
9. System Icons read the server's freedesktop icon theme, so the feature is Linux-only: on Windows and macOS the library
   is hidden (CI checks that no packs are served there).
10. Icon import, SVG rasterisation through Cairo (installed via MSYS2 on Windows and Homebrew on macOS) and the
    thumbnail cache are tested on all three OSes. A real file dialog is not covered.
11. CLI command tests run against the in-process service; `poe cli` against a live server on Windows and macOS is not
    covered.
12. Not implemented: the server has no `--daemon` option. Supervision (heartbeat, memory limit, restart) is done by the
    server monitor that `poe server` always starts; DAEMON.md describes it.

Plugin support is declared per plugin, not here; see the plugins repository's table.
