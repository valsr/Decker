# User icon import — design

## Intent

Let users bring their own icons (GIF, JPG, PNG, SVG) into Decker. Imports appear in a **User** library in the icon browser, next to plugin and System Icons packs, and can be used on any key like any other pack icon.

## Goals

- Import from the GUI file dialog; the old "Choose file..." button is replaced by this flow.
- Each import has a user-chosen, unique id (suggested from the file name). A duplicate is refused and the server suggests a free alternative (`name-2`).
- Raster images (PNG/JPEG/GIF) are resized to 144x144. Animated GIFs are resized frame by frame, keeping frame durations, loop count and transparency.
- SVG is copied unchanged under the unique id.
- Files land in `<root>/assets/user-icons` (`paths.user_icons()`).
- The CLI gets import for free (RPC surface is introspected).

## Non-goals

- Editing, renaming or deleting imports (a later feature; the RPC and pack are shaped so it can be added).
- Cropping, rotating or colour adjustment.
- Importing icon packs (folders of icons).

## Constraints

- All image work is server-side; the client never reads or writes pack folders.
- Import is loopback-gated exactly like `plugin_install` (`server.allow_remote_plugin_install` opens it to remote clients).
- Keep modules decoupled, methods under 50 lines, max 5 args, all types annotated.

## Approaches considered

- **A. Server does everything (chosen).** Client sends bytes, id and options over a new `icon_import` RPC; the server validates, resizes and stores. One tested place for the rules, CLI parity, loopback gating covers it. Cost: file bytes cross RPC (capped).
- **B. Client resizes, server stores.** Smaller uploads and live-exact preview, but rules live in the GUI, no CLI import, Qt cannot write animated GIFs so Pillow would be needed there anyway, and the server would trust client output.

## Design

**Pack.** A reserved pack `decker.user` (name "User"), served by the existing `iconpacks_list` / `iconpack_icons` / `iconpack_icon` RPCs. The `decker.` prefix check that reserves `decker.system.` is extended to refuse plugin packs claiming `decker.user`. The pack is listed even when empty so the library is discoverable. Icons are the files in `user-icons`, sorted by name; the icon name is the file name (`<id>.png|gif|svg`).

**Module `src/decker/asset/usericons.py`** (name: `usericons.py`) holds `UserIcons`:
- `import_icon(name: str, data: bytes, options: ImportOptions) -> ImportResult`
- `suggest_id(name: str) -> str`
- `preview(data: bytes, options: ImportOptions) -> bytes` (PNG, or first GIF frame; nothing written)

`ImportOptions` (frozen dataclass): `fit` (`center` | `stretch`, default `center`), `interpolation` (`nearest` | `bilinear` | `lanczos`, default `nearest`).

**Ids.** Normalised to lowercase `[a-z0-9_-]`, 1–64 chars; anything else is replaced by `-`, runs collapsed, edges trimmed; empty after normalising is refused. Uniqueness is across all extensions (so `cat.gif` blocks `cat.png`). On collision the result is a refusal carrying a suggestion: the first free `id-2`, `id-3`, …

**Resize.** Output is 144x144 RGBA. `center`: scale by one factor to fit inside the square, pad with transparency, centre. `stretch`: independent x/y scales. JPEG imports are saved as PNG. GIF: every frame is composed to full canvas first (honouring disposal), resized with the same rule, re-saved with original per-frame durations and loop count, `disposal=2`, transparency kept. Single-frame GIFs are saved as PNG.

**SVG.** Must parse as XML with an `svg` root; rejected if it contains `<script>`, `<foreignObject>`, `on*=` event attributes, or external `href`/`xlink:href` references (anything not starting with `#` or `data:image/`). Copied byte for byte.

**Limits.** Upload cap = `MAX_ICON_BYTES` (existing icon limit); decoded raster pixels capped (decompression-bomb guard via Pillow `MAX_IMAGE_PIXELS`); GIF frame count capped using the existing animation cap. Over any cap: refused with a reason.

**Writes.** Written to a temp file in the same folder, then `os.replace`d; the id check and write happen under one lock so concurrent imports cannot collide.

**RPC** (`DeckerService`, all loopback-gated except preview, which writes nothing):
- `icon_import(name: str, filename: str, data: bytes, options: str) -> str` — `options` is a JSON string; returns JSON `{ok, id, name, error, suggestion}`.
- `icon_import_preview(filename: str, data: bytes, options: str) -> str` — base64 PNG.
- `icon_import_suggest(name: str) -> str` — a free id.

**Client.** "Choose file..." opens the file dialog, then an **Import icon** dialog: id field (prefilled from the file name, live-checked against the server), fit selector, interpolation selector, and a preview rendered by the server. SVGs hide the fit/interpolation controls. On a duplicate the dialog shows the suggestion and offers to use it. On success it emits the pack icon as if picked from the browser (`pack_icon_selected("decker.user", "<file>")`). `copy_to_user_icons` and its local-folder write are removed. If the client is not allowed to import (remote), the button explains why and the browser still works.

**Docs/tests.** Unit tests for ids, collisions, resize maths (centre/stretch/nearest), GIF timing/loop preservation, SVG rejection, size caps, atomic write; service tests for gating; client dialog tests. Update the picker tests that referenced `copy_to_user_icons`. Note the User pack in `docs/plugins/` where System Icons are described.

## Left to the builder

Exact dialog layout and wording; preview debounce; GIF palette quantisation details; whether the preview RPC shares code with `key_preview` composition.

## Calls I made (for review)

Id charset and 64-char limit; cross-extension uniqueness; JPEG saved as PNG; single-frame GIF saved as PNG; stricter-than-asked SVG rejection; extra bilinear/lanczos options; separate suggest and preview RPCs.
