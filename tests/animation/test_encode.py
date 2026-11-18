import io
import random

from assertpy import assert_that
from PIL import Image

from decker.animation.encode import KeyFormat, encode_native

_JPEG = KeyFormat(size=(96, 96), image_format="JPEG", rotation=0, flip=(False, False))


def _fmt(rotation: int = 0, flip: tuple[bool, bool] = (False, False)) -> KeyFormat:
    return KeyFormat(size=(96, 96), image_format="JPEG", rotation=rotation, flip=flip)


def _noisy(size: int = 96) -> Image.Image:
    rng = random.Random(1)
    img = Image.new("RGB", (size, size))
    img.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(size * size)])
    return img


def _marked() -> Image.Image:
    img = Image.new("RGB", (96, 96), (0, 0, 0))
    for x in range(8):
        for y in range(8):
            img.putpixel((x, y), (255, 255, 255))
    return img


def _bright_corner(data: bytes) -> tuple[int, int]:
    img = Image.open(io.BytesIO(data)).convert("L")
    return max(((x, y) for x in (4, 91) for y in (4, 91)), key=lambda p: img.getpixel(p))  # type: ignore[arg-type,return-value]


def test_quality_90_is_smaller_than_100_for_the_same_frame() -> None:
    frame = _noisy()
    assert_that(len(encode_native(frame, _JPEG, 90))).is_less_than(len(encode_native(frame, _JPEG, 100)))


def test_output_is_scaled_to_the_key_size() -> None:
    fmt = KeyFormat(size=(72, 72), image_format="JPEG", rotation=0, flip=(False, False))
    out = Image.open(io.BytesIO(encode_native(_noisy(), fmt, 90)))
    assert_that(out.format).is_equal_to("JPEG")
    assert_that(out.size).is_equal_to((72, 72))


def test_rotation_and_flip_follow_the_deck_format() -> None:
    marked = _marked()
    assert_that(_bright_corner(encode_native(marked, _fmt(), 100))).is_equal_to((4, 4))
    assert_that(_bright_corner(encode_native(marked, _fmt(flip=(True, False)), 100))).is_equal_to((91, 4))
    assert_that(_bright_corner(encode_native(marked, _fmt(flip=(True, True)), 100))).is_equal_to((91, 91))
    # PIL rotates counter-clockwise: top-left goes to bottom-left; the flip (applied after) moves it to bottom-right.
    assert_that(_bright_corner(encode_native(marked, _fmt(rotation=90), 100))).is_equal_to((4, 91))
    assert_that(_bright_corner(encode_native(marked, _fmt(rotation=90, flip=(True, False)), 100))).is_equal_to((91, 91))


def test_bmp_format_ignores_quality() -> None:
    fmt = KeyFormat(size=(96, 96), image_format="BMP", rotation=0, flip=(False, False))
    frame = _noisy()
    low = encode_native(frame, fmt, 10)
    assert_that(low).is_equal_to(encode_native(frame, fmt, 100))
    assert_that(low[:2]).is_equal_to(b"BM")


def test_from_deck_reads_format_and_defaults_report_payload() -> None:
    raw = {"size": (72, 72), "format": "JPEG", "flip": (True, False), "rotation": 180}
    fmt = KeyFormat.from_deck(raw)
    assert_that(fmt).is_equal_to(KeyFormat((72, 72), "JPEG", 180, (True, False)))
    assert_that(fmt.report_payload).is_equal_to(1016)
    assert_that(KeyFormat.from_deck(raw, report_payload=512).report_payload).is_equal_to(512)
    assert_that(hash(fmt)).is_equal_to(hash(KeyFormat.from_deck(raw)))
