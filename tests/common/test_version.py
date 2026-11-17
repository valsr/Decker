import pytest
from assertpy import assert_that

from decker.common import version


def test_none_specifier_is_compatible():
    assert_that(version.is_compatible(None, "0.1.0")).is_true()
    assert_that(version.is_compatible("", "0.1.0")).is_true()


def test_prerelease_matches():
    assert_that(version.is_compatible(">=0.2", "0.3.0.dev1")).is_true()


def test_excluded():
    assert_that(version.is_compatible(">=1.0", "0.2.0")).is_false()


def test_invalid_specifier_is_incompatible():
    assert_that(version.is_compatible("not a spec", "0.2.0")).is_false()


def test_default_uses_decker_version(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(version, "decker_version", lambda: "0.5.0")
    assert_that(version.is_compatible(">=0.5")).is_true()
    assert_that(version.is_compatible(">=0.6")).is_false()
