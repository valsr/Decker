# Animated Key Faces (GIF) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Play animated GIFs as key faces on Stream Deck hardware, with a per-device write scheduler that keeps USB write time at or under 75% by adaptively lowering JPEG quality and then frame rate.

**Architecture:** A new server-side `decker.animation` package decodes GIFs once, composes and encodes frames once per (GIF, appearance, key size, quality) into a byte-bounded cache, and plays them through one writer thread per device that owns every hardware image write, measures its own busy time and runs a feedback controller over a fixed quality/frame-rate ladder. The plugin host hands animated keys to the writer; the client plays a server-composed animated WebP with `QMovie`.

**Tech Stack:** Python 3.14, Pillow, `streamdeck` library (stubs in `.stubs/`), PyQt6, RPyC, pytest + assertpy.

**Spec:** `docs/superpowers/specs/2026-11-17-animated-key-faces-design.md` (read it first; this plan only records decisions the spec leaves to the implementer).

## Global Constraints

- Python `^3.14`; no new runtime dependencies (Pillow, `streamdeck`, PyQt6 only).
- Quality gates before any task is done: `poe format`, `poe mypy`, `poe pylint` (score at least 9.0), `poe test` (coverage at least 85%).
- black line length 120, isort `black` profile; annotate every parameter, return and instance attribute; docstrings only on public classes/functions (one short line); methods under 50 lines; at most 5 arguments per function.
- Tests: pytest + assertpy, files mirror the source layout under `tests/`; do not mock infrastructure beyond a fake `StreamDeck`.
- Server stays headless: no Qt in `src/decker/animation/`. Plugin processes stay out-of-process. Client never touches hardware.
- Write budget 75% of writer-thread time per device. Controller constants: down when 5 s mean busy is above 75%; fast path when frames are more than 250 ms late for 1 s; up only when 20 s mean busy is below 50%, 30 s after the last step down, and projected busy is at most 65%.
- Ladder (highest cost first): `q100/native, q90/native, q90/30, q90/20, q90/15, q90/10, q75/10, q75/5`; BMP decks use only the frame-rate rungs.
- `MAX_ICON_BYTES` becomes 4 MiB (4 * 1024 * 1024) for all icon images; GIF cap 300 frames; frame delays below 20 ms become 100 ms; frame cache default 64 MiB; settings `animation.enabled` (true), `animation.budget_percent` (75), `animation.cache_mb` (64).
- Static key writes stay synchronous for callers (submit to the writer and wait, bounded timeout).
- Stage explicit file paths only in every commit (never `git add .` or `-A`); work on a new branch `feat/animated-key-faces` created from `main`.

## Review Focus

Failure modes the spec implies but its tasks would not otherwise exercise, most likely first:

1. A GIF with a single frame (or one that decodes to one frame) must behave as an ordinary static image: no animation slot, no writer scheduling. Pinned in Task 2 and Task 9.
2. A corrupt, truncated, over-300-frame or over-size GIF must fall back to its first frame as a static image, log one warning, and never raise into the plugin host or affect other keys. Pinned in Task 2 and Task 9.
3. A write that raises for one key (deck unplugged, USB error) must not kill the writer thread or stop other keys' animation. Pinned in Task 6.
4. A page switch while animations play must leave no writes to the old page's keys after `show_page` returns, and a static write racing an animation frame on the same key must win. Pinned in Task 6 and Task 8.
5. `Device.close()` / server shutdown with a busy writer must return promptly (no hang), and degenerate delays (0 ms, one 60 s frame) must not busy-loop or stall playback. Pinned in Task 2 and Task 6.

---

### Task 1: Raise the icon limit and accept `.gif` in icon packs

**Files:**
- Modify: `src/decker/plugin/icons.py` (`MAX_ICON_BYTES`)
- Modify: `src/decker/asset/iconpack.py` (`_IMAGE_SUFFIXES`)
- Modify: `docs/plugins/limits.md`, `docs/plugins/package-and-manifest.md` (4 MiB limit, `.gif` allowed in packs, GIFs animate on keys)
- Test: `tests/asset/test_iconpack.py`, `tests/plugin/` (the existing icon-reading test module; add there)

**Interfaces:**
- Produces: `MAX_ICON_BYTES: int = 4 * 1024 * 1024`; `.gif` files appear in `IconPackStore` listings and are served by `read_icon`.

- [ ] **Step 1: Write failing tests**
  - `test_gif_is_listed_and_served_from_a_pack`: a pack folder with `a.gif` lists `a.gif` and `read_icon(pack_id, "a.gif")` returns its bytes.
  - `test_icon_of_3_mib_is_served_and_5_mib_is_refused`: assert on `read_icon` for both sizes; same for `plugin.icons.read_icon`.
