"""Decker version lookup and plugin compatibility checks."""

from importlib import metadata

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion


def decker_version() -> str:
    """Return the installed Decker version, or "0" when the package is not installed."""
    try:
        return metadata.version("decker")
    except metadata.PackageNotFoundError:
        return "0"


def is_compatible(specifier: str | None, version: str | None = None) -> bool:
    """Return whether version (default: this Decker) satisfies specifier; an invalid specifier is incompatible."""
    if not specifier:
        return True
    try:
        return SpecifierSet(specifier).contains(version if version is not None else decker_version(), prereleases=True)
    except (InvalidSpecifier, InvalidVersion):
        return False
