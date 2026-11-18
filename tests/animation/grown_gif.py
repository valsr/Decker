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


def grown_gif(logical: tuple[int, int], frame_sizes: list[tuple[int, int]]) -> bytes:
    """A GIF with the given logical screen and one uniform-colour frame per size, each drawn at the origin."""
    palette = bytes([0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255])
    out = bytearray(b"GIF89a")
    out += logical[0].to_bytes(2, "little") + logical[1].to_bytes(2, "little") + b"\x81\x00\x00" + palette
    out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    for index, (width, height) in enumerate(frame_sizes):
        out += b"\x21\xf9\x04\x00\x0a\x00\x00\x00"
        out += b"\x2c\x00\x00\x00\x00" + width.to_bytes(2, "little") + height.to_bytes(2, "little") + b"\x00"
        out += b"\x02" + _sub_blocks(_uniform_lzw(width * height, 1 + index % 3))
    return bytes(out + b"\x3b")
