"""Builds tiny GIF files whose frames are far bigger than their logical screen, without allocating those frames."""

_CLEAR = 4  # LZW minimum code size 2: colours 0..3, clear code 4, end code 5, first dictionary code 6
_END = 5
_MAX_CODES = 4096


def _uniform_lzw(pixels: int, colour: int) -> bytes:
    """LZW-compress `pixels` pixels of one colour (a run grows the dictionary by one longer run per code)."""
    bits: list[tuple[int, int]] = []  # (code, width)
    width, next_code = 3, 6
    bits.append((_CLEAR, width))
    remaining = pixels
    run = 1  # length of the longest run string in the dictionary
    while remaining:
        length = min(run, remaining)
        bits.append((colour if length == 1 else length + 4, width))
        remaining -= length
        if remaining:
            next_code += 1
            run += 1
            if next_code > (1 << width) and width < 12:
                width += 1
            if next_code >= _MAX_CODES:
                bits.append((_CLEAR, width))
                width, next_code, run = 3, 6, 1
    bits.append((_END, width))
    out, acc, nbits = bytearray(), 0, 0
    for code, size in bits:
        acc |= code << nbits
        nbits += size
        while nbits >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            nbits -= 8
    if nbits:
        out.append(acc & 0xFF)
    return bytes(out)


def _sub_blocks(data: bytes) -> bytes:
    out = bytearray()
    for start in range(0, len(data), 255):
        chunk = data[start : start + 255]
        out += bytes([len(chunk)]) + chunk
    return bytes(out) + b"\x00"


def grown_gif(
    logical: tuple[int, int], frame_sizes: list[tuple[int, int]], junk: bytes = b"", disposal: int = 0
) -> bytes:
    """A GIF with the given logical screen and one uniform-colour frame per size, each drawn at the origin.

    `junk` is written before the second frame (bytes that start no block, which Pillow skips) and `disposal` is
    the disposal method of every frame.
    """
    palette = bytes([0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255])
    out = bytearray(b"GIF89a")
    out += logical[0].to_bytes(2, "little") + logical[1].to_bytes(2, "little") + b"\x81\x00\x00" + palette
    out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    for index, (width, height) in enumerate(frame_sizes):
        if index == 1:
            out += junk
        out += bytes([0x21, 0xF9, 0x04, disposal << 2, 0x0A, 0x00, 0x00, 0x00])
        out += b"\x2c\x00\x00\x00\x00" + width.to_bytes(2, "little") + height.to_bytes(2, "little") + b"\x00"
        out += b"\x02" + _sub_blocks(_uniform_lzw(width * height, 1 + index % 3))
    return bytes(out + b"\x3b")


def _frame(width: int, height: int, colour: int, disposal: int = 0) -> bytes:
    out = bytes([0x21, 0xF9, 0x04, disposal << 2, 0x0A, 0x00, 0x00, 0x00])
    out += b"\x2c\x00\x00\x00\x00" + width.to_bytes(2, "little") + height.to_bytes(2, "little") + b"\x00"
    return out + b"\x02" + _sub_blocks(_uniform_lzw(width * height, colour))


def _hide(big: bytes) -> bytes:
    """Bytes that hide `big` from a walk that reads one chain after `21 01 00` while Pillow reads two."""
    return b"\x21\x01\x00" + bytes([0x21, 0x01, 51]) + b"\x01" * 31 + b"\x00" + big


def _fake() -> bytes:
    """Bytes a one-chain walk reads as a 1x1 frame and Pillow swallows as sub-block data."""
    return b"\x21\x01\x00" + bytes([0x2C, 0, 0, 0, 0, 1, 0, 1, 0, 0, 2, 0]) + b"\x01" * 33 + b"\x00"


def desynced_gif(big: tuple[int, int], balanced: bool, disposal: int = 0, hidden: int = 1) -> bytes:
    """A GIF where empty extension blocks make a naive walk and Pillow read different frames.

    `hidden` big frames are invisible to a one-chain walk; `balanced` adds fake frames the walk sees and Pillow
    does not (keeping the frame counts equal) and the trailer, otherwise the trailer is left out.
    """
    palette = bytes([0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255])
    out = bytearray(b"GIF89a\x02\x00\x02\x00\x81\x00\x00" + palette)
    out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00" + _frame(2, 2, 1)
    for _ in range(hidden):
        out += _hide(_frame(big[0], big[1], 2, disposal)) + (_fake() if balanced else b"")
    return bytes(out) + (b";" if balanced else _frame(2, 2, 1))


_PALETTE = bytes([0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255])
_HEAD = b"GIF89a\x02\x00\x02\x00\x81\x00\x00" + _PALETTE


def netscape_hidden_gif(big: tuple[int, int], disposal: int = 0) -> bytes:
    """A loop extension without its count block: Pillow reads one more chain, so `big` is its frame 0 and the walk
    (which ends the extension at the terminator) sees it only as data."""
    hidden = b"\x21\xff\x0bNETSCAPE2.0\x00" + bytes([0x21, 0x01, 51]) + b"\x01" * 31 + b"\x00"
    return _HEAD + hidden + _frame(big[0], big[1], 2, disposal) + _frame(2, 2, 1) + _frame(2, 2, 3) + b";"


def netscape_aligned_gif(height: int = 10, later_height: int = 8) -> bytes:
    """The same quirk with two different frame-0 descriptors that share one pixel-data offset: offsets and frame
    counts agree, only the rectangle (11264 x height for Pillow, 1 x 1 for a one-chain walk) differs."""
    chain = bytearray(b"\x01" * 35)
    chain[0], chain[1], chain[2], chain[34] = 0x21, 0x01, 37, 0
    descriptor = b"\x2c\x00\x00\x00\x00\x00\x2c" + height.to_bytes(2, "little") + b"\x80"
    frame0 = descriptor + bytes([0, 1, 0, 1, 0, 0]) + b"\x02" + _sub_blocks(_uniform_lzw(0x2C00 * height, 1))
    later = b"".join(
        b"\x2c\x00\x00\x00\x00\x01\x00"
        + later_height.to_bytes(2, "little")
        + b"\x00\x02"
        + _sub_blocks(_uniform_lzw(later_height, 2))
        for _ in range(4)
    )
    return _HEAD + b"\x21\xff\x0bNETSCAPE2.0\x00" + bytes(chain) + frame0 + later + b";"


def comment_flood_gif(count: int, sub_block: bytes = b"") -> bytes:
    """`count` comment extensions (each a single sub-block `sub_block`, empty by default) before two tiny frames."""
    if sub_block:
        comments = b"\x21\xfe" + (bytes([len(sub_block)]) + sub_block) * count + b"\x00"
    else:
        comments = b"\x21\xfe\x00" * count
    return _HEAD + comments + _frame(2, 2, 1) + _frame(2, 2, 2) + b";"
