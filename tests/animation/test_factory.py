import io
import logging
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from assertpy import assert_that
from PIL import Image

from decker.animation import factory as factory_module
from decker.animation.encode import KeyFormat
from decker.animation.factory import AnimationFactory
from decker.animation.model import Animation, AnimationSpec, Frame
from decker.server.appearance import resolve_appearance

_FMT = KeyFormat(size=(72, 72), image_format="JPEG", rotation=0, flip=(False, False), report_payload=1016)
_APPEARANCE: dict[str, Any] = resolve_appearance({}, {"background": "#202020"})


def _make_gif(count: int = 3, size: int = 16) -> bytes:
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    frames = [Image.new("RGB", (size, size), colors[i % len(colors)]) for i in range(count)]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return buffer.getvalue()


def _spec(title: str = "", gif: bytes | None = None) -> AnimationSpec:
    return AnimationSpec(gif=gif if gif is not None else _make_gif(), appearance=_APPEARANCE, title=title, scale=1.0)


def _built(factory: AnimationFactory, spec: AnimationSpec, quality: int = 90) -> Animation:
    factory.frames_for(spec, _FMT, quality)
    assert_that(factory.wait_idle(10)).is_true()
    animation = factory.frames_for(spec, _FMT, quality)
    assert animation is not None
    return animation


@pytest.fixture(name="factory")
def _factory() -> Iterator[AnimationFactory]:
    instance = AnimationFactory(cache_bytes=8 * 1024 * 1024)
    yield instance
    instance.close()


def test_frame_index_at_follows_cumulative_delays_and_loops() -> None:
    frames = (Frame(b"a", 1, 100), Frame(b"b", 1, 50))
    animation = Animation("id", 90, frames, b"", {90: 1.0})

    indices = [animation.frame_index_at(ms) for ms in (0, 99, 100, 149, 150)]

    assert_that(indices).is_equal_to([0, 0, 1, 1, 0])
    assert_that(animation.total_ms).is_equal_to(150)


def test_animation_id_ignores_nothing_but_content_and_appearance() -> None:
    gif = _make_gif()
    same = AnimationSpec(gif=gif, appearance=dict(_APPEARANCE), title="", scale=1.0)

    assert_that(_spec(gif=gif).animation_id).is_equal_to(same.animation_id)
    assert_that(_spec(gif=gif).animation_id).is_not_equal_to(
        AnimationSpec(gif=gif, appearance=_APPEARANCE, title="", scale=0.5).animation_id
    )
    assert_that(_spec(gif=gif).gif_sha).is_length(64)


