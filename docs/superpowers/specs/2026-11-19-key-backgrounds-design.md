# Key background images and "image library" naming — design

Status: awaiting approval. Size: small change (one repo: `decker`).

## Intent

A key's background today is only a colour. Users want a picture behind the icon and title, taken from the library, and
the library should be called the **image library** because it no longer holds only icons (it holds images, SVGs and
GIFs).

## Decisions taken with the user

- A key background is one of three modes: **none**, **solid colour**, **image** (PNG, SVG or animated GIF from the library).
- Transitions and slideshows are **dropped** from this change.
- **Approach A:** a nested `background` appearance setting, like the nested `title`. Old values stay readable.
- **GIF backgrounds:** if the foreground icon is itself an animated GIF it wins and the background shows its first
  frame; otherwise an animated GIF background plays behind the static icon and title.
- **Rename:** user-visible labels and docs say "image library". Pack ids, RPC names (`iconpacks_list`, ...) and the
  manifest key `icon_packs` keep their names so existing plugins keep working.

## Goals

- `background` appearance setting `{type: "none" | "color" | "image", color, image}`:
  - `none`: opaque black (what the default colour gives today).
  - `color`: `color` is `#rrggbb` or `#rrggbbaa`, composited over black (the hardware has no transparency), as now.
  - `image`: `image` is the same `{ref}` value the `icon` setting uses (a library reference), drawn to fill the key
    (scaled to cover, centred, cropped). Transparent PNGs show black behind them.
- The icon/title still draw over the background; the key preview and the hardware agree.
- An animated GIF background animates through the existing animation writer under the usual budget.
- The key editor shows a mode selector with the colour button or the library picker (no tint control for backgrounds).
- Users see "Image library" instead of "Icon library" in the picker and docs.

## Non-goals

- Transitions, slideshows, per-key image lists; fit/letterbox scaling options; tinting of background images.
- Renaming protocol identifiers, pack ids, RPC names or manifest keys.
- Differentiating GIF/SVG/PNG by badge in the library (separate to-do).

## Anti-goals

- Existing keys must look exactly as before: a stored bare `"#rrggbb"` background renders identically.
- A missing or unreadable background image must never break the key: it falls back to black, the icon and title still draw.
- Plugins that set a `background` default (string) in their manifest keep working unchanged.

## Approaches

- **A. Nested `background` (chosen).** One setting with a mode; legacy strings fold into `{type: color, color}` on read
  (the way legacy flat `title_*` keys fold today), no migration. One clear form control.
- **B. Add `background_image` beside the colour.** No folding, but colour and image are both set at once so "none /
  colour / image" is no longer a single choice, and old clients ignore the new key. Rejected.

## Design

- **Schema (`common/appearance_schema.py`, `plugin/settings_schema.py`):** the `background` entry becomes a new
  `background` field type with default `{type: "color", color: "#000000", image: {ref: ""}}`; a normaliser accepts a
  bare colour string (legacy) or a partial object, rejects unknown types and bad colours, and clamps nothing silently.
  Existing schema validation of manifests keeps accepting string defaults for `background`.
- **Render (`server/appearance.py`):** `_background_layer` handles the three modes; the image is resolved through the
  existing library resolver and drawn with a cover-fit. `compose_key_frames` composes animation frames over a static
  or per-frame background; `compose_key_face` returns an `AnimationSpec` for an animated GIF background when the
  foreground is not itself animated. Unreadable images log at debug once and fall back to black.
- **Animation (`animation/`):** `AnimationSpec` carries the animated source for the background case; the factory
  builds frames as background frame + static icon + title. One animated source per key (the foreground GIF wins).
- **Client:** a `BackgroundEdit` composite (mode combo, colour button, library picker without tint) registered as the
  `background` field type in `schema_form.py` and `_watch`; preview uses the existing `key_preview` RPC.
- **Rename:** library labels, tooltips and docs (`docs/plugins`, README, CLAUDE.md wording) say "image library";
  config key `icons.*` and all protocol names stay.
- **Docs/tests:** appearance docs and a platform-neutral README row; tests for legacy folding, each mode, the GIF
  background plus static icon, foreground-GIF-wins, missing image fallback, the schema form round trip and the preview.

## What is left to the builder

Module layout for the normaliser, the exact cover-fit helper, the BackgroundEdit layout, and which docs mention the
library name.

## My calls (not discussed with the user)

1. The image fills the key by cover-and-crop; there is no scaling option in this change.
2. Transparent PNG/GIF areas show black, not the old colour.
3. Background images are not tinted (the icon's colour override does not apply).