- [ ] **Step 2: Run** `poe test -- tests/asset/test_iconpack.py` — Expected: FAIL (gif not listed, 3 MiB refused).
- [ ] **Step 3: Implement** the two constant changes; update the two docs pages. Leave `server/repositories.py`'s 512 KiB download limit untouched.
- [ ] **Step 4: Run** the same tests plus `tests/asset/test_systemicons.py` — Expected: PASS (update any existing assertion that hard-codes 256 KiB).
- [ ] **Step 5: Commit** `git add src/decker/plugin/icons.py src/decker/asset/iconpack.py docs/plugins/limits.md docs/plugins/package-and-manifest.md tests/asset/test_iconpack.py <plugin icons test> docs/superpowers/specs/2026-11-17-animated-key-faces-design.md docs/superpowers/plans/2026-11-17-animated-key-faces.md` then `git commit -m "feat: allow GIF icons and raise icon limit to 4 MiB"`.

### Task 2: GIF decoding

**Files:**
- Create: `src/decker/animation/__init__.py` (empty), `src/decker/animation/gif.py`
- Test: `tests/animation/__init__.py`, `tests/animation/test_gif.py`

**Interfaces:**
- Produces:
  - `MAX_GIF_FRAMES = 300`, `MIN_FRAME_DELAY_MS = 20`, `DEFAULT_FRAME_DELAY_MS = 100`
  - `class GifError(ValueError)`
  - `@dataclass(frozen=True) class GifFrame: image: Image.Image; delay_ms: int` (`image` is a full-canvas RGBA frame with disposal and transparency already applied)
  - `def is_gif(data: bytes) -> bool` (magic `GIF87a`/`GIF89a`)
  - `def is_animated_gif(data: bytes) -> bool` (is a GIF and `n_frames > 1`; False on any Pillow error)
  - `def decode_gif(data: bytes) -> list[GifFrame]` (raises `GifError` for more than `MAX_GIF_FRAMES` frames, a frame above `MAX_RASTER_PIXELS`, or undecodable data)

- [ ] **Step 1: Write failing tests** (generate GIFs with Pillow `save_all=True`)
  - `test_delays_below_20ms_become_100ms`: durations `[0, 10, 50]` decode to `[100, 100, 50]`.
  - `test_disposal_restore_to_background_clears_previous_frame`: frame 2 with disposal 2 shows only its own pixels over transparency.
  - `test_transparent_pixels_stay_transparent_in_rgba`: alpha 0 at a known pixel.
  - `test_single_frame_gif_is_not_animated`: `is_animated_gif` False, `decode_gif` returns one frame.
  - `test_more_than_300_frames_raises_gif_error`, `test_corrupt_bytes_raise_gif_error`, `test_non_gif_bytes_are_not_gifs`.
  - `test_total_duration_is_never_zero`: a one-frame-per-0 ms GIF still yields a positive sum (guards the busy-loop in Review Focus 5).
- [ ] **Step 2: Run** `poe test -- tests/animation/test_gif.py` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `gif.py` with Pillow `ImageSequence`, compositing each frame over the previous canvas per Pillow's `disposal_method`; check frame count before decoding pixels.
- [ ] **Step 4: Run** the tests — Expected: PASS.
- [ ] **Step 5: Commit** `git add src/decker/animation/__init__.py src/decker/animation/gif.py tests/animation/__init__.py tests/animation/test_gif.py` then `git commit -m "feat: decode animated GIFs into composited frames"`.

### Task 3: Frame composition and native encoding

**Files:**
- Modify: `src/decker/server/appearance.py` (`compose_key_image`: extract the layer-compositing core)
- Create: `src/decker/animation/encode.py`
- Test: `tests/server/test_appearance.py`, `tests/animation/test_encode.py`

