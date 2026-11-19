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
