# Screensaver and brightness — design

Status: awaiting approval. Size: project (one repo: `decker`).

## Intent

Like the Elgato software, an idle deck should be able to show a picture (or go dark) and dim itself, then come back
untouched on a key press. The picture can be laid across the whole deck face so the keys look like a window onto it:
the strips of image that would sit under the plastic gaps between keys are cut out. The Decker server is the product
and the client is a UI frontend, so the screensaver must run with **no client connected**.

## Decisions taken with the user

- **Per device** settings, edited from the client's settings menu.
- **Content:** none (dark), a single image (JPEG, PNG, SVG rasterised to the deck's size), or a **gallery** (a folder of
  images).
- **Image scaling:** center or stretch.
- **Bezel gaps:** an option that cuts the gaps out of the picture so it looks underlaid. The user measures about 4 mm
  between keys that are 16 mm x 16 mm.
- **Gallery rotation:** change every X minutes, or once per activation ("every time the screensaver kicks in").
- **Triggers:** an idle timeout in minutes (**0 disables**), and RPCs that activate it instantly.
- **Brightness:** a normal brightness and a screensaver brightness, per device.
- **Approach A:** a server-side overlay on the existing hardware path (see Approaches). The first key press that wakes
  the deck is **swallowed**.

## Goals

- Idle timeout per device; instant activate/deactivate by RPC; waking by key press or RPC.
- Image and gallery content with center/stretch scaling and the bezel cut-out, rendered once per activation (and per
  gallery advance), not per frame.
- Two per-device brightness values applied on the hardware, including on open and reopen of a device.
- Works headless, on every platform tier (Pillow only; no new dependencies).
- A preview in the client settings so the bezel and scaling can be tuned without waiting for the timeout.

## Non-goals

- Animated screensavers (GIF/video): a static first frame only.
- Scheduling by time of day, or activating on lock/sleep/focus events.
- Uploading images from a remote client: image and folder paths are server-side and set only by loopback clients.
- A shuffle option or per-image dwell times (gallery is sorted by file name, wraps around).
- Per-key or per-profile screensavers.

## Anti-goals

- Waking must never fire an action: no key press that wakes the deck reaches pages, plugins or clients.
- The screensaver must never alter stored pages, key images or profile state. Waking restores exactly what was showing.
- A bad image or missing folder must not break the deck: it falls back to dark, with the reason reported.

## Approaches

- **A. Server-side overlay on the hardware path (chosen).** On activation the server stops animations, writes per-key
  slices directly to the device and sets the screensaver brightness. Page state is untouched; waking re-shows the
  active page via `DeviceManager.show_page`. Smallest change; cost: the overlay needs an explicit write gate.
- **B. A virtual screensaver page.** Reuses page switching, but pollutes the page/profile model and fights app rules
  and plugin page switches. Rejected.
- **C. Client-side rendering.** Fails the headless requirement. Rejected.

## Design

### Settings model (`decker.common.model`)

`ScreensaverSettings` (frozen dataclass, per device, defaults in brackets):

- `brightness: int` [100] normal brightness, 1-100.
- `timeout_minutes: int` [0] 0 = never activate on idle; 1-1440.
- `saver_brightness: int` [10] 0-100 (0 turns the backlight off).
- `content: "none" | "image" | "gallery"` [`none`].
- `image_path: str`, `folder_path: str` [empty], at most 1024 chars.
- `scaling: "center" | "stretch"` [`center`].
- `bezel: bool` [`false`], `key_mm: float` [16.0], `gap_mm: float` [4.0] (key_mm 5-60, gap_mm 0-30).
- `gallery_mode: "interval" | "activation"` [`activation`], `gallery_minutes: int` [5] (1-1440).

Server-side validation clamps nothing silently: out-of-range or unknown values are rejected with an error.

### Server components (`src/decker/server/screensaver/`)

- **`screensaver_store.py` `ScreensaverStore`:** table `screensaver_settings(device_id PRIMARY KEY, settings_json)` in
  `decker.db` (same pattern as `AppRuleStore`); missing row = defaults; deleting a device is not expected.
- **`compose.py`:** pure functions, no hardware. `canvas_layout(rows, cols, key_px, bezel, key_mm, gap_mm)` gives the
  canvas size and each key's crop box; `compose(image, layout, scaling) -> list[PIL.Image]` returns one image per key.
  With the bezel on, `gap_px = round(key_px * gap_mm / key_mm)` and key `(r, c)` crops at
  `(c * (key_px + gap_px), r * (key_px + gap_px))`; with it off, gaps are 0. The picture is rasterised/decoded to the
  canvas size: **center** keeps aspect ratio, scales to cover the whole canvas and crops the excess; **stretch**
  distorts to fill. Rendering reuses `AssetRenderer` for SVG/PNG/JPEG. Files over 20 MiB or beyond a pixel cap are
  refused.
- **`source.py`:** resolves what to show: `next_image(settings, state) -> bytes | None` (single image, or the gallery's
  next sorted file, rescanned at each advance, unreadable files skipped, wrapping).
