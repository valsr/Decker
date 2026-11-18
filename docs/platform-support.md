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
| Partial | Works with known gaps; the footnote names the cause |
| Planned | Not working yet, on the roadmap (project 2, core portability) |
| No | The code clearly cannot work there today |
| Not verified | Nobody has tried it; it may or may not work |

## Features

| Feature | Linux (Arch/Plasma/Wayland) | Linux (Ubuntu/Debian/Fedora/GNOME) | Linux (other) | Windows | macOS |
|---------|------|------|------|------|------|
| Server and monitor | Yes | Not verified | Not verified | Partial [1] | Partial [1] |
| Hardware access (HID) | Yes | Not verified [2] | Not verified [2] | Not verified [3] | Not verified [3] |
| GUI client | Yes | Not verified | Not verified | Not verified | Not verified |
| System tray | Yes | Not verified [4] | Not verified | Not verified | Not verified |
| Plugin runtime (process isolation) | Yes | Not verified | Not verified | No [5] | Partial [5] |
| Plugin install and repositories | Yes | Not verified | Not verified | Partial [5] | Partial [5] |
| System Icons | Yes | Not verified | Not verified | No [6] | No [6] |
| User icon import | Yes | Not verified | Not verified | Not verified | Not verified |
| GIF animations | Yes | Not verified | Not verified | Not verified | Not verified |
| CLI | Yes | Not verified | Not verified | Not verified | Not verified |
| Daemon mode | No [7] | No [7] | No [7] | No [7] | No [7] |

Footnotes:

1. The monitor reads the server's memory from `/proc/<pid>/status` (`src/decker/server/monitor.py`), which exists only
   on Linux. Memory limiting therefore needs `/proc`; a non-`/proc` implementation is planned in project 2.
2. The README documents `libhidapi` setup only for Debian/Ubuntu, Fedora and Arch. Other distributions need their own
   package name, and the README does not cover device permissions.
3. `libhidapi`, drivers and device permissions are not documented for Windows or macOS.
4. GNOME has no system tray by default, and the behaviour there is untested.
5. Plugin process control uses POSIX process groups (`os.killpg`, `src/decker/plugin/runtime/process.py` and
   `src/decker/plugin/environment.py`), which Windows does not have, and per-plugin memory is read from `/proc`. macOS
   has process groups but no `/proc`, so plugin memory reporting is unavailable there. In `environment.py`, `os.killpg` is used only while building a
   plugin environment: it kills the install command's process group on timeout, and again after every command to
   clean up leftover children.
6. System Icons read the server's freedesktop icon theme; Windows and macOS have none.
7. Not implemented: the server has no `--daemon` option.

Plugin support is declared per plugin, not here; see the plugins repository's table.
