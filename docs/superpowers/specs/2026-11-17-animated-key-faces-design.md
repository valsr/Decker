# Animated key faces (GIF) — design

Status: draft for approval. Size: project (one repo: `decker`).

## Intent

Let a key face be an animated GIF, with a hard guarantee that a deck full of animated keys never lags: key presses stay
responsive, static updates (page switches, plugin `set_image`) are not starved, and the USB link is never saturated. The
way this is achieved is an adaptive, per-device write scheduler that measures its own load and sheds quality and then
frame rate on the fly.

## Measured facts this design rests on

Measured on the attached Stream Deck XL (96x96 keys, 32 keys, USB high-speed, interrupt OUT endpoint 512 B / 125 us),
using the project's `streamdeck` library with a single writer thread and the test GIF (`src/decker/assets/Happy Cat GIF.gif`:
480x370, 12 frames, 100 ms each, 1.1 MB).

- `StreamDeck.set_key_image` **blocks until every report is on the wire**. A report is always 1024 B (8 B header, 1016 B
  image data, zero padded). Sustained throughput was **3998 reports/s = 4.09 MB/s**, i.e. the endpoint's theoretical
  maximum (2 packets per report, 8000 microframes/s), independent of key count (1, 8 or 32 keys) and frame size.
  One report costs 0.25 ms of writer-thread time; timing is steady (p99 within a few percent of the median).
- `PILHelper.to_native_key_format` hard-codes JPEG quality 100. Per frame (96 px): q100 = 6.4-6.7 KB = about 6.75
  reports (1.69 ms); q90 = 2.5-2.7 KB = 3 reports (0.75 ms); q80 = 2 reports.
- All 32 keys at the GIF's native 10 fps needs 2160 reports/s (54% of the link) at q100 or 960 reports/s (24%) at q90.
- Not measured: whether the deck's own JPEG decoder keeps pace at these rates (writes are accepted at link speed, but
  the screen was not observed), and other models (Mini uses ~19 KB BMP frames, 6 keys; Original 72 px; Plus 120 px).
  The controller must therefore not assume the XL's numbers.

A throwaway benchmark produced these numbers; a cleaned-up version is kept in `scripts/bench_usb_writes.py` so the
figures can be re-derived on other models (see Calls).

## Goals

- GIF key faces play with correct frame timing, composed with the key's background and title exactly like static images.
- **Write-time budget:** animation plus static writes use at most 75% of writer-thread time per device, measured as time
  spent inside `set_key_image` divided by wall time.
- **Adaptive:** the scheduler measures the real cost of a report and adjusts a single quality/frame-rate "level" per
  device, in both directions, without a restart (see Controller).
- **Predictable cost:** all decoding, scaling, composing and JPEG encoding happens once per (GIF, appearance, key size,
  quality) and is cached; playback only sends cached bytes.
- Works on every key-LCD model the library supports (XL, Original/V2, Mini, Neo, Plus keys), including BMP-format decks.
- GUI: key buttons in the grid animate; the editor preview shows the first frame.

## Non-goals

- Animated WebP/APNG input; video; audio.
- A user-facing way to import/upload a GIF (the icon picker's file chooser and `~/.decker/assets/user-icons` are not
  wired into key faces today). Decided by the user: this is the next piece of work, not part of this project.
- Per-GIF fps overrides or a user-visible quality setting; fixing the stretch-to-square behaviour for non-square images
  (the test GIF will look slightly squashed, as non-square PNGs do today).
- Touch strip / LCD strip animation (Plus, Neo).

## Anti-goals (a failure even if it "works")

- Key-press latency or static-update latency getting worse while animations run.
- The write scheduler oscillating visibly between quality levels.
- Unbounded memory growth from GIF frame caches or unbounded GIF decode time/size.
- A bad GIF or a write error taking down the writer, the server, or other keys.

## Approaches considered

- **A. One writer per device owning every write (chosen).** A single writer thread and scheduler per device handles static
  and animated writes alike, measures busy time, and hosts the controller. Cost: changes how `Device.set_image_bytes`
  is called (static writes route through the writer) — a larger but contained diff.
- **B. A separate animator thread beside today's direct writes.** Smaller diff, but the controller cannot see static writes
  (so the 75% budget is wrong exactly when a page switch lands) and two threads contend for the same USB channel.
- Rejected: per-key timers (no budget, lag under load); plugins streaming frames (JSON/base64 per frame through a pipe).

Chosen by the user: A.

## Design

### Components (names are suggestions)

- **`animation` package** (server side, no Qt): `gif.py` (decode), `frames.py` (cache), `writer.py` (per-device writer +
  scheduler), `controller.py` (levels and feedback loop). Pure logic takes an injectable clock and a `write(key, bytes)`
  callable so everything is testable without hardware.
