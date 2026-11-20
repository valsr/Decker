# Settings schema

`global_settings` and each card's and action's `settings` are an ordered list rendered top to bottom as a form.

## Entries

- Section heading: `{ "section": "Title" }`
- Field: `{ "key": "...", "type": "...", "label": "...", "default": ..., ...}`

Common field keys: `key` (unique within the list), `type`, `label`, `default`, `optional` (an empty value is allowed
and stored as `null`), `placeholder`, `help`.

## Types

| Type | Extra keys | Value |
|------|------------|-------|
| `int` | `min`, `max`, `step`, `special_value` (text shown at `min`, e.g. "no limit") | integer |
| `float` | `min`, `max`, `step`, `decimals` | finite number |
| `text` | `multiline`, `template` (boolean, default `false`: expand `{page_name}`, `{page_index}`, `{page_count}`, `{current_profile}`, `{profile_id}` before delivery; `{{`/`}}` are literal braces, unknown names stay as typed) | string |
| `bool` | | boolean |
| `choice` | `options`: `[{ "label": "...", "value": ... }]` (non-empty) | one of the option values |
| `color` | `alpha` (boolean; when `true` the picker has an opacity slider and `#rrggbbaa` is also valid, alpha last) | `#rrggbb` (or `#rrggbbaa`) |
| `font` | | font family name |
| `icon` | | an object, see [Icon](#icon); `default` may be partial |
| `background` | | an object `{"type": "none"\|"color"\|"image", "color": "#rrggbb", "image": {"ref": "pack:<pack id>/<path>"}}`, see [Key backgrounds](../key-backgrounds.md); a plain colour string is still accepted and read as `color` |
| `text_style` | `template` (as for `text`; only its `text`) | an object, see [Text style](#text-style); `default` may be partial |
| `page` | `profile_field` (key of a `profile` field of the same schema: the dropdown then lists that profile's pages; blank or absent: the key's own profile) | a page of the key's device: stored as its page id (string, default `""`), delivered as `{"page_id", "name", "index", "profile_id"}` (`index` is 1-based within its profile; `profile_id` is `-1` when the page is gone); action settings only, not allowed in `global_settings` |
| `profile` | | a profile of the key's device: stored as the decimal profile id (`""`, the default, follows the current profile), delivered as `{"profile_id", "name", "index", "icon"}` (`index` is the 1-based dropdown position, `icon` an icon ref, `decker:logo` for the Decker icon; an unset or deleted profile arrives as `{"profile_id": -1, "name": "", "index": 0, "icon": ""}`). Profile ids are small per-device integers and are **reused** after a profile is deleted, so a stored id can later mean a new profile; action settings only, not allowed in `global_settings` |
| `action` | | an action of any installed plugin: stored as its id (`""`: none). The dropdown lists every available action |
| `action_params` | `action_field` (key of an `action` field of the same schema; the form then shows that action's settings) | an object: the chosen action's settings. Changing the action resets it. Used by the Run Action card |

## Text style

`text_style` is one text field; entering it opens a formatting toolbar (font, size, bold, italic, underline,
strikethrough, position, colour, outline, outline width, visible). Declare it like any other field:

```json
{ "key": "label", "type": "text_style", "label": "Label", "default": { "position": "top", "size": 14 } }
```

The value is an object with these fields; missing or invalid fields fall back to the field's default (per field,
never the whole value):

| Field | Type | Default |
|-------|------|---------|
| `text` | string | `""` |
| `visible` | boolean | `true` |
| `font` | font family name | `"DejaVu Sans"` |
| `size` | integer 4–48 | `12` |
| `bold`, `italic`, `underline`, `strike` | boolean | `false` |
| `position` | `"top"`, `"middle"` or `"bottom"` | `"bottom"` |
| `color` | `#rrggbb` or `#rrggbbaa` (alpha last) | `"#ffffff"` |
| `outline` | `#rrggbb`, `#rrggbbaa` or `null` (no outline) | `null` |
| `outline_width` | integer 1–6 | `1` |

Two text areas on one key are two `text_style` fields. Decker's own key title (appearance key `title`) is a
`text_style` field.

## Icon

`icon` is a control for picking an icon from the image library (the installed icon packs): a preview, the icon's name, **Browse…** (a
searchable browser with the packs grouped by plugin) and a fill colour (RGBA). Declare it like any other field:

```json
{ "key": "icon", "type": "icon", "label": "Icon", "default": { "color": "#ffffff" } }
```

The value is an object; missing or invalid fields fall back to the field's default (per field, never the whole value):

| Field | Type | Default |
|-------|------|---------|
| `ref` | `""` (no icon) or `pack:<pack id>/<icon path>` | `""` |
| `color` | `#rrggbb` or `#rrggbbaa` (alpha last) | `"#ffffff"` |

To show the icon on the key, pass both to the SDK: `ctx.set_icon(settings["icon"]["ref"], settings["icon"]["color"])`
(see [protocol](protocol.md#images)). References with a `..` segment or an absolute path are treated as invalid.

## Validation

The **server** validates stored and incoming values against the schema, so a plugin always receives a complete,
typed settings object:

- unknown keys are dropped;
- missing, invalid, out-of-range or non-finite values fall back to the field's default (or `null` when `optional`);
- the client never duplicates defaults.

Settings reach the plugin in `will_appear.settings`, `settings_changed.settings` and, for plugin-wide settings,
`hello.global_settings` and `global_settings_changed.global_settings`. A plugin can write them back with
`set_settings` (per key) and `set_global_settings`; the server validates those too.
