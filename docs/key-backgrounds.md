# Key backgrounds

Every key can have a background that Decker draws behind the icon and the title. It is part of the key's appearance
and is edited in the key editor's appearance section.

## Modes

| Mode | Meaning |
|------|---------|
| None | No background; the key is black behind the icon and title. |
| Solid colour | One colour fills the key. |
| Image | An image from the **image library** fills the key. |

The image library is the browser of everything the server serves as images: icon packs from plugins, the User pack and,
on Linux, the System Icons.

## Stored value

```json
{ "type": "image", "color": "#1f618d", "image": { "ref": "pack:decker.user/sunset.png" } }
```

- `type` is `none`, `color` or `image`; it decides which of the other fields is used.
- `color` is `#rrggbb` (or `#rrggbbaa`); it is kept when you switch modes.
- `image.ref` is `pack:<pack id>/<path>`.

Legacy values that are a bare colour string (`"#1f618d"`) still work and need no migration: they are read as
`{"type": "color", "color": "#1f618d"}`. A plugin manifest can therefore keep giving a plain colour string as the
`background` default in `appearance`, and a `background` settings field accepts a string too. See
[package-and-manifest.md](plugins/package-and-manifest.md) and [settings-schema.md](plugins/settings-schema.md).

## How an image is drawn

The image fills the key by cover-and-crop: it is scaled until it covers the whole key and the overflow is cropped,
centred. SVG backgrounds render at the key's square size, so author them square. Transparent areas show black. There
is no tint.

Supported formats: PNG, JPEG, SVG and GIF (first frame for a still, all frames when animated).

## GIF backgrounds

- An animated GIF used as the foreground icon wins: the background then shows its first frame only.
- Otherwise an animated background plays behind the static icon and title.
- A key has one animated source at most.

## Fallbacks

A missing, uninstalled or unreadable image gives a black background; the icon and the title still draw.

## Performance

Decoded background layers are cached by content (64 entries), so redrawing a key does not decode its image again.

## Limitations

No scaling option, no fit or letterbox mode, no tint, no transitions and no slideshow.

## Protocol names are unchanged

Only the user-visible name changed from "icon library" to "image library". The `iconpacks_list`, `iconpack_icons`,
`iconpack_icon` and `icon_import` RPCs, the `icon_packs` manifest key, the `icons.*` config keys, the `pack:` ref prefix
and pack ids (`decker.user`, `decker.system.*`) are the same as before.
