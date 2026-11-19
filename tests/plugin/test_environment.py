import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from assertpy import assert_that

from decker.plugin import environment
from decker.plugin.environment import (
    EnvironmentBuildError,
    build_environment,
    stage_sdk,
    venv_python,
)
from decker.plugin.manifest import RuntimeSpec
from tests.portable import fake_executable

needs_uv = pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")


def _runtime(requirements: tuple[str, ...] = ()) -> RuntimeSpec:
    return RuntimeSpec(type="python", entry="main.py", requirements=requirements)


def _make_wheel(directory: Path) -> None:
    directory.mkdir(parents=True)
    dist = "tinypkg-0.1.dist-info"
    with zipfile.ZipFile(directory / "tinypkg-0.1-py3-none-any.whl", "w") as wheel:
        wheel.writestr("tinypkg/__init__.py", "VALUE = 1\n")
        wheel.writestr(f"{dist}/METADATA", "Metadata-Version: 2.1\nName: tinypkg\nVersion: 0.1\n")
        wheel.writestr(
            f"{dist}/WHEEL", "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        )
        wheel.writestr(f"{dist}/RECORD", "")


def test_stage_sdk_copies_package_and_is_idempotent(tmp_path: Path) -> None:
    first = stage_sdk(tmp_path)
    package = first / "decker_plugin_sdk"
    assert_that(first.parent).is_equal_to(tmp_path)
    assert_that((package / "__init__.py").exists()).is_true()
    assert_that(list(package.rglob("__pycache__"))).is_empty()
    marker = package / "marker"
    marker.write_text("x")
    second = stage_sdk(tmp_path)
    assert_that(second).is_equal_to(first)
    assert_that(marker.exists()).is_true()
    assert_that([p.name for p in first.iterdir()]).is_equal_to(["decker_plugin_sdk"])


@pytest.mark.slow
@needs_uv
def test_build_creates_venv_with_server_python_when_no_spec(tmp_path: Path) -> None:
    lines: list[str] = []
    build_environment(tmp_path, _runtime(), lines.append)
    result = subprocess.run(
        [str(venv_python(tmp_path)), "-c", "import sys; print(sys.version_info[:2])"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert_that(result.stdout.strip()).is_equal_to(str(sys.version_info[:2]))
    assert_that(lines).is_not_empty()


@pytest.mark.slow
@needs_uv
def test_build_installs_requirements(tmp_path: Path) -> None:
    wheels = tmp_path / "wheels"
    _make_wheel(wheels)
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    build_environment(
        plugin, _runtime(("tinypkg",)), lambda _: None, extra_args=["--no-index", "--find-links", str(wheels)]
    )
    subprocess.run([str(venv_python(plugin)), "-c", "import tinypkg"], check=True)


def test_missing_uv_raises(tmp_path: Path) -> None:
    assert_that(build_environment).raises(EnvironmentBuildError).when_called_with(
        tmp_path, _runtime(), lambda _: None, uv=str(tmp_path / "no-such-uv")
    )


def test_failed_install_raises_with_output(tmp_path: Path) -> None:
    fake = fake_executable(
        tmp_path / "fakeuv", "import sys\nfor i in range(1, 31):\n    print(f'line{i}')\nsys.exit(1)\n"
    )
    seen: list[str] = []
    with pytest.raises(EnvironmentBuildError) as info:
        build_environment(tmp_path, _runtime(), seen.append, uv=str(fake))
    message = str(info.value)
    assert_that(message).contains("line30").contains("line11").does_not_contain("line10\n")
    assert_that(seen).is_length(30)
    assert_that(environment.EnvironmentBuildError).is_not_none()


def test_venv_is_built_relocatable(tmp_path: Path) -> None:
    argv_log = tmp_path / "argv.log"
    fake = fake_executable(
        tmp_path / "fakeuv",
        f"import sys\nwith open({str(argv_log)!r}, 'a') as log:\n    log.write(' '.join(sys.argv[1:]) + '\\n')\n",
    )

    build_environment(tmp_path, _runtime(), lambda _: None, uv=str(fake))

    assert_that(argv_log.read_text()).starts_with("venv --relocatable ")


def test_timeout_kills_the_whole_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(environment, "_TIMEOUT_SECONDS", 1)
    import time

    start = time.monotonic()
    with pytest.raises(EnvironmentBuildError, match="timed out"):
        environment._run(["sh", "-c", "sleep 30 & sleep 30"], lambda _line: None)
    assert_that(time.monotonic() - start).is_less_than(10)


def test_stage_sdk_is_keyed_on_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = stage_sdk(tmp_path)
    monkeypatch.setattr(environment, "_sdk_digest", lambda _source: "changed")
    assert_that(stage_sdk(tmp_path)).is_not_equal_to(first)


def test_python_request_enforces_minimum() -> None:
    assert_that(environment._python_request("3.12")).is_equal_to("3.12")
    assert_that(environment._python_request(">=3.8")).is_equal_to(">=3.8,>=3.10")
    with pytest.raises(EnvironmentBuildError, match="older"):
        environment._python_request("3.9")


def test_venv_python_uses_scripts_on_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    assert_that(venv_python(tmp_path)).is_equal_to(tmp_path / ".venv" / "Scripts" / "python.exe")


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_venv_python_uses_bin_elsewhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    assert_that(venv_python(tmp_path)).is_equal_to(tmp_path / ".venv" / "bin" / "python")
