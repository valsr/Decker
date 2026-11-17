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
