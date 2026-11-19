# Bundled DejaVu family, SDK font helper and the plugin audit — design

Project 3 of 3 in `2026-11-18-platform-support-design.md`, plus the Decker change it needs. Spans two repos: Decker (`valsr/decker`) and the plugins repo (`valsr/decker-plugins`).

## Intent

The plugin audit found that four of the five official plugins (Pages, Profiles, Icon, Font Awesome) use no OS APIs and need no platform declaration, while Counter draws its number with a font found through `fc-match` and a hard-coded Arch path. Off Linux it silently falls back to Pillow's default font, so the count looks different on Windows and macOS. The fix is for Decker to hand plugins a font it already ships, so every OS draws the same glyphs. The audit also fills the plugins x platforms table, with Windows and macOS cells backed by CI.

## Goals

- Decker bundles the whole DejaVu family and plugins can get any of its files through the SDK.
- Counter uses the SDK's bold font on every OS and stops running `fc-match`.
- The plugins repo CI runs the plugin and tool tests on Linux, Windows and macOS.
- `docs/platform-support.md` in the plugins repo is filled from evidence.

## Non-goals

- Declaring `platforms` on the four plugins that need nothing (omitted already means "all platforms").
- Plugin-specific font selection UI, or fonts other than DejaVu.
- Bundling DejaVu Math TeX Gyre (my call, see below).
- Changing how the SDK is staged (the font files stay in Decker's assets).

## Approaches considered

- **A. SDK helper plus an env var (chosen).** `launch_env` sets `DECKER_FONT_DIR`; the SDK reads it. Small, testable, no staging change.
- B. Copy the fonts into every staged SDK: about 10 MB per plugin and a change to staging; no benefit over A.
- C. Ship the font inside Counter: duplicates the file per plugin and gives plugins no shared font.

## Design

**Decker, fonts.** `src/decker/assets/fonts/` gains the rest of the DejaVu family from release 2.37: Sans (ExtraLight, Oblique, BoldOblique), Sans Condensed (Regular, Bold, Oblique, BoldOblique), Sans Mono (4), Serif (4), Serif Condensed (4); with the existing Sans Regular and Bold that is 21 files, about 9.9 MB, and the licence file stays. The client registers every bundled file with Qt (`client/fonts.py` lists them today by name, replace it with the folder listing), and the server's font lookup resolves any bundled DejaVu family and style before it falls back to DejaVu Sans, so a family the picker offers is the family the key renders.

**Decker, SDK.** `launch_env` adds `DECKER_FONT_DIR` (absolute path of the bundled folder). New module `decker_plugin_sdk/fonts.py`: `font_path(family: str = "DejaVu Sans", bold: bool = False, italic: bool = False) -> str | None` returns the file for that face, or `None` if the variable is unset, the family or style does not exist, or the file is missing. Supported families: DejaVu Sans, DejaVu Sans Condensed, DejaVu Sans Mono, DejaVu Serif, DejaVu Serif Condensed (Serif files are italic, not oblique, internally: the mapping hides that). Documented in `docs/plugins/`.

**Plugins repo, Counter.** Counter calls `font_path(bold=True)` through `from decker_plugin_sdk.fonts import font_path`; if that import fails (older Decker) or it returns `None`, it uses Pillow's default font. `fc-match`, `subprocess` and the Arch path are removed. Manifest version 1.1.0. Counter's tests cover both paths.

**Plugins repo, CI.** The plugin and tool test steps run on a matrix of `ubuntu-latest`, `windows-latest`, `macos-latest` (`fail-fast: false`, `workflow_dispatch` added); lint, version check and pack stay on Linux. Windows/macOS need whatever system setup Decker's own matrix needed for installing Decker from the git pin (builder verifies; if the pin cannot install there, stop and report).

**Plugins repo, table.** Legend gains `CI` (matrix verified). Rows: the four pure plugins and Counter get `CI` on Windows and macOS where the runs pass; the Ubuntu/Debian/Fedora/GNOME column gets `CI` from the Ubuntu run for what the tests cover; the Arch and "Linux (other)" cells stay `Not verified` unless the maintainer upgrades them. Footnotes state what CI does not cover (no real Stream Deck, no real Decker UI).

**Order and dependencies.** Decker first (its PR must merge), then the plugins repo bumps its Decker pin to the commit with `font_path` and carries the Counter change. Until that bump Counter's tests run against the old pin, so the plugins-repo branch pins the Decker commit of the feature branch for CI and moves it to `main`'s merge commit before its PR is opened.

## Left to the builder

File-to-face mapping inside `fonts.py` (keep it a data table), how the server's font lookup consumes the bundled folder, the exact Windows/macOS CI setup for the plugins repo, test layout.

## Risks

About 9.9 MB more in the Decker package and repository (fonts are binary, history grows once); the SDK helper is public API, so its shape is hard to change later; installing Decker's git pin on Windows and macOS runners may need system libraries (hidapi, Cairo).

## Calls I made (for review)

Excluding DejaVu Math TeX Gyre (a specialised math font, 0.6 MB); exposing only five families through the SDK (ExtraLight is bundled and reachable by the client picker and font lookup, not by `font_path`); a Pillow-default fallback for old Decker rather than a minimum Decker version; leaving the Arch and Linux-other table cells at `Not verified`; branch `feat/bundled-dejavu-sdk-fonts` from `main`.
