"""Safety validation for SVG icons imported by the user."""

import re
from xml.etree import ElementTree

_DOCTYPE = re.compile(r"<!\s*(doctype|entity)", re.IGNORECASE)
_FORBIDDEN_TAGS = frozenset({"script", "foreignobject"})
_ALLOWED_HREF_PREFIXES = ("#", "data:image/")


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _check_attributes(element: ElementTree.Element) -> None:
    for key, value in element.attrib.items():
        name = _local(key).lower()
        if name.startswith("on"):
            raise ValueError(f"event handler attribute not allowed: {name}")
        if name == "href" and not value.strip().lower().startswith(_ALLOWED_HREF_PREFIXES):
            raise ValueError("external references are not allowed")


def validate_svg(data: bytes) -> None:
    """Raise ValueError(reason) unless data is a self-contained SVG without scripts, entities or external references."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("not valid UTF-8 text") from exc
    if _DOCTYPE.search(text):
        raise ValueError("DOCTYPE and ENTITY declarations are not allowed")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise ValueError(f"not valid XML: {exc}") from exc
    if _local(root.tag).lower() != "svg":
        raise ValueError("root element is not svg")
    for element in root.iter():
        tag = _local(element.tag).lower() if isinstance(element.tag, str) else ""
        if tag in _FORBIDDEN_TAGS:
            raise ValueError(f"{tag} elements are not allowed")
        _check_attributes(element)
