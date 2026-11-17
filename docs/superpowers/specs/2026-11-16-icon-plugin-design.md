# Icon plugin, icon control and FontAwesome pack — design

Status: awaiting approval. Size: project (two repos: `decker`, `decker-plugins`).

## Intent

Let a user put an icon from an installed icon pack on a key, in a colour they choose. That needs (1) a reusable **icon
control** for settings forms that opens an icon browser (grouped by plugin and pack, searchable), (2) a way for a plugin
to show a pack icon without reading files itself, (3) the **Icon plugin** (`com.decker.icon`) that ties them together,
and (4) shipping the FontAwesome pack (`com.decker.fontawesome`) properly.

## Goals

- `icon` settings type becomes a real control: preview, name, **Browse…**, clear, and a **fill colour** (RGBA, swatch only).
- Browser dialog: left, a tree **Plugin → Pack** (plus "All icons"); right, a thumbnail grid; a **search box** filtering by
  icon name (case-insensitive substring, across the selected pack or all). Thumbnails load lazily (visible first) and
  are tinted so black icons are visible on a dark theme.
- Plugin shows the icon by reference. Fill colour recolours SVGs (the pack icons use `fill="currentColor"`).
- `com.decker.fontawesome` ships: manifest name fixed, package builds, and the published index gets its icon.

## Non-goals

- Shipping `com.decker.fontawesome-full` (left untracked, not packaged or released, for now).
- Choosing a local file in the icon control (the server cannot read a client's disk; the old "Choose file…" picker is unchanged).
- Recolouring raster (png/jpg) icons; only SVGs are tinted.
- Searching by tags/aliases (names only).

## Anti-goals

- Plugins reading other plugins' files, or any path escaping a pack folder.
- A browser that freezes loading thousands of thumbnails (the solid pack has 2001).

## Approaches considered

1. **`pack:` reference resolved by the server (chosen).** `set_image` accepts `{"icon": "pack:<pack id>/<path>", "color": "#rrggbb[aa]"}`;
   the server reads the icon from its registry (existing size cap, path checks) and tints it. The plugin is a few lines and
   needs no new protocol round trip. Uses the `pack:` prefix that the manifest docs already reserve.
2. A request/response pair so a plugin can fetch icon bytes (and tint itself). More protocol, async plumbing in the SDK;
   only worth it if plugins need the raw bytes.
3. A built-in Decker "icon" action instead of a plugin. Simplest, but you asked for a plugin and it would not exercise the
   plugin system.

## Design

### decker (new branch `feat/icon-plugin`, stacked on `feat/text-style-control`)

- **Reference:** `pack:<pack id>/<icon path>`; split at the first `/` (pack ids never contain one). `IconPackRegistry.read_ref(ref) -> bytes | None`
  reuses `read_icon`, so size cap and path checks stay in one place. `iconpacks_list` also returns `plugin_name` for grouping.
- **Value of the `icon` field type:** `{"ref": "", "color": "#ffffff"}` (`ref` is `""` or a valid `pack:` reference; `color` is
  `#rrggbb` or `#rrggbbaa`; invalid fields fall back per field, like `text_style`). Documented in `settings-schema.md`.
- **Protocol:** `set_image` gains `icon` + optional `color` (mutually exclusive with `image`); unknown/unreadable reference clears
  the image and logs a warning. SDK: `Context.set_icon(ref: str, color: str | None = None)`. Documented in `protocol.md`.
- **Rendering:** `AssetRenderer.render_bytes(data, w, h, color=None)`; for SVG, `color` sets `color` and a default `fill` on the root
  element (so `currentColor` and unstyled paths both follow it) and the alpha becomes root `opacity`. `compose_key_image`
  passes the plugin image's tint through; the server keeps the tint with the plugin image.
- **Client:** `IconEdit` control (registered for type `icon` in `SchemaForm`), `IconBrowserDialog` replacing `IconPackBrowserDialog`
  (also used by the existing `IconPickerWidget`). Thumbnails are loaded one RPC per event-loop turn, visible items first, and
  tinted with the theme's text colour; the chosen fill colour tints the preview.

### decker-plugins (new branch, off `main`)

- `plugins/com.decker.fontawesome/manifest.json`: `name` becomes "Fontawesome Icons" (it says "Counter" today); description tidied.
- `tools/build_index.py`: the manifest icon may be an SVG; it is rendered to a 256 px PNG with Decker's renderer
  (`icons/<id>.png`); PNG icons keep working. Today an SVG icon is silently skipped.
- New plugin `plugins/com.decker.icon` (python runtime, no requirements): one action "Icon", one `icon` setting; on
  `will_appear`/`settings_changed` it calls `set_icon` (or clears the image when `ref` is empty). Own tests.
- The Decker pin in `pyproject.toml` moves to the new Decker commit; `com.decker.icon` declares the Decker version that
  introduced `set_icon` (see Open points).

## Constraints

- Decker conventions (black 120, full annotations, <= 50-line methods, <= 5 args, mypy, pylint >= 9, coverage >= 85%).
- decker-plugins: version rule (new plugin starts at a manifest version with no tag), ruff, plugin tests under the plugin's `tests/`.

## Calls made without you (check these)

- Reference syntax `pack:<pack id>/<icon path>` and value shape `{"ref", "color"}`.
- Server-side tinting via root `color`/`fill`/`opacity`, SVG only.
- Search is a client-side name filter; "All icons" aggregates the packs' name lists.
- The branch stacking, and the new plugin id `com.decker.icon`.

## Open points

- **Decker version gate:** Decker is `0.2.0`; `set_icon` needs a newer server. Proposal: bump Decker to `0.3.0` in this branch and set
  `"decker": ">=0.3"` on `com.decker.icon`. Say if you would rather not bump yet (the plugin would then install on servers that cannot run it).
- Whether pack names should say which plugin they belong to (only matters once `-full` ships).

## Left to the builder

Icons for the cog-like controls, tree widget details, lazy-loading mechanics, exact SVG attribute rewriting, test layout.
