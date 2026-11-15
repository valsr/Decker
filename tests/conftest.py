from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_sdk_dir(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep PluginManager.create from staging the SDK into the real home directory."""
    sdk_root: Path = tmp_path_factory.mktemp("sdk")
    monkeypatch.setattr("decker.common.paths.sdk", lambda: sdk_root)
