# Platform support — design

This is the umbrella design for widening Decker's platform support. It is split into three projects, done in order. **Project 1 is designed in detail here and is what gets planned and built next.** Projects 2 and 3 are outlined so project 1 leaves room for them; each gets its own design before it starts.

## Intent

Decker stays Linux-first (Manjaro/Arch/Plasma/Wayland) but should reach parity everywhere. Priority order:

1. Linux (Manjaro/Arch/Plasma/Wayland) — primary target
2. Linux (Ubuntu/Debian/Fedora/Gnome) — parity with the primary target
3. Linux (Other) — 90-100% of functionality
4. Windows — 75%+ of functionality
5. macOS — 75%+ of functionality

Core functionality must be at parity on every platform. A plugin may skip a platform when porting it is too onerous, but it must say so, and users must be able to see and filter on that. Each repo keeps a table of what is supported on which platform.

## Goals

- Plugin manifests (and repository index entries) declare which platforms they support.
- The plugin browser filters on the server's platform, on by default and switchable off.
- A support table in this repo (features x platforms) and in the plugins repo (plugins x platforms), kept up to date by every later feature and plugin change (standing rule, also saved in project memory).

## Non-goals (project 1)

- Making the core portable (project 2) and auditing/porting plugins (project 3).
- Hard-blocking installation of a plugin that does not match the platform.
- A capability-based requirement system.

## Projects

1. **Platform declaration, filter and tables** (this design).
2. **Core portability**: plugin process control (`os.killpg`, `/proc` RSS), server monitor memory reading (`psutil` path), System Icons on systems without freedesktop themes, `libhidapi`/udev/driver setup docs per OS, window/tray differences (GNOME has no default tray), paths and daemon mode on Windows/macOS, and a GitHub Actions matrix (Linux, Windows, macOS runners) so parity is checked automatically.
3. **Plugin audit**: declare `platforms` on every official plugin after checking what each really needs (only Counter currently touches OS-level APIs), and fill the plugin table.

## Approaches considered (project 1)

- **A. Flat OS list plus an optional Linux detail field (chosen).** `platforms` lists OSes; a `linux` object narrows desktops and sessions. Easy to read and validate; the filter has two obvious axes. Cost: Linux has its own field, uneven if another OS later needs detail.
- **B. One list of `os[:desktop[:session]]` tags.** Compact and extensible, but a string grammar is easier to get wrong and harder to validate, and a plugin supporting Plasma and GNOME needs several tags.
- **C. Capability requirements** (`needs: ["dbus", "x11"]`). Most accurate, but needs a capability-to-platform map Decker must maintain, while the tables and filter are phrased in OS terms anyway.

## Design (project 1)

**Platform model.**
- `os`: `linux` | `windows` | `macos`.
- Linux only: `desktop`: `kde` | `gnome` | `other`; `session`: `wayland` | `x11`.

**Manifest** (`manifest.json`, still `format: 1`; additive and optional):
- `"platforms": ["linux", "windows", "macos"]` — non-empty list of OS names; omitted means all platforms. Unknown names are kept and never match (so a newer plugin does not break an older Decker); a list that is not an array of strings, or empty, is a validation error.
- `"linux": {"desktops": ["kde", "gnome", "other"], "sessions": ["wayland", "x11"]}` — optional; each key is a non-empty list, omitted means any. Allowed only when `platforms` is absent or contains `linux`; otherwise a validation error.

**Repository index** (index format v1, additive): each version entry may carry the same `platforms` and `linux` fields, validated the same way; an invalid platform field skips that entry with a warning like other invalid entries. Absent means all platforms.

**Matching.** `platform_supports(spec, host) -> bool` in `decker.common.platforms`: true when the spec is absent; otherwise the host `os` must be listed, and for a Linux host each `linux` constraint must contain the host's desktop/session. A host value of `unknown` (see below) satisfies any constraint on that axis, so a headless server is never filtered out for a detail it cannot know.

**Host detection.** `detect_platform() -> HostPlatform` (server side): `os` from `sys.platform`; Linux desktop from `XDG_CURRENT_DESKTOP` (contains `KDE` -> `kde`, `GNOME` -> `gnome`, anything else -> `other`, unset -> `unknown`), session from `XDG_SESSION_TYPE` (`wayland`/`x11`, else `unknown`). The server runs headless and may be started without a desktop environment, which is why `unknown` exists.

**RPCs.**
- `platform_info() -> str` (JSON `{os, desktop, session}`), exposed to all clients, no gating.
- The existing catalog RPC includes each plugin's `platforms`/`linux` (from the latest version) and a server-computed `supported: bool`; installed-plugin info includes the same two fields.

**Client browser** (`get_more_plugins.py`): a checkbox "Only show plugins that support this system" (label shows the server's platform), on by default; the choice is remembered in the client's UI state store. When the filter is off, unsupported plugins show a "Not supported on <os>" badge; installing one asks for confirmation, then proceeds (warn, never block). Installed plugins that do not match show the same badge in the plugin list. A plugin that does not match is still loaded; the server logs a warning.

**Docs and tables.**
- This repo: `docs/platform-support.md`, a table of core features (rows) against the five platform tiers (columns), with values `Yes`, `Partial` (with a footnote), `Planned`, `No`. Initial contents reflect today's verified state honestly (Tier 1 `Yes`; others `Planned`/`Not verified` where untested). `CLAUDE.md` gains one line pointing to it and stating the standing rule (every feature and plugin change updates the table).
- Plugins repo (`../decker-plugins`): `docs/platform-support.md`, plugins (rows) x tiers; project 1 creates it with every plugin `Not audited`; project 3 fills it. The repo's index-generation tool in `tools/` is updated to copy `platforms`/`linux` from each manifest into the index, with a test.
- `docs/plugins/package-and-manifest.md`, `repositories.md` and the settings/protocol docs get the new fields and RPC.

**Compatibility.** Old plugins (no fields) behave as all-platforms; old Deckers ignore the new optional fields. No manifest format bump.

## Left to the builder

Exact badge wording and layout; where the UI state store key lives; the `HostPlatform` dataclass shape beyond the three fields; the footnote style in the tables.

## Calls I made (for review)

Warn-but-allow install; unknown host values match any constraint; per-version platform data in the index; three Linux desktop buckets (`kde`, `gnome`, `other`) and two sessions; the plugins-repo change ships as a separate PR in `valsr/decker-plugins`.