- **`screensaver_controller.py` `ScreensaverController`:** owns settings validation, caps, RPC-facing methods and the
  `screensaver_changed` / `screensaver_settings_changed` events.
- **`screensaver_engine.py` `ScreensaverEngine`:** per-device runtime state (`idle deadline`, `active`, `gallery
  index`, `last error`) and one scheduler thread using monotonic time. `note_activity(device_id)` pushes the deadline
  out; `activate(device_id)` renders slices off the hardware thread, takes the write gate, stops animations, writes the
  slices and sets the screensaver brightness; `deactivate(device_id)` releases the gate, restores brightness and calls
  `show_page` for the active page. The scheduler also advances the gallery in interval mode.

### Hooking into the device path

- **Write gate:** `DeviceManager` gets `set_overlay(device_id, active)`. While set, every content write from the
  sink/page state for that device (`set_image_bytes`, `clear_key_image`, `play_animation`, titles) updates cached
  state as usual but is **not sent** to hardware. Only the engine's own writes bypass the gate.
- **Key events:** in `DeviceManager._on_hw_key_event` (one place): call `engine.note_activity` for every event; if the
  device is active, swallow the event (do not call `Device.on_key_event` or the callback), deactivate on the press,
  and also swallow that key's matching release so a stale up never reaches a page.
- **Brightness:** `Device.set_brightness(percent)` calls the deck. Normal brightness is applied when a device is opened
  or reopened and on settings change; the screensaver value only while active.
- **Server shutdown while active:** a normal stop wakes every active device (normal brightness, active page). A crash
  cannot: the deck keeps showing the last thing written, at screensaver brightness, until a server starts again.
- **Reopen while active** (hot-plug): the deck comes back awake with normal brightness; the engine treats it as
  activity (deactivates, resets the deadline).
- **Interaction with other features:** profile/page switches (manual, plugin or app rule) while active only change
  state; waking shows whatever is then active. Window focus events do not count as activity. Active state is never
  persisted: a server restart starts awake.

### RPC and events (`service.py`, all through the usual `@api_response`)

- `screensaver_get(device_id)`: settings plus runtime status (`active`, `last_error`).
- `screensaver_set(device_id, settings_json)`: validate, store, apply brightness, reschedule; loopback-only when it
  changes `image_path` or `folder_path`; never activates by itself.
- `screensaver_activate(device_id)` / `screensaver_deactivate(device_id)`: instant, work even when timeout is 0.
- `screensaver_preview(device_id, settings_json)`: PNG of the composed canvas with the gaps shown dark, for the editor
  (loopback-only for paths, same as set). Preview paths use the same size and pixel caps.
- Events: `screensaver_changed(device_id, active)` and `screensaver_settings_changed(device_id)`.
- The CLI client discovers these through `commands()` with no change.

### Client

- `ConnectionManager` typed methods and events for the above; `MainWindow` forwards them like the app-rule events.
- `SettingsDialog` gets a per-device "Device" section (device chosen from the existing device selector): brightness,
  timeout, content type, file/folder pickers (loopback-connected only; disabled with a hint for remote), scaling,
  bezel with key and gap in mm, gallery mode and minutes, a live preview, and "Activate now".
- Server-side errors (missing file, unreadable folder) show under the Activate button from `last_error`.

### Errors and limits

- Missing or unreadable image/folder at activation: dark screen at the screensaver brightness; `last_error` is set and
  logged once per activation.
- Gallery with no readable image behaves the same.
- Rendering runs outside any hardware lock; a wake during rendering cancels the activation before it writes.
- Caps: path length 1024 chars; image file 20 MiB; decoded pixels capped at 24 MP.

### Docs and tests

- New `docs/screensaver.md` (settings, RPC and event reference, bezel geometry, limits); README platform table row
  "Screensaver and brightness"; `docs/platform-support.md`; CLAUDE.md server/client bullets.
- Tests: `compose` geometry and scaling against known pixels; store round trip; engine timing with an injectable clock
  and a fake device manager; swallowed-press behaviour through the real `_on_hw_key_event`; write gate with plugin
  writes during activation; RPC validation including the loopback gate over a real RPyC connection; client dialog
  tests offscreen. No real hardware is touched in tests.

## What is left to the builder

Module split inside `server/screensaver/`, exact event payload shapes, preview image size, the dialog's layout, and
whether the scheduler is one thread or a timer per device.

## My calls (not discussed with the user)

1. **Center means cover:** keeps aspect ratio, fills the canvas, crops the excess (so no letterboxing). Stretch distorts.
2. **Paths are server-side and loopback-only** (no remote upload), consistent with plugin install.
3. **Only key presses count as activity;** focus changes and page switches do not.
4. **Content "none" exists** so the screensaver can simply dim/blank the deck.
5. **Gallery is sorted by file name, not shuffled**, and rescanned at each advance.
6. **Bezel defaults are 16 mm keys and 4 mm gaps for every model;** other models can be edited per device.
7. **A preview RPC is included** to tune the bezel; it can be dropped if it costs too much.
8. **Screensaver brightness 0 is allowed** (backlight off).
