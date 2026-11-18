"""Builds and caches composed, natively encoded animations off the caller's thread."""

import functools
import io
import logging
import math
import queue
import threading
from collections import OrderedDict
from collections.abc import Callable, Sequence

from PIL import Image

from decker.animation.cache import SizedLru
from decker.animation.encode import KeyFormat, encode_native
from decker.animation.gif import GifError, GifFrame, decode_gif
from decker.animation.model import Animation, AnimationSpec, Frame
from decker.server.appearance import compose_key_frames

logger = logging.getLogger(__name__)

BUILD_WORKERS = 2
PREVIEW_SIZE = 144
PREVIEW_CACHE_BYTES = 16 * 1024 * 1024
MAX_REGISTERED_SPECS = 1024
ESTIMATE_QUALITIES = (100, 90, 75)

_Key = tuple[str, KeyFormat, int]


class _DaemonPool:
    # Daemon workers so an unfinished build never keeps the process alive or delays interpreter shutdown;
    # ThreadPoolExecutor joins its (non-daemon) workers at exit and runs every queued task first.
    def __init__(self, workers: int) -> None:
        self._queue: queue.SimpleQueue[Callable[[], None] | None] = queue.SimpleQueue()
        self._threads: list[threading.Thread] = [
            threading.Thread(target=self._work, name=f"animation-build-{index}", daemon=True)
            for index in range(workers)
        ]
        for thread in self._threads:
            thread.start()

    def submit(self, task: Callable[[], None]) -> None:
        """Queue task for the next free worker."""
        self._queue.put(task)

    def close(self) -> None:
        """Let each worker exit once it reaches the end of the queue, without waiting."""
        for _ in self._threads:
            self._queue.put(None)

    def _work(self) -> None:
        while (task := self._queue.get()) is not None:
            task()


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _save_webp(frames: list[Image.Image], delays: list[int]) -> bytes:
    buffer = io.BytesIO()
    frames[0].save(
        buffer, format="WEBP", save_all=True, append_images=frames[1:], duration=delays, loop=0, lossless=True
    )
    return buffer.getvalue()


def _save_gif(frames: list[Image.Image], delays: list[int]) -> bytes:
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=delays, loop=0)
    return buffer.getvalue()


def _compose(spec: AnimationSpec, frames: Sequence[GifFrame], size: int) -> list[Image.Image]:
    return compose_key_frames(spec.appearance, [frame.image for frame in frames], spec.title, size, spec.scale)


def _reports_by_quality(
    first: Image.Image, frames: tuple[Frame, ...], fmt: KeyFormat, quality: int
) -> dict[int, float]:
    average = sum(frame.reports for frame in frames) / len(frames)
    base = len(frames[0].data)
    sizes = {q: base if q == quality else len(encode_native(first, fmt, q)) for q in ESTIMATE_QUALITIES}
    return {q: average * size / base for q, size in sizes.items()}


def _build_animation(spec: AnimationSpec, fmt: KeyFormat, quality: int) -> tuple[Animation, int]:
    gif_frames = decode_gif(spec.gif)
    images = _compose(spec, gif_frames, max(fmt.size))
    encoded = [encode_native(image, fmt, quality) for image in images]
    frames = tuple(
        Frame(data, math.ceil(len(data) / fmt.report_payload), gif_frame.delay_ms)
        for data, gif_frame in zip(encoded, gif_frames)
    )
    poster = _png(_compose(spec, gif_frames[:1], PREVIEW_SIZE)[0])
    animation = Animation(
        spec.animation_id, quality, frames, poster, _reports_by_quality(images[0], frames, fmt, quality)
    )
    return animation, sum(len(data) for data in encoded) + len(poster)


def _build_preview(spec: AnimationSpec) -> tuple[bytes, int]:
    gif_frames = decode_gif(spec.gif)
    images = _compose(spec, gif_frames, PREVIEW_SIZE)
    delays = [frame.delay_ms for frame in gif_frames]
    try:
        data = _save_webp(images, delays)
    except (OSError, KeyError, ValueError):
        data = _save_gif(images, delays)
    return data, len(data)


class _OverBudgetError(Exception):
    pass


