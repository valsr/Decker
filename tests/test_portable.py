import sys
from pathlib import Path

import pytest
from assertpy import assert_that

from tests.portable import entry_name, install_launcher


def test_windows_entry_is_a_cmd_wrapper_running_the_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    script = tmp_path / "tool.py"
    script.write_text("print(1)\n")
    launcher = install_launcher(script)
    assert_that(entry_name("tool.py")).is_equal_to("tool.cmd")
    assert_that(launcher.name).is_equal_to("tool.cmd")
    assert_that(launcher.read_text()).contains(sys.executable).contains("%~dp0tool.py")


def test_posix_entry_is_the_executable_script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    script = tmp_path / "tool.py"
    script.write_text("print(1)\n")
    assert_that(install_launcher(script)).is_equal_to(script)
    assert_that(entry_name("tool.py")).is_equal_to("tool.py")
