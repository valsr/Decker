import io
import threading

import pytest
from assertpy import assert_that
from PIL import Image

from decker.server import appearance as ap
from decker.server.appearance import compose_key_image, resolve_appearance


def _png(color: str, size: int = 20) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buf, format="PNG")
    return buf.getvalue()


_LOOK = resolve_appearance({}, {"background": {"type": "image", "image": {"ref": "x"}}})


@pytest.fixture(autouse=True)
def _clean_cache():
    ap._LAYER_CACHE.clear()  # pylint: disable=protected-access
    yield
    ap._LAYER_CACHE.clear()  # pylint: disable=protected-access


def _decodes(monkeypatch) -> list[int]:
    calls: list[int] = []
    real = ap._background_image  # pylint: disable=protected-access

    def spy(data: bytes, size: int):
        calls.append(size)
        return real(data, size)

    monkeypatch.setattr(ap, "_background_image", spy)
    return calls


def test_second_compose_of_the_same_background_does_not_decode_again(monkeypatch):
    calls = _decodes(monkeypatch)
    data = _png("#0000ff")

    first = compose_key_image(_LOOK, None, "", background_image=data)
    second = compose_key_image(_LOOK, None, "", background_image=data)

    assert_that(calls).is_length(1)
    assert_that(second).is_equal_to(first)


def test_changed_image_and_other_size_are_rendered_again(monkeypatch):
    calls = _decodes(monkeypatch)

    compose_key_image(_LOOK, None, "", background_image=_png("#0000ff"))
    compose_key_image(_LOOK, None, "", background_image=_png("#ff0000"))
    compose_key_image(_LOOK, None, "", size=72, background_image=_png("#ff0000"))

    assert_that(calls).is_equal_to([144, 144, 72])


def test_cache_is_bounded_and_evicts_the_oldest():
    for i in range(ap._MAX_CACHED_LAYERS + 5):  # pylint: disable=protected-access
        compose_key_image(_LOOK, None, "", size=16, background_image=_png(f"#{i:02x}0000", 8 + i))

    assert_that(ap._LAYER_CACHE).is_length(ap._MAX_CACHED_LAYERS)  # pylint: disable=protected-access
    oldest = (ap.hashlib.sha256(_png("#000000", 8)).hexdigest(), 16)
    assert_that(ap._LAYER_CACHE).does_not_contain_key(oldest)  # pylint: disable=protected-access


def test_cached_layer_is_not_mutated_by_compositing():
    data = _png("#0000ff")
    expected = compose_key_image(_LOOK, None, "")  # black reference, not used below
    assert_that(expected).is_not_none()
    plain = compose_key_image(_LOOK, None, "", background_image=data)
    ap._LAYER_CACHE.clear()  # pylint: disable=protected-access
    titled_look = resolve_appearance({}, {**_LOOK, "title": {"text": "Hello", "position": "middle"}})
    uncached_titled = compose_key_image(titled_look, _png("#00ff00", 8), "", background_image=data)
    ap._LAYER_CACHE.clear()  # pylint: disable=protected-access

    compose_key_image(_LOOK, None, "", background_image=data)  # fills the cache
    cached_titled = compose_key_image(titled_look, _png("#00ff00", 8), "", background_image=data)
    again = compose_key_image(_LOOK, None, "", background_image=data)

    assert_that(cached_titled).is_equal_to(uncached_titled)
    assert_that(again).is_equal_to(plain)


def test_bad_image_is_not_cached():
    compose_key_image(_LOOK, None, "", background_image=b"not an image")

    assert_that(ap._LAYER_CACHE).is_empty()  # pylint: disable=protected-access


def test_threads_composing_the_same_background_agree():
    data = _png("#0000ff")
    results: list[bytes] = []

    def work() -> None:
        for _ in range(10):
            results.append(compose_key_image(_LOOK, None, "", background_image=data))

    threads = [threading.Thread(target=work) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert_that(results).is_length(60)
    assert_that(set(results)).is_length(1)


def test_intern_background_returns_one_shared_object_per_content() -> None:
    ap._INTERNED.clear()  # pylint: disable=protected-access
    first = ap.intern_background(bytes(_png("#ff0000")))
    copy = ap.intern_background(bytes(_png("#ff0000")))
    assert_that(copy is first).is_true()
    assert_that(ap.intern_background(None)).is_none()


def test_intern_background_is_bounded_by_count_and_bytes(monkeypatch) -> None:
    ap._INTERNED.clear()  # pylint: disable=protected-access
    for index in range(40):
        ap.intern_background(f"image-{index}".encode())
    assert_that(ap._INTERNED).is_length(32)  # pylint: disable=protected-access
    monkeypatch.setattr(ap, "_MAX_INTERNED_BYTES", 100)
    ap._INTERNED.clear()  # pylint: disable=protected-access
    big = b"x" * 101
    assert_that(ap.intern_background(big) is big).is_true()
    assert_that(ap._INTERNED).is_empty()  # pylint: disable=protected-access
    for index in range(5):
        ap.intern_background(bytes([index]) * 30)
    assert_that(sum(len(v) for v in ap._INTERNED.values())).is_less_than_or_equal_to(
        100
    )  # pylint: disable=protected-access
