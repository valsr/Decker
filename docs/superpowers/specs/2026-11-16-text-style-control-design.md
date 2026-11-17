# Text style control — design

Status: awaiting approval. Size: small change (client widget, one schema type, renderer extension).

## Intent

Adding text to a key currently takes a long Title section (show title, text, position, font, size, color, outline,
outline width). Replace it with one compact control: a single text field with an inset cog. The cog opens a floating,
single-row formatting toolbar, in the style of a word-processor toolbar. The control is generic and reusable, so plugins
can declare it for their own text without writing UI.

## Goals

- One line-edit with an inset cog at its right end; clicking the cog toggles a floating popup under the field.
- Popup is a single toolbar row:
  `[font ▾] [– size pt +] | [B][I][U][S] | [top][middle][bottom] | [color ▾][outline ▾][– width px +] | [visible 👁]`
  - Font: dropdown of installed families.
  - Size and outline width: numeric input with +/- buttons.
  - Bold, italic, underline, strike: independent toggle buttons with tooltips (Ctrl+B/I/U shortcuts while the popup is focused).
  - Position: three icon toggles, exactly one selected.
  - Color and outline: buttons showing an icon with a coloured bar; click opens the colour dialog with an alpha
    channel (RGBA, added at your request mid-implementation); values are `#rrggbb` or `#rrggbbaa`. Outline's menu has "No outline"; outline width is disabled while there is none.
  - Visible: toggle replacing the old "Show title" checkbox; off hides the text, including a plugin's fallback title.
- Popup closes on outside click or Esc, clamps to the window edge, and edits update the form live; the panel's Save
  button still commits.
- Reusable: a standalone widget (`TextStyleEdit`) with no knowledge of keys or titles, exposed to plugins as a settings
  schema field type, and used by Decker's own title.

## Non-goals

- Alignment, lists, spacing, all-caps or multi-line text (keys are one centred line). Can be added later as value fields.
- Changing how plugins supply images, or any server protocol beyond the schema type and appearance keys.

## Anti-goals

- No Qt imports in server code, and no rendering logic in the client.
- Existing keys must not lose their titles or styling.

## Value shape

One nested object per field:

```json
{"text": "", "visible": true, "font": "DejaVu Sans", "size": 12, "bold": false, "italic": false,
 "underline": false, "strike": false, "position": "bottom", "color": "#ffffff", "outline": null, "outline_width": 1}
```

Schema declaration for plugin authors: `{"key": "label", "type": "text_style", "label": "Label", "default": {...}}`;
partial defaults are filled from the defaults above. Two text areas on one key means two `text_style` fields.

## Approaches considered

1. **Client widget + new schema type + renderer extension (chosen).** Widget lives in `client/widgets/`, registered in
   `schema_form.py` like `color` and `font`; the server validates and renders the value. Keeps the client/server split
   and makes plugin reuse a one-line schema entry.
2. Hard-code a toolbar into the appearance panel only. Fastest, but not reusable by plugins, which was a stated goal.
3. Keep flat `title_*` keys and add a prefix convention for plugins. Avoids migration but needs every consumer to know
   the key family, and is easy to get wrong.

## Server rendering

- Bold/italic: ask fontconfig for the style (`fc-match "Family:bold:italic"`); if the family has no bold face, fake bold
  with a thin stroke.
- Underline/strike: Pillow can't draw them; draw lines from the measured text bounding box, in the text colour, and
  include them in the outline pass so they look part of the text. Placement is approximate for some fonts, which is
  acceptable at 72–144 px keys.
- `visible: false` suppresses all text including the plugin's fallback title. Empty text with `visible: true` still falls
  back to the plugin title.

## Migration

Existing stored appearance keys (`title`, `title_position`, `title_font`, `title_size`, `title_color`, `title_outline`,
`title_outline_width`, `show_title`) are read into the nested value when resolving appearance, so saved keys render
unchanged; they are written back in the new shape on the next save.

## Documentation

Document `text_style` and its value in `docs/plugins/settings-schema.md`.

## Calls made without you (check these)

- Field type name `text_style`, widget name `TextStyleEdit`.
- Visible toggle is an eye icon at the end of the toolbar, default on (you hadn't chosen how to hide the title).
- Size and outline width are +/- numeric inputs (as you first said), not a dropdown like the screenshot.
- Bold falls back to a stroke when a family has no bold face.
- Migration is read-time with write-back on save, not a one-off data rewrite.

## Left to the builder

Exact icons and sizing, popup placement code, keyboard shortcut wiring, how `parse_settings_schema` validates the new
type, and test layout (mirror `tests/client/widgets/` and server appearance tests; keep the ≥ 85% coverage gate).
