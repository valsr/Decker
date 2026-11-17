# Settings schema

`global_settings` and each action's `settings` are an ordered list rendered top to bottom as a form.

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
| `text` | `multiline` | string |
| `bool` | | boolean |
| `choice` | `options`: `[{ "label": "...", "value": ... }]` (non-empty) | one of the option values |
| `color` | | `#rrggbb` |
| `font` | | font family name |
| `icon` | | a file path (reserved for the icon library) |
| `text_style` | | an object, see [Text style](#text-style); `default` may be partial |

## Text style

`text_style` is one text field with a cog that opens a formatting toolbar (font, size, bold, italic, underline,
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

## Validation

The **server** validates stored and incoming values against the schema, so a plugin always receives a complete,
typed settings object:

- unknown keys are dropped;
- missing, invalid, out-of-range or non-finite values fall back to the field's default (or `null` when `optional`);
- the client never duplicates defaults.

Settings reach the plugin in `will_appear.settings`, `settings_changed.settings` and, for plugin-wide settings,
`hello.global_settings` and `global_settings_changed.global_settings`. A plugin can write them back with
`set_settings` (per key) and `set_global_settings`; the server validates those too.
