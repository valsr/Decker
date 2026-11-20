# Platform support

**Standing rule:** every new feature and every plugin must target all five platform tiers below. Whoever changes a
feature updates the README table in the same change. Plugins live in their own repository (`valsr/decker-plugins`), which
keeps its own plugins x platforms table in its README; update that one in the same change as well. A
plugin may skip a platform when porting is too onerous, but it must say so in its manifest (`platforms`, `linux`; see
[package and manifest](plugins/package-and-manifest.md)) so users can see and filter on it.

## Priority tiers

1. Linux (Arch/Manjaro, Plasma, Wayland): the primary target.
2. Linux (Ubuntu/Debian/Fedora, GNOME): parity with the primary target.
3. Linux (other): 90-100% of the functionality.
4. Windows: 75%+ of the functionality.
5. macOS: 75%+ of the functionality.

Core functionality is expected at parity on every platform.

The features x platforms table, with its footnotes, lives in the [README](../README.md#platform-support).
Plugin support is declared per plugin and tracked in the plugins repository's README.

## Focused-app profile switching

Switching profiles by focused window (see [app profile switching](app-profile-switching.md)) ships in v1 with backends for
Plasma 6 Wayland (KWin), X11 and Windows. GNOME Wayland and macOS report "unsupported" and come later; the standing rule
above still applies, so they stay marked in the README table until a backend exists. The Windows and X11 backends are
only tested against fakes so far.

## Screensaver and brightness

The screensaver (see [screensaver](screensaver.md)) is drawn by the server with Pillow and written over the same HID path
as key faces, so it has no OS-specific code and targets all five tiers alike. It is only tested against fakes so far, not
on real hardware, and image and folder paths are set only from the server's machine. SVG images are rasterised through
Cairo, like icons, so they need the Cairo library on every OS (see the README's install sections).