def test_same_gif_on_many_keys_encodes_once(factory: AnimationFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    real_encode = factory_module.encode_native

    def spy(image: Image.Image, fmt: KeyFormat, quality: int) -> bytes:
        calls.append(quality)
        return real_encode(image, fmt, quality)

    monkeypatch.setattr(factory_module, "encode_native", spy)
    spec = _spec()

    for _ in range(32):
        factory.frames_for(spec, _FMT, 90)
    assert_that(factory.wait_idle(10)).is_true()
    animations = [factory.frames_for(_spec(), _FMT, 90) for _ in range(32)]

    # 3 frames at quality 90, plus frame 0 at 100 and 75 for reports_by_quality.
    assert_that(calls).is_length(5)
    assert_that(animations).does_not_contain(None)
    assert_that({id(animation) for animation in animations}).is_length(1)


def test_animation_larger_than_the_cache_budget_fails_once_and_is_never_rebuilt(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[int] = []
    real_encode = factory_module.encode_native

    def spy(image: Image.Image, fmt: KeyFormat, quality: int) -> bytes:
        calls.append(quality)
        return real_encode(image, fmt, quality)

    monkeypatch.setattr(factory_module, "encode_native", spy)
    caplog.set_level(logging.WARNING, logger="decker.animation.factory")
    tiny = AnimationFactory(cache_bytes=100)
    spec = _spec()
    try:
        for _ in range(10):
            assert_that(tiny.frames_for(spec, _FMT, 90)).is_none()
            assert_that(tiny.wait_idle(10)).is_true()
    finally:
        tiny.close()

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert_that(warnings).is_length(1)
    assert_that(warnings[0].getMessage()).contains("exceeds the cache budget")
    assert_that(calls).is_length(5)


def test_animation_within_the_cache_budget_builds_without_warnings(
    factory: AnimationFactory, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="decker.animation.factory")

    animation = _built(factory, _spec())

    assert_that(animation.frames).is_length(3)
    assert_that([record for record in caplog.records if record.levelno == logging.WARNING]).is_empty()


def test_built_animation_has_frames_reports_and_poster(factory: AnimationFactory) -> None:
    animation = _built(factory, _spec())

    assert_that(animation.frames).is_length(3)
    assert_that(animation.quality).is_equal_to(90)
    assert_that([frame.delay_ms for frame in animation.frames]).contains_only(100)
    for frame in animation.frames:
        assert_that(frame.reports).is_equal_to(-(-len(frame.data) // _FMT.report_payload))
    assert_that(sorted(animation.reports_by_quality)).is_equal_to([75, 90, 100])
    assert_that(animation.reports_by_quality[100]).is_greater_than_or_equal_to(animation.reports_by_quality[75])
    with Image.open(io.BytesIO(animation.poster_png)) as poster:
        assert_that(poster.format).is_equal_to("PNG")
        assert_that(poster.size).is_equal_to((144, 144))


def test_reports_use_the_payload_of_the_key_format(factory: AnimationFactory) -> None:
    small_payload = KeyFormat(size=(72, 72), image_format="JPEG", rotation=0, flip=(False, False), report_payload=64)
    spec = _spec()

    factory.frames_for(spec, small_payload, 90)
    factory.wait_idle(10)
    animation = factory.frames_for(spec, small_payload, 90)

    assert animation is not None
    assert_that(animation.frames[0].reports).is_equal_to(-(-len(animation.frames[0].data) // 64))
    assert_that(factory.frames_for(spec, _FMT, 90)).is_none()


def test_changing_the_title_changes_the_animation_id_and_rebuilds(factory: AnimationFactory) -> None:
    gif = _make_gif()
    first = _spec(title="A", gif=gif)
    second = _spec(title="B", gif=gif)
    _built(factory, first)

    assert_that(second.animation_id).is_not_equal_to(first.animation_id)
    assert_that(factory.frames_for(second, _FMT, 90)).is_none()
    rebuilt = _built(factory, second)
    assert_that(rebuilt.animation_id).is_equal_to(second.animation_id)
    assert_that(rebuilt.poster_png).is_not_equal_to(_built(factory, first).poster_png)


def test_frames_for_returns_none_until_the_build_finishes_then_the_animation(
    factory: AnimationFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()
    real_decode = factory_module.decode_gif

    def blocked_decode(data: bytes) -> Any:
        release.wait(10)
        return real_decode(data)

    monkeypatch.setattr(factory_module, "decode_gif", blocked_decode)
    spec = _spec()

    assert_that(factory.frames_for(spec, _FMT, 90)).is_none()
    assert_that(factory.frames_for(spec, _FMT, 90)).is_none()
    assert_that(factory.wait_idle(0.01)).is_false()
    release.set()
    assert_that(factory.wait_idle(10)).is_true()

    animation = factory.frames_for(spec, _FMT, 90)
    assert_that(animation).is_instance_of(Animation)
    assert animation is not None
    assert_that(animation.animation_id).is_equal_to(spec.animation_id)


def test_cached_frames_returns_only_built_animations_and_never_builds(factory: AnimationFactory) -> None:
    spec = _spec()
    assert_that(factory.cached_frames(spec, _FMT, 90)).is_none()
    assert_that(factory.wait_idle(0.01)).is_true()
    assert_that(factory.frames_for(spec, _FMT, 90)).is_none()

    built = _built(factory, spec, 90)

    assert_that(factory.cached_frames(spec, _FMT, 90)).is_same_as(built)
    assert_that(factory.cached_frames(spec, _FMT, 75)).is_none()
    assert_that(factory.wait_idle(0.01)).is_true()
    broken = _spec(gif=b"GIF89a broken")
    factory.frames_for(broken, _FMT, 90)
    assert_that(factory.wait_idle(10)).is_true()
    assert_that(factory.cached_frames(broken, _FMT, 90)).is_none()


def test_corrupt_gif_logs_one_warning_and_returns_none_repeatedly(
    factory: AnimationFactory, caplog: pytest.LogCaptureFixture
) -> None:
    spec = _spec(gif=b"GIF89a this is not a gif")
    caplog.set_level(logging.WARNING, logger="decker.animation.factory")

    for _ in range(3):
        assert_that(factory.frames_for(spec, _FMT, 90)).is_none()
        assert_that(factory.wait_idle(10)).is_true()
    assert_that(factory.frames_for(spec, _FMT, 75)).is_none()
    assert_that(factory.wait_idle(10)).is_true()

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert_that(warnings).is_length(1)


def test_is_failed_turns_true_once_the_gif_failed_to_build(factory: AnimationFactory) -> None:
    spec = _spec(gif=b"GIF89a this is not a gif")
    assert_that(factory.is_failed(spec)).is_false()

    factory.frames_for(spec, _FMT, 90)
    assert_that(factory.wait_idle(10)).is_true()

    assert_that(factory.is_failed(spec)).is_true()
    assert_that(factory.is_failed(_spec())).is_false()


def test_a_gif_over_the_pixel_budget_fails_from_its_header_with_one_warning(
    factory: AnimationFactory, caplog: pytest.LogCaptureFixture
) -> None:
    buffer = io.BytesIO()
    tiny = [Image.new("L", (2, 2), index) for index in range(300)]
    tiny[0].save(buffer, format="GIF", save_all=True, append_images=tiny[1:], duration=100)
    data = bytearray(buffer.getvalue())
    data[6:10] = (4096).to_bytes(2, "little") * 2  # the logical screen claims 300 frames of 4096x4096
    spec = _spec(gif=bytes(data))
    caplog.set_level(logging.WARNING, logger="decker.animation.factory")

    for _ in range(3):
        factory.frames_for(spec, _FMT, 90)
        assert_that(factory.wait_idle(10)).is_true()

    assert_that(factory.is_failed(spec)).is_true()
    assert_that([r for r in caplog.records if r.levelno == logging.WARNING]).is_length(1)


def test_a_big_canvas_gif_is_composed_from_downscaled_frames(factory: AnimationFactory) -> None:
    spec = _spec(gif=_make_gif(count=3, size=400))

    animation = _built(factory, spec)

    assert_that(animation.frames).is_length(3)
    assert_that(Image.open(io.BytesIO(animation.poster_png)).size).is_equal_to((144, 144))


def test_preview_webp_is_a_playable_animation_with_all_frames(factory: AnimationFactory) -> None:
    spec = _spec(gif=_make_gif(count=4))

    data = factory.preview_webp(spec)

    assert data is not None
    with Image.open(io.BytesIO(data)) as preview:
        assert_that(preview.format).is_in("WEBP", "GIF")
        assert_that(getattr(preview, "n_frames", 1)).is_equal_to(4)
        assert_that(preview.size).is_equal_to((144, 144))
    assert_that(factory.preview_webp(spec)).is_same_as(data)


def test_preview_falls_back_to_gif_when_webp_animation_fails(
    factory: AnimationFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_webp(_frames: list[Image.Image], _delays: list[int]) -> bytes:
        raise OSError("no webp")

    monkeypatch.setattr(factory_module, "_save_webp", no_webp)

    data = factory.preview_webp(_spec(gif=_make_gif(count=2)))

    assert data is not None
    with Image.open(io.BytesIO(data)) as preview:
        assert_that(preview.format).is_equal_to("GIF")
        assert_that(getattr(preview, "n_frames", 1)).is_equal_to(2)


def test_preview_of_a_corrupt_gif_is_none(factory: AnimationFactory) -> None:
    assert_that(factory.preview_webp(_spec(gif=b"GIF89a broken"))).is_none()


def test_a_gif_that_failed_to_build_gets_no_preview_and_no_second_warning(
    factory: AnimationFactory, caplog: pytest.LogCaptureFixture
) -> None:
    spec = _spec(gif=b"GIF89a broken")
    caplog.set_level(logging.WARNING, logger="decker.animation.factory")
    factory.frames_for(spec, _FMT, 90)
    factory.wait_idle(10)

    assert_that(factory.preview_webp(spec)).is_none()
    assert_that([r for r in caplog.records if r.levelno == logging.WARNING]).is_length(1)


def test_register_and_spec_for_round_trip_and_stay_bounded(
    factory: AnimationFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(factory_module, "MAX_REGISTERED_SPECS", 2)
    specs = [_spec(title=str(i)) for i in range(3)]

    ids = [factory.register(spec) for spec in specs]

    assert_that(ids[2]).is_equal_to(specs[2].animation_id)
    assert_that(factory.spec_for(ids[2])).is_same_as(specs[2])
    assert_that(factory.spec_for(ids[0])).is_none()
    assert_that(factory.spec_for("unknown")).is_none()


def test_close_drops_pending_builds_and_stops_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()
    real_decode = factory_module.decode_gif

    def blocked_decode(data: bytes) -> Any:
        release.wait(10)
        return real_decode(data)

    monkeypatch.setattr(factory_module, "decode_gif", blocked_decode)
    instance = AnimationFactory(cache_bytes=1024 * 1024)
    for title in ("a", "b", "c"):
        instance.frames_for(_spec(title=title), _FMT, 90)

    instance.close()
    release.set()

    assert_that(instance.wait_idle(0.01)).is_true()
    assert_that(instance.frames_for(_spec(title="d"), _FMT, 90)).is_none()
    assert_that(instance.wait_idle(0.01)).is_true()
