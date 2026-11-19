# Decker Server

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE.md)
[![Made with Python](https://img.shields.io/badge/Made%20with-Python-ff7b3f.svg)](https://www.python.org/)

> :warning: Decker Server is currently in early alpha release and doesn't work! Dont use at this point.

**Decker** is an linux application designed for Elgato Stream Deck, inspired by
[StreamController](https://github.com/StreamController/StreamController).

**Decker Server** is the server component/application that handles interacting with the hardware.

## Supported Devices

Decker supports the following Elgato Stream Deck models:

- Stream Deck XL

## Features

| Feature | Status |
|---------|--------|
| Server with monitor (heartbeat, memory limit, automatic restart), multiple clients | Supported |
| Device discovery, stable device ids | Supported |
| Profiles and pages per device, per-key actions and long press | Supported |
| Key appearance: title, fonts, colours, icon override, live preview | Supported |
| Icon packs (plugins, User pack, System Icons on Linux) | Supported |
| Animated GIF key faces | Supported |
| Plugins (out of process, `.deckerplugin` packages, repositories, updates) | Supported |
| PyQt6 desktop client | Supported |
| Command line client (`poe cli`) | Supported |
| Daemon mode, system tray on every desktop | Not supported |

Early alpha: the table shows what exists, not that it is stable. Plugins are listed in the
[plugins repository](https://github.com/valsr/decker-plugins).

### Platform support

| Platform | Status |
|----------|--------|
| Linux (Arch/Manjaro, Plasma, Wayland) | Used by the maintainer, including hardware; also tested in CI on Arch |
| Linux (Ubuntu/Debian/Fedora, GNOME) | Test suite passes in CI (no hardware) |
| Linux (other) | Not verified |
| Windows | Test suite passes in CI (no hardware) |
| macOS | Test suite passes in CI (no hardware) |

Per-feature detail, with what CI does and does not cover, is in [docs/platform-support.md](docs/platform-support.md).

## System Requirements

**Decker Server** depends on the following libraries to be installed:

- libhidapi
- [uv](https://docs.astral.sh/uv/), needed to install plugins that have a Python runtime (it builds each plugin's
  own environment)

For installation/setup per operating system see the subsections below. Decker also needs the Cairo library (for SVG
icons); the Windows and macOS steps below install it.

What is verified: the CI workflow (`.github/workflows/ci.yml`) runs the test suite on Ubuntu, Windows and macOS runners and in Fedora and Arch Linux containers
using the steps below, and they pass. CI has no Stream Deck attached, so nothing here is verified with real hardware
off Linux (Arch/Manjaro). The steps for installing on your own Windows or macOS machine are what the CI runners
needed; the maintainer has not verified them on a user machine.

### Debian/Ubuntu

`sudo apt-get update && sudo apt-get install -y libhidapi-libusb0`

### Fedora

`sudo dnf install hidapi`

### Arch Linux

`sudo pacman -S hidapi`

### Linux device permissions (udev)

Without a udev rule, only root can open the Stream Deck. The conventional approach (not verified on every
distribution) is a rule for the Elgato vendor id `0fd9`, for example in `/etc/udev/rules.d/70-streamdeck.rules`:

```
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", TAG+="uaccess"
KERNEL=="hidraw*", ATTRS{idVendor}=="0fd9", TAG+="uaccess"
```

Then reload the rules and replug the device:

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

`uaccess` gives the user at the active session access. On systems without logind, use a group instead, for example
`MODE="0660", GROUP="plugdev"` in place of `TAG+="uaccess"`, and add yourself with `sudo usermod -aG plugdev $USER`
(log out and in again).

### Windows

CI uses MSYS2 for the native libraries; install [MSYS2](https://www.msys2.org/), then in an MSYS2 MINGW64 shell:

```bash
pacman -S mingw-w64-x86_64-cairo mingw-w64-x86_64-hidapi
```

Put `<msys2 folder>\mingw64\bin` on `PATH` so Python finds `libcairo-2.dll` (CI proves Cairo is needed: the SVG tests run there). CI installs hidapi too but never
loads it, since no test enumerates devices. Install
[uv](https://docs.astral.sh/uv/). Device permissions and drivers on Windows are unverified.

### macOS

```bash
brew install hidapi cairo
```

Homebrew's libraries are outside the default library search path, so if Python cannot find Cairo (`no library called
"cairo-2" was found`), set `DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix)/lib"` before starting Decker (CI does
this). Install [uv](https://docs.astral.sh/uv/) as well. Device permissions on macOS are unverified.

## Plugins

Key actions and icon packs come from plugins, shipped as `.deckerplugin` packages. Each plugin runs in its own
process, so a misbehaving plugin cannot take the server down. Plugins run with your user's permissions and are not
sandboxed: only install plugins you trust.

```bash
poe cli plugin new com.example.hello          # scaffold a plugin
poe cli plugin pack com.example.hello         # build com.example.hello-0.1.0.deckerplugin
poe cli plugin install com.example.hello-0.1.0.deckerplugin
poe cli plugin list
poe cli plugin remove com.example.hello
```

You can also install from Settings, Plugins in the client, or by dropping a package on the main window. Installing
is only allowed from the server's own machine unless `server.allow_remote_plugin_install` is `true`.

Plugins can also come from repositories: Settings, Plugins, "Get More Plugins…" lets you search, install and update
plugins from the repositories you have added (the default is `https://valsr.github.io/decker-plugins/index.json`).
Decker checks them for updates daily, weekly (default), monthly or only on demand and shows a notification when updates
are available. A repository can provide any plugin and plugins run with your user's permissions, so only add
repositories you trust. See [plugin repositories](docs/plugins/repositories.md), including how to host your own.

Writing a plugin: see the [plugin documentation](docs/plugins/README.md) (package format and manifest, settings
schema, protocol, Python SDK and limits).

## Contributing

Maybe later

## Note

This application is not affiliated with Elgato and/or any of their products and services.
