# Button icon and key editor — design

Status: approved. Size: small change (server + client).

## Intent

Make the key editor revolve around the key itself: a live preview of what the key will look like, a per-key icon
override, a Save button that is easy to reach and shows when there are unsaved edits, and a highlight on the key being
edited in the grid.

## Goals

- The editor panel header shows the action's name (no key ID).
- Left of the form: a live preview of the key (right click: **Set icon**, **Clear icon**; double click: icon picker).
- Right of the preview, in order: Title row, Icon row (thumbnail, icon colour button when supported, `[x]` clear) and
  Background row on one line, **Save**. The action's own settings form follows below.
- A per-key **icon override** replaces the action's static default icon (manifest icon or state image). Anything the plugin
  draws through `set_image` still wins over it.
- While the form differs from the last loaded/saved values the Save button is highlighted; saving (or loading another
  key) clears it. The server's echo of a save must not re-trigger it.
- The key being edited is outlined in the button grid; the outline clears when the panel returns to the placeholder.

## Non-goals

- Key IDs / profiles (keys stay addressable as device + page + key index).
- Previewing unsaved plugin settings (plugin images come from the plugin's live state).

## Approaches

1. Preview composed on the server through a `key_preview` RPC (chosen): identical to the hardware (fonts, templates,
   page variables), one debounced round trip per edit.
2. Client-side re-implementation of the composer: instant, but duplicates the drawing code and drifts.
3. Preview only after Save: no new RPC, but not "live".

## Design

- `APPEARANCE_SCHEMA` gains `{"key": "icon", "type": "icon", "label": "Icon"}`; it is stored in the existing appearance
  column (no migration) and accepted by `key_update_appearance` via `APPEARANCE_KEYS`.
- `PluginManager._compose`: after the plugin-provided image and before the manifest state image, use the stored
  appearance's icon ref (`icon_packs.read_ref`), with its colour and `PACK_ICON_SCALE`.
- `PluginManager.preview_image(target, stored) -> bytes | None` composes a live key with a draft appearance without
  writing to the sink or the instance; `DeckerService.key_preview(device_id, page_id, key_index, appearance_json) -> str`
  returns base64 PNG, or `""` when the key is unassigned or not live.
- Client: `KeyPreview` widget (image, context menu, double click) emitting `set_icon_requested` / `clear_icon_requested`;
  `ActionConfigPanel` laid out as above, tracks dirty state, debounces (150 ms) preview requests through an injected
  provider; `ButtonGridWidget.set_selected(index | None)` outlines the key via a `selected` property styled in `theme.qss`.

## Calls made without you

- Preview of a key that is not live (inactive page) falls back to the last composed key image.
- Highlight styling: Save uses the theme's accent colour; selected key uses a 2 px accent outline.
