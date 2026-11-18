"""SVG safety validation for imported icons."""

import pytest
from assertpy import assert_that

from decker.asset.svgcheck import validate_svg

_NS = 'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'


def _svg(body: str, attrs: str = "") -> bytes:
    return f"<svg {_NS} {attrs}>{body}</svg>".encode()


def test_accepts_a_plain_svg() -> None:
    validate_svg(_svg("<rect/>"))


def test_accepts_internal_and_data_image_hrefs() -> None:
    validate_svg(_svg('<defs><g id="a"/></defs><use href="#a"/><use xlink:href="#a"/>'))
    validate_svg(_svg('<image href="data:image/png;base64,AAAA"/>'))


@pytest.mark.parametrize(
    "data",
    [
        _svg("<script>alert(1)</script>"),
        _svg("<foreignObject/>"),
        _svg("<rect/>", 'onload="x"'),
        _svg('<image href="http://x/y.png"/>'),
        _svg('<image xlink:href="file:///etc/passwd"/>'),
        b'<!DOCTYPE svg [<!ENTITY a "b">]><svg xmlns="http://www.w3.org/2000/svg"/>',
        b'<!doctype svg><svg xmlns="http://www.w3.org/2000/svg"/>',
        b'<html xmlns="http://www.w3.org/1999/xhtml"/>',
        b"not xml at all",
        b"\xff\xfe\x00",
    ],
)
def test_rejects_unsafe_or_invalid_data(data: bytes) -> None:
    with pytest.raises(ValueError):
        validate_svg(data)


def test_rejection_carries_a_reason() -> None:
    with pytest.raises(ValueError) as info:
        validate_svg(_svg("<script/>"))
    assert_that(str(info.value)).contains("script")


_EVIL = '<!DOCTYPE svg [<!ENTITY a "b">]><svg xmlns="http://www.w3.org/2000/svg"><text>&a;</text></svg>'
_PLAIN = '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
@pytest.mark.parametrize("text", [_EVIL, _PLAIN])
def test_rejects_bom_less_utf16(encoding: str, text: str) -> None:
    with pytest.raises(ValueError):
        validate_svg(text.encode(encoding))


def test_rejects_a_non_utf8_encoding_declaration() -> None:
    with pytest.raises(ValueError):
        validate_svg(f'<?xml version="1.0" encoding="UTF-16"?>{_PLAIN}'.encode())


@pytest.mark.parametrize("name", ["UTF-8", "utf-8"])
def test_accepts_a_utf8_encoding_declaration(name: str) -> None:
    validate_svg(f"<?xml version='1.0' encoding='{name}'?>{_PLAIN}".encode())