- **GIF decode:** Pillow `ImageSequence`, composited to full RGBA frames honouring disposal and transparency; per-frame
  delay in ms, with delays below 20 ms clamped to 100 ms (browser behaviour); loop forever. Caps (constants, see Calls):
  max file size is the shared 4 MiB `MAX_ICON_BYTES`, max 300 frames, existing `MAX_RASTER_PIXELS` per frame. Over any cap, or a decode error, the key
  shows the first frame as a static image and a warning is logged once per GIF.
- **Composition:** each GIF frame replaces the plugin/icon image layer in `compose_key_image` (same background, scale
  `PACK_ICON_SCALE` for pack icons, title, tint rules as static images). Result: a list of `Frame(native_bytes, reports,
  delay_ms)` plus a **poster** (first composed frame as PNG).
- **Frame cache:** LRU bounded by total bytes (default 64 MiB). Key: (SHA-256 of the GIF bytes, hash of the resolved
  appearance, width, height, quality). Shared across keys and pages: the same GIF on 32 keys is encoded once. Encoding for
  a missing entry runs off the writer thread; the poster is shown immediately and playback starts when ready. The cache
  holds the current quality plus at most the adjacent levels actually requested.
- **Native encoding:** produced by Decker (not `PILHelper.to_native_key_format`) so quality is a parameter; rotation/flip/
  size come from `key_image_format()` as in the library. BMP decks have no quality dimension.

### Writer and scheduler (per device)

- One daemon writer thread per open `Device`. All hardware image writes for that device go through it:
  `Device.set_image_bytes`, `clear_key_image`, and animation frames.
- Priority: queued static writes first (they are user-visible changes and rare), then animation frames by earliest
  deadline. Static writes to a key cancel that key's animation slot; starting an animation replaces it.
- Static writes stay synchronous for callers: the caller submits to the writer and waits for completion (bounded
  timeout), so `DeckerService.set_image` still returns whether the image was sent and `DeviceManager.set_image_bytes`
  can still read back the rendered image to persist it right after.
- An **animation slot** per key holds the frame list, a start time and the current level's frame-rate cap. The frame to
  show is chosen by the clock (`index = f(now - start)`), never by counting writes: a late writer skips frames instead of
  building a backlog and never plays slow-motion. Consecutive identical frames and frames already shown cost nothing (the
  existing "shown" de-duplication generalises).
- Only keys on the **active page of the open device** have slots. `DeviceManager.show_page` drops all slots and
  re-attaches animations for keys whose state records an animation (kept in memory beside the cached PNG, which stays the
  poster); after a server restart the plugin host recomposes keys as it does today, which restarts playback.
- Errors per write are caught and logged as today; a failing animation slot is dropped without affecting other keys; the
  writer survives write exceptions and the existing device-closed handling still applies.

### Controller (per device)

State: the current **level**, the measured **seconds per report** (EWMA, seeded 0.25 ms; for BMP decks measured the same
way), and a sliding series of 1 s buckets of busy fraction and frame lag.

