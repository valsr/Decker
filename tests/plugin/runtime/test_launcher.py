from pathlib import Path

import pytest
from assertpy import assert_that

from decker.plugin.manifest import RuntimeSpec
from decker.plugin.runtime.launcher import launch_command, launch_env


def test_python_uses_plugin_venv_uses_plugin_venv(tmp_path: Path) -> None:
    cmd = launch_command(tmp_path, RuntimeSpec("python", "main.py"))
    assert_that(cmd[0]).is_equal_to(str(tmp_path / ".venv/bin/python"))
    assert_that(cmd[1:3]).is_equal_to(["-m", "decker_plugin_sdk"])


def test_executable_runs_entry_directly(tmp_path: Path) -> None:
    cmd = launch_command(tmp_path, RuntimeSpec("executable", "bin/run"))
    assert_that(cmd).is_equal_to([str(tmp_path / "bin/run")])


def test_entry_outside_plugin_dir_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        launch_command(tmp_path, RuntimeSpec("python", "../evil.py"))
    with pytest.raises(ValueError):
        launch_command(tmp_path, RuntimeSpec("executable", "/bin/sh"))


def test_env_is_minimal_and_has_sdk_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_TOKEN", "x")
    env = launch_env(tmp_path)
    assert_that(env).contains_key("PATH", "HOME", "LANG")
    assert_that(env).does_not_contain_key("SECRET_TOKEN")
    assert_that(env["PYTHONUNBUFFERED"]).is_equal_to("1")
    assert_that(env["PYTHONPATH"]).is_equal_to(str(tmp_path))
    assert_that(launch_env(None)).does_not_contain_key("PYTHONPATH")
