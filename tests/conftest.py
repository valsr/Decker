import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_sdk_dir(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep PluginManager.create from staging the SDK into the real home directory."""
    sdk_root: Path = tmp_path_factory.mktemp("sdk")
    monkeypatch.setattr("decker.common.paths.sdk", lambda: sdk_root)


@pytest.fixture(autouse=True)
def _no_system_icon_themes(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the registry's System Icons from reading the machine's real icon themes and desktop settings."""
    empty: Path = tmp_path_factory.mktemp("no-icons")
    monkeypatch.setenv("HOME", str(empty))
    monkeypatch.setenv("XDG_DATA_HOME", str(empty / "data"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(empty / "share"))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip tests marked for a platform the suite is not running on."""
    rules = (
        ("posix_only", sys.platform == "win32", "needs POSIX process groups and signals (not available on Windows)"),
        ("linux_only", sys.platform != "linux", "needs Linux-only behaviour"),
        ("windows_only", sys.platform != "win32", "needs Windows process groups (plugin runtime)"),
    )
    for marker, skip, reason in rules:
        if skip:
            for item in items:
                if marker in item.keywords:
                    item.add_marker(pytest.mark.skip(reason=reason))