Levels, highest cost first (frame-rate caps never exceed a GIF's native rate; caps apply uniformly to all animated keys):

    L0 q100/native   L1 q90/native   L2 q90/30   L3 q90/20   L4 q90/15   L5 q90/10   L6 q75/10   L7 q75/5

Degrade quality first (q100 to q90 is nearly invisible at key size and saves 2.2x), cap frame rate second; restore in the
reverse order (frame rate before quality). BMP decks use only the frame-rate rungs.

Rules:

1. **Step down one level** when the 5 s mean busy fraction exceeds **75%**.
2. **Fast path:** if frames are more than **250 ms** behind schedule for 1 s, step down immediately.
3. **Step up one level** only if the 20 s mean busy fraction is below **50%**, at least **30 s** have passed since the last
   step down, **and** the projected busy fraction at the next level is at most **65%**.
   `projected = busy x cost(next level) / cost(current level)`, with level cost = reports per frame x frame rate summed
   over the active animated keys, using the measured seconds per report.
4. **Re-plan** immediately (no cooldown, both directions) when the set of animated keys changes (page switch, key
   assigned or cleared, GIF finished encoding): pick the lowest-numbered level whose projection is at most 75%.
5. The busy fraction includes static writes, so plugin updates and page-switch bursts are accounted for; the 5 s window
   keeps a single page switch (about 230 reports, roughly 60 ms) from triggering a step.
6. Log each level change at INFO with the busy fraction and cause.

Initial level at device open: the rule-4 plan with the seeded cost.

| 32 keys, GIF native rate | q100 | q90 | Expected level |
|---|---|---|---|
| 10 fps | 54% | 24% | L0 |
| 24 fps | 130% | 58% | L1 (step up blocked: q100 projects to 130%) |
| 50 fps | 270% | 120% | about L2 (q90, 30 fps cap, about 72%) |

Known blind spots: the controller cannot see the deck dropping frames after the host's write completes, nor CPU
saturation; the unused 25% is the margin.

### GUI

- The `key_state_changed` event and `get_key_display_states` keep returning the poster as `image_b64`, and gain
  `animation_id` (the frame-cache key) when the key is animated.
- New RPC `key_animation(animation_id)` returns the **composed** animation (background, title, scaling baked in) as an
  animated WebP built from the cached composed frames (at full quality, not the deck's quality level); fall back to
  animated GIF if Qt's WebP plugin is unavailable (builder verifies). The client fetches only for keys visible in the grid,
  caches by id, and plays it with `QMovie`; movies stop when the view is hidden or the key leaves the page.
- This replaces the earlier idea of playing the raw GIF with `QMovie` in the client, which would lose the background and
  title composition. Frames are not streamed per frame over RPC.
- The editor's draft preview (`key_preview`) shows the poster only.

### Where a GIF can come from

Everywhere an icon image already flows through `compose_key_image`: pack icons (`.gif` added to the pack image suffixes),
manifest/state images, and plugin `set_icon`/`set_image` bytes (content-hash cached). The user decided to raise
`MAX_ICON_BYTES` (`src/decker/plugin/icons.py`, used by `asset/iconpack.py` and `asset/systemicons.py`) from 256 KiB to
**4 MiB** for all icon images: one limit, no separate GIF constant. The per-frame pixel cap (`MAX_RASTER_PIXELS`) still
bounds decode cost for static images. The unrelated 512 KiB limit on downloading a plugin's icon from a repository index
(`server/repositories.py`) is unchanged. Docs in `docs/plugins/` (`limits.md`, package format) are updated. There is no
user import path yet (Open items).

### Configuration

New server settings under an `animation` section, following the repository's existing config conventions:
`enabled` (default true; false renders first frames only), `budget_percent` (75), `cache_mb` (64). Everything else
(thresholds, ladder) is a constant.

## Constraints

- Python 3.14, existing dependencies only (Pillow, `streamdeck`, PyQt6); no new runtime dependencies.
- Quality gates from `CLAUDE.md`: `poe format`, `poe mypy`, `poe pylint` (at least 9.0), `poe test` (coverage at least 85%).
- Server stays headless (no Qt in `animation`); plugin processes stay out-of-process; loopback/RPC rules unchanged.
- `docs/plugins/` stays in sync with protocol, manifest and limit changes.

## Testing

- Unit tests with an injected fake clock and a fake writer: ladder order, projection arithmetic, hysteresis and cooldown,
  fast path, re-plan on key-set changes, EDF scheduling and frame skipping, static-write priority, slot cancellation.
- GIF decoding: disposal methods, transparency, delay clamp, caps and fallback to a poster.
- Frame cache: sharing across keys, byte-bounded LRU eviction, appearance-change invalidation.
- Fake `StreamDeck` with scripted per-report latency to run the whole writer + controller loop deterministically,
  including an overload scenario that must settle at a lower level and recover when load drops.
- Client: animated-state handling and `QMovie` lifecycle (offscreen Qt), RPC returns a playable animation.
- Manual: the benchmark script on the real deck, then the test GIF on all 32 keys, with the screen observed for tearing or
  dropped frames.

## Calls made without the user (change any)

- Ladder rungs, window lengths (5 s / 20 s / 30 s / 250 ms), thresholds (75 / 50 / 65%), caps (300 frames,
  64 MiB cache; the 4 MiB icon size limit is the user's decision), the 20 ms delay clamp, the animated WebP transport, and the editor preview showing the poster.
- Per-device (not global) budgeting, because each deck has its own USB endpoint.
- Keeping the cleaned-up benchmark in `scripts/bench_usb_writes.py`.
- The design doc is left uncommitted.

## Open items

- None. The user decided that **GIF import** (how a user gets their own GIF onto a key; today the picker's file chooser
  copies to `~/.decker/assets/user-icons` but its result is not used by the key-face ref system) is the **next piece of
  work**, a separate project. Until then GIFs reach keys through icon packs (once `.gif` is allowed) and plugin
  `set_icon`/`set_image`, and the test GIF is exercised through a test fixture or dev icon pack.

## Left to the builder

Module and class names, thread/queue primitives, the exact EWMA constants and bucket handling, the BMP-deck level table,
the animated WebP/GIF encoder settings, event/RPC field names beyond those above, and test file layout.