class AnimationFactory:
    """Shared, size-bounded source of encoded animations and GUI previews, built in the background."""

    def __init__(self, cache_bytes: int) -> None:
        self._cache_bytes: int = cache_bytes
        self._frames: SizedLru = SizedLru(cache_bytes)
        self._previews: SizedLru = SizedLru(PREVIEW_CACHE_BYTES)
        self._specs: OrderedDict[str, AnimationSpec] = OrderedDict()
        self._failed: set[str] = set()
        self._pending: set[_Key] = set()
        self._state: threading.Condition = threading.Condition()
        self._closed: bool = False
        self._pool: _DaemonPool = _DaemonPool(BUILD_WORKERS)

    def frames_for(self, spec: AnimationSpec, fmt: KeyFormat, quality: int) -> Animation | None:
        """Return the cached animation, or None while it builds (or if its GIF failed to build)."""
        key: _Key = (spec.animation_id, fmt, quality)
        gif_sha = spec.gif_sha
        with self._state:
            if gif_sha in self._failed:
                return None
            cached: Animation | None = self._frames.get(key)
            if cached is not None or key in self._pending or self._closed:
                return cached
            self._pending.add(key)
        self._pool.submit(functools.partial(self._build_in_background, key, spec))
        return None

    def cached_frames(self, spec: AnimationSpec, fmt: KeyFormat, quality: int) -> Animation | None:
        """Return the animation if it is already cached, else None; never starts a build."""
        with self._state:
            if spec.gif_sha in self._failed:
                return None
            cached: Animation | None = self._frames.get((spec.animation_id, fmt, quality))
            return cached

    def is_failed(self, spec: AnimationSpec) -> bool:
        """Return True once spec's GIF has failed to build (or preview)."""
        with self._state:
            return spec.gif_sha in self._failed

    def preview_webp(self, spec: AnimationSpec) -> bytes | None:
        """Return the composed animation at 144 px as animated WebP (GIF without WebP support), or None."""
        if spec.gif_sha in self._failed:
            return None
        try:
            data: bytes = self._previews.get_or_build(spec.animation_id, functools.partial(_build_preview, spec))
        except GifError as exc:
            self._remember_failure(spec, exc)
            return None
        return data

    def register(self, spec: AnimationSpec) -> str:
        """Remember spec under its animation id (most recent MAX_REGISTERED_SPECS kept) and return the id."""
        animation_id = spec.animation_id
        with self._state:
            self._specs[animation_id] = spec
            self._specs.move_to_end(animation_id)
            while len(self._specs) > MAX_REGISTERED_SPECS:
                self._specs.popitem(last=False)
        return animation_id

    def spec_for(self, animation_id: str) -> AnimationSpec | None:
        """Return the registered spec for animation_id, or None."""
        with self._state:
            return self._specs.get(animation_id)

    def wait_idle(self, timeout: float) -> bool:
        """Wait until no build is pending; return False on timeout."""
        with self._state:
            return self._state.wait_for(lambda: not self._pending, timeout)

    def close(self) -> None:
        """Stop the build workers without waiting; pending builds are dropped."""
        with self._state:
            self._closed = True
            self._pending.clear()
            self._state.notify_all()
        self._pool.close()

    def _build_in_background(self, key: _Key, spec: AnimationSpec) -> None:
        try:
            if not self._closed:
                self._frames.get_or_build(key, functools.partial(self._build_within_budget, spec, key[1], key[2]))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._remember_failure(spec, exc)
        finally:
            with self._state:
                self._pending.discard(key)
                self._state.notify_all()

    def _build_within_budget(self, spec: AnimationSpec, fmt: KeyFormat, quality: int) -> tuple[Animation, int]:
        # An animation the cache cannot hold would be rebuilt on every poll, so it fails like a bad GIF.
        animation, size = _build_animation(spec, fmt, quality)
        if size > self._cache_bytes:
            raise _OverBudgetError(f"animation exceeds the cache budget ({size} > {self._cache_bytes} bytes)")
        return animation, size

    def _remember_failure(self, spec: AnimationSpec, exc: Exception) -> None:
        with self._state:
            if spec.gif_sha in self._failed:
                return
            self._failed.add(spec.gif_sha)
        logger.warning("Cannot build animation for GIF %s: %s", spec.gif_sha[:12], exc)