**Interfaces:**
- Consumes: `GifFrame` from Task 2.
- Produces:
  - `appearance.compose_key_frames(appearance: Mapping[str, Any], frames: Sequence[Image.Image], plugin_title: str, size: int = 144, plugin_image_scale: float = 1.0) -> list[Image.Image]` — RGB images, same background/scale/title treatment as `compose_key_image` (which now delegates to a shared private helper; its output must not change).
  - `@dataclass(frozen=True) class KeyFormat: size: tuple[int, int]; image_format: str; rotation: int; flip: tuple[bool, bool]` with `@classmethod from_deck(cls, fmt: Mapping[str, Any]) -> KeyFormat` (reads `key_image_format()`'s `size`, `format`, `rotation`, `flip`).
  - `encode.encode_native(image: Image.Image, fmt: KeyFormat, quality: int) -> bytes` — scale to `fmt.size`, apply rotation then flips as `PILHelper` does, JPEG at `quality` (BMP ignores it).

- [ ] **Step 1: Write failing tests**
  - `test_first_composed_frame_equals_static_composition`: for one frame, `compose_key_frames(...)[0]` pixel-equals the decoded PNG from `compose_key_image` with the same appearance and image.
  - `test_title_and_background_are_drawn_on_every_frame`.
  - `test_existing_compose_key_image_output_is_unchanged` (reuse an existing appearance test as the regression).
  - `test_quality_90_is_smaller_than_100_for_the_same_frame` (use a noisy 96x96 image).
  - `test_rotation_and_flip_follow_the_deck_format`: a marker pixel lands where `PILHelper` would put it.
  - `test_bmp_format_ignores_quality`.
- [ ] **Step 2: Run** `poe test -- tests/animation/test_encode.py tests/server/test_appearance.py` — Expected: FAIL.
- [ ] **Step 3: Implement** both pieces; `encode_native` must not call `PILHelper.to_native_key_format` (it hard-codes quality 100).
- [ ] **Step 4: Run** the tests — Expected: PASS.
- [ ] **Step 5: Commit** `git add src/decker/server/appearance.py src/decker/animation/encode.py tests/server/test_appearance.py tests/animation/test_encode.py` then `git commit -m "feat: compose and encode key frames with explicit JPEG quality"`.

### Task 4: Animation model, size-bounded cache and factory

**Files:**
- Create: `src/decker/animation/model.py`, `src/decker/animation/cache.py`, `src/decker/animation/factory.py`
- Test: `tests/animation/test_cache.py`, `tests/animation/test_factory.py`

**Interfaces:**
- Consumes: `decode_gif`, `GifFrame` (Task 2); `compose_key_frames`, `encode_native`, `KeyFormat` (Task 3).
- Produces (`model.py`):
  - `@dataclass(frozen=True) class AnimationSpec: gif: bytes; appearance: Mapping[str, Any]; title: str; scale: float` with properties `gif_sha: str` and `animation_id: str` (SHA-256 of the GIF plus a stable hash of appearance, title and scale; independent of key size and quality).
  - `@dataclass(frozen=True) class Frame: data: bytes; reports: int; delay_ms: int`
  - `@dataclass(frozen=True) class Animation: animation_id: str; quality: int; frames: tuple[Frame, ...]; poster_png: bytes; reports_by_quality: Mapping[int, float]` with `total_ms -> int` and `frame_index_at(elapsed_ms: int) -> int` (loops forever).
- Produces (`cache.py`): `class SizedLru` — `__init__(self, max_bytes: int)`, `get(key: Hashable) -> Any | None`, `put(key: Hashable, value: Any, size: int) -> None` (evict least recently used until under budget; an entry larger than the budget is not stored), `get_or_build(key, build: Callable[[], tuple[Any, int]]) -> Any` (thread-safe, one build per key at a time), `size_bytes -> int`.
- Produces (`factory.py`): `class AnimationFactory` — `__init__(self, cache_bytes: int, report_payload: int)`; `frames_for(spec: AnimationSpec, fmt: KeyFormat, quality: int) -> Animation | None` (non-blocking: returns the cached animation, or None while a background build — `ThreadPoolExecutor(max_workers=2)` — runs; a failed build is remembered by `gif_sha` so it logs one warning and is not retried); `preview_webp(spec: AnimationSpec) -> bytes | None` (composed at size 144, animated WebP, GIF if Pillow lacks WebP animation; cached by `animation_id` in a second `SizedLru`); `register(spec) -> str` and `spec_for(animation_id: str) -> AnimationSpec | None` (small bounded dict).
- `reports_by_quality` is filled for qualities 100, 90 and 75 by encoding frame 0 at each and using its size ratio against the fully encoded quality.

- [ ] **Step 1: Write failing tests**
  - Cache: `test_evicts_least_recently_used_until_under_budget`, `test_entry_larger_than_budget_is_returned_but_not_stored`, `test_get_or_build_builds_once_under_concurrent_callers`.
  - Model: `test_frame_index_at_follows_cumulative_delays_and_loops` (delays 100, 50: index at 0/99/100/149/150 is 0,0,1,1,0).
  - Factory: `test_same_gif_on_many_keys_encodes_once` (count calls through an injected encoder spy via monkeypatch), `test_changing_the_title_changes_the_animation_id_and_rebuilds`, `test_frames_for_returns_none_until_the_build_finishes_then_the_animation`, `test_corrupt_gif_logs_one_warning_and_returns_none_repeatedly` (caplog), `test_preview_webp_is_a_playable_animation_with_all_frames` (Pillow reopens it, `n_frames` equals the GIF's).
- [ ] **Step 2: Run** `poe test -- tests/animation` — Expected: FAIL.
- [ ] **Step 3: Implement** the three modules per the interfaces.
- [ ] **Step 4: Run** `poe test -- tests/animation` — Expected: PASS.
- [ ] **Step 5: Commit** `git add src/decker/animation/model.py src/decker/animation/cache.py src/decker/animation/factory.py tests/animation/test_cache.py tests/animation/test_factory.py` then `git commit -m "feat: cache composed animation frames by content and appearance"`.

### Task 5: Level controller

**Files:**
- Create: `src/decker/animation/controller.py`
- Test: `tests/animation/test_controller.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Level: quality: int; fps_cap: int | None`
  - `LADDER: tuple[Level, ...]` (the eight rungs from Global Constraints) and `def ladder_for(bmp: bool) -> tuple[Level, ...]` (BMP: the distinct frame-rate rungs only, quality fixed at 100).
  - `Demand = Callable[[Level], float]` — reports per second the active animated keys need at that level.
  - `class LevelController`: `__init__(self, ladder: Sequence[Level], budget: float = 0.75)`; `level -> Level`; `replan(demand: Demand, seconds_per_report: float) -> Level` (lowest-cost-index rung, i.e. the first in the ladder, whose `demand(level) * seconds_per_report` is at most the budget, else the last rung; no cooldown); `tick(now: float, busy_5s: float, busy_20s: float, lag_s: float, demand: Demand, seconds_per_report: float) -> Level` (applies the Global Constraints rules; one step per call; records `now` of the last step down).

- [ ] **Step 1: Write failing tests** (XL numbers: `seconds_per_report = 0.00025`, 32 keys, reports per frame 6.75 at q100, 3 at q90, 2 at q75)
  - `test_replan_for_10fps_picks_L0_24fps_picks_L1_50fps_picks_q90_30` (the spec's table).
  - `test_steps_down_one_rung_when_5s_busy_exceeds_75_percent`.
  - `test_does_not_step_up_before_30s_after_a_step_down`.
  - `test_does_not_step_up_when_projection_exceeds_65_percent` (24 fps: busy 0.58 at L1 projects to 1.30).
  - `test_steps_up_when_20s_busy_below_50_percent_and_projection_fits` (10 fps at L1 with busy 0.24 goes to L0).
  - `test_lag_over_250ms_steps_down_immediately_even_if_busy_is_low`.
  - `test_no_oscillation_over_a_600s_simulated_steady_load` (loop `tick` with constant demand; the number of level changes after settling is zero).
  - `test_bmp_ladder_has_no_quality_change`.
- [ ] **Step 2: Run** `poe test -- tests/animation/test_controller.py` — Expected: FAIL.
- [ ] **Step 3: Implement** as pure logic with no clock or threads; step-up projection is `busy_20s * demand(next) / demand(current)` and is skipped if `demand(current)` is 0.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `git add src/decker/animation/controller.py tests/animation/test_controller.py` then `git commit -m "feat: add adaptive quality and frame-rate level controller"`.

### Task 6: Per-device key writer (scheduler)

**Files:**
- Create: `src/decker/animation/writer.py`
- Test: `tests/animation/test_writer.py`

**Interfaces:**
- Consumes: `Animation`, `Frame` (Task 4).
- Produces `class KeyWriter`:
  - `__init__(self, write: Callable[[int, bytes | None], None], clock: Callable[[], float] = time.monotonic) -> None` — `write(key_index, native_bytes_or_None_to_blank)` is the only hardware call.
  - `submit_static(key_index: int, data: bytes | None, timeout: float = 5.0) -> bool` — queues a static write (None blanks), cancels that key's animation, waits for completion, returns False on timeout or write error.
  - `play(key_index: int, animation: Animation, fps_cap: int | None = None) -> None`, `stop(key_index: int) -> None`, `stop_all() -> None`
  - `step(now: float) -> float | None` — performs at most one write (queued static writes first, then the animation frame with the earliest deadline) and returns the clock time of the next deadline, or None if idle. Frame choice is `animation.frame_index_at` from the slot's start time (skipping late frames, never accumulating a backlog); a frame equal to the one already shown, or a key still inside the fps-cap period (`1 / fps_cap` since its last write), is not written.
  - `start() -> None` (daemon thread looping on `step`, waiting on a condition until the next deadline), `close(timeout: float = 2.0) -> None`.
- A write that raises is logged; the static caller gets False; an animation slot whose write raises is dropped; the thread keeps running.

- [ ] **Step 1: Write failing tests** (fake clock; call `step` directly, no threads, except the last two)
  - `test_static_write_is_served_before_a_due_animation_frame`.
  - `test_earliest_deadline_key_is_written_first`.
  - `test_late_writer_skips_frames_instead_of_replaying_them` (advance the clock 5 frames; exactly one write, with the current frame).
  - `test_fps_cap_limits_writes_per_second` (30 fps cap on a 100 fps GIF writes 30 times in a simulated second).
  - `test_identical_consecutive_frames_cost_no_write`.
  - `test_static_write_cancels_the_keys_animation_and_wins_a_race` (Review Focus 4).
  - `test_failing_write_for_one_key_does_not_stop_other_keys` (Review Focus 3).
  - `test_zero_delay_gif_does_not_make_step_return_a_zero_wait` (Review Focus 5; deadline is strictly in the future).
  - `test_submit_static_returns_false_on_timeout` and `test_close_returns_promptly_while_a_write_is_pending` using a real thread and a blocking `write` released after `close` (Review Focus 5).
- [ ] **Step 2: Run** `poe test -- tests/animation/test_writer.py` — Expected: FAIL.
- [ ] **Step 3: Implement** `writer.py`; keep per-key slot state in a private dataclass; one `threading.Condition` guards queue and slots.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `git add src/decker/animation/writer.py tests/animation/test_writer.py` then `git commit -m "feat: add per-device key writer with deadline scheduling"`.

### Task 7: Controller and load monitoring inside the writer

**Files:**
- Modify: `src/decker/animation/writer.py`
- Create: `src/decker/animation/load.py`
- Test: `tests/animation/test_load.py`, `tests/animation/test_writer_adaptive.py`

**Interfaces:**
- Consumes: `LevelController`, `Level`, `ladder_for` (Task 5); `KeyWriter` (Task 6); `AnimationFactory.frames_for`, `AnimationSpec`, `KeyFormat` (Tasks 3-4).
- Produces (`load.py`): `class LoadMonitor` — `__init__(self, seed_seconds_per_report: float = 0.00025)`; `record_write(now: float, busy_s: float, reports: int) -> None`; `record_lag(now: float, lag_s: float) -> None`; `busy_fraction(now: float, window_s: float) -> float` (1 s buckets); `lag_over(now: float, threshold_s: float, for_s: float) -> bool`; `seconds_per_report -> float` (EWMA).
- Changes to `KeyWriter`: constructor gains keyword-only `controller: LevelController | None = None`, `monitor: LoadMonitor | None = None`, `factory: AnimationFactory | None = None`, `fmt: KeyFormat | None = None`; `play` stays for fixed pre-built animations and a new `play_spec(key_index: int, spec: AnimationSpec, poster_written: bool = True) -> None` is added (the poster is already on the key via `submit_static`; playback starts when `factory.frames_for(spec, fmt, level.quality)` first returns an animation, polled each step); `level -> Level`. Every write is timed with the clock and recorded; `step` runs `controller.tick` at most once per simulated second; the slot set changing (play/stop/ready) triggers `controller.replan`; when the level's quality changes a slot keeps playing its current frames until the factory returns the new quality, then switches; `fps_cap` comes from the level (never above a GIF's native rate, uniform across keys).
- Keep the Task 6 constructor usage working (all new parameters optional) so Task 6 tests stay green.

- [ ] **Step 1: Write failing tests**
  - Load: `test_busy_fraction_over_window`, `test_seconds_per_report_ewma_tracks_measured_cost`, `test_lag_over_requires_sustained_lag`.
  - Writer, with fake clock and a fake `write` that advances the clock by `reports * 0.00025`:
    `test_32_keys_at_10fps_settle_at_L0_and_stay`, `test_overload_steps_down_within_6s_and_recovers_after_load_drops`, `test_page_switch_burst_of_32_static_writes_does_not_change_the_level`, `test_adding_keys_replans_immediately`, `test_quality_change_keeps_playing_old_frames_until_new_quality_is_ready`.
- [ ] **Step 2: Run** `poe test -- tests/animation` — Expected: new tests FAIL, Task 6 tests PASS.
- [ ] **Step 3: Implement** `load.py` and the writer changes.
- [ ] **Step 4: Run** `poe test -- tests/animation` — Expected: PASS.
- [ ] **Step 5: Commit** `git add src/decker/animation/load.py src/decker/animation/writer.py tests/animation/test_load.py tests/animation/test_writer_adaptive.py` then `git commit -m "feat: adapt writer quality and frame rate to measured write load"`.

### Task 8: Route device writes through the writer; page switches

**Files:**
- Modify: `src/decker/server/devices/__init__.py` (`Device`), `src/decker/server/devices/manager.py` (`DeviceManager`), `src/decker/server/devices/state.py` (`DeviceState`), `.stubs/StreamDeck/` (add any used attribute, e.g. `IMAGE_REPORT_PAYLOAD_LENGTH`, if mypy needs it)
- Modify: `src/decker/common/config/defaults.yml` (new `animation` section)
- Test: `tests/server/test_device_drawing.py`, `tests/server/test_device_manager.py`, `tests/server/devices/test_state.py`

**Interfaces:**
- Consumes: `KeyWriter`, `LevelController`, `LoadMonitor` (Tasks 6-7); `AnimationFactory`, `AnimationSpec`, `KeyFormat` (Tasks 3-4).
- Produces:
  - `Device.__init__` unchanged signature; it creates one `KeyWriter` per device lazily on first use (so `set_animation_support`, if called first, can supply the controller, monitor, factory and format), started with the first write, whose `write` callable calls `self._device.set_key_image(key, native)` after `_try_open()`; `Device.set_image_bytes` and `Device.clear_key_image` keep their behavior but perform the hardware write via `submit_static`; the existing `tracker.shown` de-duplication stays. `Device.play_animation(key_index: int, spec: AnimationSpec) -> None`, `Device.stop_animations() -> None`, `Device.close()` closes the writer first.
  - `Device.set_animation_support(factory: AnimationFactory, enabled: bool, budget: float) -> None` called by the manager when opening a device (builds `KeyFormat.from_deck`, `ladder_for(bmp)`, `LoadMonitor`); with `enabled` false, `play_animation` is a no-op (the static poster stays).
  - `DeviceManager.set_animation(device_id: str, key_index: int, spec: AnimationSpec) -> None`; `DeviceManager.create` builds the shared `AnimationFactory(cache_bytes=cache_mb * 1024 * 1024, report_payload=...)` from `animation.cache_mb`, `enabled` from `animation.enabled`, budget from `animation.budget_percent / 100` via `config.get_as_or_default`.
  - `DeviceState.set_key_animation(key_index: int, spec: AnimationSpec | None) -> None`, `DeviceState.get_key_animation(key_index: int) -> AnimationSpec | None`, `DeviceState.get_all_animations() -> dict[int, AnimationSpec]` (in memory only; `clear_key` drops it; `switch_page` replaces the set).
  - `DeviceManager.show_page` stops all animations before redrawing, then re-attaches `get_all_animations()` for the new page.

- [ ] **Step 1: Write failing tests** (fake `StreamDeck` as in `test_device_drawing.py`)
  - `test_set_image_bytes_writes_through_the_writer_and_still_skips_an_unchanged_image`.
  - `test_static_write_stops_that_keys_animation`.
  - `test_show_page_leaves_no_writes_to_previous_page_keys_after_it_returns` (Review Focus 4).
  - `test_show_page_restarts_animations_recorded_for_the_new_page`.
  - `test_clear_key_state_forgets_the_animation`.
  - `test_animation_disabled_in_config_keeps_the_static_poster_only`.
  - `test_device_close_returns_promptly_with_animations_running` (Review Focus 5).
  - State: `test_animations_are_per_page_and_in_memory_only`.
- [ ] **Step 2: Run** `poe test -- tests/server/test_device_drawing.py tests/server/test_device_manager.py tests/server/devices` — Expected: FAIL.
- [ ] **Step 3: Implement** the changes; add to `defaults.yml`: `animation: {enabled: true, budget_percent: 75, cache_mb: 64}` with comments in the file's existing style.
- [ ] **Step 4: Run** the full server tests `poe test -- tests/server` — Expected: PASS (existing device tests may need the fake deck's `IMAGE_REPORT_PAYLOAD_LENGTH`; set it on the fixture).
- [ ] **Step 5: Commit** `git add src/decker/server/devices src/decker/common/config/defaults.yml .stubs tests/server` (only the files you changed) then `git commit -m "feat: route device image writes through the per-device writer"`.

### Task 9: Plugin host starts animations; state events carry `animation_id`

**Files:**
- Modify: `src/decker/server/plugins.py` (`_compose`, `_recompose`, `preview_image`, `_HardwareSink`, `_on_state_changed`, `get_key_display_states`)
- Test: `tests/server/test_plugins.py`, `tests/server/test_hardware_sink.py`

**Interfaces:**
- Consumes: `AnimationSpec`, `is_animated_gif` (Tasks 2, 4); `DeviceManager.set_animation`, `DeviceState.set_key_animation/get_key_animation` (Task 8).
- Produces:
  - `@dataclass(frozen=True) class Composed: png: bytes; animation: AnimationSpec | None` returned by `PluginManager._compose` (poster png unchanged: the renderer already reads a GIF's first frame); `animation` is set only when the resolved image bytes satisfy `is_animated_gif` (so a single-frame GIF stays static, Review Focus 1) and carries the expanded appearance, title and scale used for the PNG. `preview_image` still returns `bytes` (the `.png`).
  - `_HardwareSink.set_animation(device_id: str, key_index: int, spec: AnimationSpec) -> None` (calls `DeviceManager.set_animation` and records the spec on the key's `DeviceState`); `_HardwareSink.set_image` records `None` for the key's animation.
  - The `key_state_changed` payload and `get_key_display_states` entries gain `animation_id: str | None`; `_HardwareSink.set_animation` also calls `AnimationFactory.register(spec)` (via `DeviceManager.animation_factory`) so Task 10's RPC can find it.
  - A GIF that fails to decode at playback time leaves the poster on the key and affects nothing else (the factory handles the warning); `_compose` never raises because of a GIF.

- [ ] **Step 1: Write failing tests**
  - `test_animated_gif_icon_ref_writes_poster_then_starts_animation`.
  - `test_single_frame_gif_is_written_as_a_plain_static_image` (Review Focus 1).
  - `test_plugin_set_image_with_gif_bytes_starts_animation`.
  - `test_corrupt_gif_bytes_keep_a_static_image_and_do_not_raise` (Review Focus 2).
  - `test_replacing_a_gif_with_a_png_stops_the_animation_and_clears_animation_id`.
  - `test_key_state_changed_event_includes_animation_id_for_animated_keys_and_null_otherwise`.
  - Sink: `test_sink_set_animation_records_spec_on_device_state`.
- [ ] **Step 2: Run** `poe test -- tests/server/test_plugins.py tests/server/test_hardware_sink.py` — Expected: FAIL.
- [ ] **Step 3: Implement**; keep the sink's existing `set_image` signature and make `set_animation` a sibling method.
- [ ] **Step 4: Run** `poe test -- tests/server` — Expected: PASS.
- [ ] **Step 5: Commit** `git add src/decker/server/plugins.py tests/server/test_plugins.py tests/server/test_hardware_sink.py` then `git commit -m "feat: start animated key faces from the plugin host"`.

### Task 10: `key_animation` RPC

**Files:**
- Modify: `src/decker/server/service.py`, `src/decker/server/devices/manager.py` (expose the factory: `DeviceManager.animation_factory -> AnimationFactory`)
- Test: `tests/server/test_service.py`, `tests/server/test_protocol_conformance.py` only if it enumerates RPCs

**Interfaces:**
- Consumes: `AnimationFactory.preview_webp`, `spec_for`, `register` (Task 4); `animation_id` in state events (Task 9, which must `register` each spec it starts).
- Produces: `@exposed def key_animation(self, animation_id: str) -> str` on `DeckerService` — base64 of the composed animated image, `""` if the id is unknown, the build fails or the server is not ready (same convention as `key_preview`). Discoverable through `commands()` with no CLI change.

- [ ] **Step 1: Write failing tests**
  - `test_key_animation_returns_base64_animation_for_a_registered_id`.
  - `test_key_animation_returns_empty_string_for_an_unknown_id`.
  - `test_key_animation_is_listed_by_commands`.
- [ ] **Step 2: Run** `poe test -- tests/server/test_service.py` — Expected: FAIL.
- [ ] **Step 3: Implement** the RPC following `key_preview`'s error handling.
- [ ] **Step 4: Run** `poe test -- tests/server tests/cli` — Expected: PASS.
- [ ] **Step 5: Commit** `git add src/decker/server/service.py src/decker/server/devices/manager.py tests/server/test_service.py` then `git commit -m "feat: add key_animation RPC for client previews"`.

### Task 11: Client plays key animations

**Files:**
- Modify: `src/decker/client/widgets/button_grid.py` (`KeyButton`, `ButtonGrid`), `src/decker/client/views/dashboard.py` (`_on_display_states_updated`)
- Test: `tests/client/widgets/test_button_grid.py`, `tests/client/` dashboard test module

**Interfaces:**
- Consumes: `animation_id` in display states (Task 9); `key_animation` RPC (Task 10).
- Produces:
  - `KeyButton.set_animation(data: bytes | None) -> None` — plays the animated image through `QMovie` over a `QBuffer`, setting the button icon on each `frameChanged`; `None` stops and releases the movie; the movie is paused on `hideEvent` and resumed on `showEvent`; the static `set_image` poster still shows until the first frame arrives.
  - `ButtonGrid.set_key_animation(key_index: int, animation_b64: str | None) -> None`.
  - `DashboardView` fetches `key_animation(animation_id)` through the same call mechanism it uses for `key_preview` only when a key's `animation_id` changes and the key is on the visible page; a state with no `animation_id` calls `set_key_animation(index, None)`. Fetches never block the GUI thread.
- First check Qt can read the produced format: add `test_qt_can_play_the_server_produced_animation` using `QMovie.isValid()` and `frameCount() > 1`; if Qt lacks WebP, switch `AnimationFactory.preview_webp` to GIF output and rename nothing else.

- [ ] **Step 1: Write failing tests** (offscreen Qt, existing fixtures)
  - `test_set_animation_advances_the_icon_between_frames` (pump events past two frame delays; icons differ).
  - `test_set_animation_none_stops_the_movie_and_restores_the_poster`.
  - `test_hidden_button_pauses_its_movie`.
  - `test_dashboard_fetches_animation_once_per_animation_id` (call count 1 across two identical state updates, 2 after the id changes).
  - `test_state_without_animation_id_clears_the_animation`.
- [ ] **Step 2: Run** `poe test -- tests/client` — Expected: FAIL.
- [ ] **Step 3: Implement**; the config panel's draft preview keeps using the poster (`set_preview_image`), unchanged.
- [ ] **Step 4: Run** `poe test -- tests/client` — Expected: PASS.
- [ ] **Step 5: Commit** `git add src/decker/client/widgets/button_grid.py src/decker/client/views/dashboard.py tests/client` (only changed files) then `git commit -m "feat: play animated key faces in the client grid"`.

### Task 12: Benchmark script, docs, end-to-end test and verification

**Files:**
- Create: `scripts/bench_usb_writes.py` (from the throwaway benchmark: CLI args `gif_path`, `--seconds`; prints frames/s, reports/s, MB/s and call latency for 1, 8 and all keys at q100 and q90; resets the deck on exit; header comment says it needs the server stopped)
- Modify: `CLAUDE.md` (one sentence in the Server paragraph: key faces may be animated GIFs played by a per-device adaptive writer in `src/decker/animation/`, spec path), `docs/plugins/README.md` if it lists capabilities
- Create: `tests/animation/test_end_to_end.py`

**Interfaces:**
- Consumes: everything above. Produces nothing new.

- [ ] **Step 1: Write the end-to-end test** with a fake `StreamDeck` whose `set_key_image` advances a fake clock by `reports * 0.00025` and records writes: `test_32_animated_keys_play_through_the_device_and_stay_within_budget` (all keys receive frames; measured busy fraction at most 0.75 after settling; page switch to a static page stops all animation writes; switching back restarts them) and `test_slower_link_forces_a_lower_level` (per-report cost 0.001 s settles below L1 and stays under the budget).
- [ ] **Step 2: Run** `poe test -- tests/animation/test_end_to_end.py` — Expected: PASS once Tasks 1-11 are in; fix wiring gaps it reveals.
- [ ] **Step 3: Add the benchmark script and docs.**
- [ ] **Step 4: Run all quality gates:** `poe format`, `poe mypy`, `poe pylint` (at least 9.0), `poe test` (coverage at least 85%) — Expected: all pass.
- [ ] **Step 5: Manual hardware verification** (ask the user first; it stops their server): run `poe cli stop`, run the benchmark and confirm about 4000 reports/s on the XL, relaunch the server, assign the cat GIF through a dev icon pack to all 32 keys, watch the deck for tearing or dropped frames, and read the `INFO` level-change log lines.
- [ ] **Step 6: Commit** `git add scripts/bench_usb_writes.py CLAUDE.md tests/animation/test_end_to_end.py` (and docs touched) then `git commit -m "feat: add USB write benchmark, docs and end-to-end animation test"`.
