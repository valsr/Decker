"""Plugin variables and the Switch card together: a card shown by a Switch follows variable changes."""

from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that

from decker.server import plugins as plugins_module
from tests.server.test_plugins_switch import _RED, SwitchEnv, _card
from tests.server.test_plugins_variables import (
    _answer,
    _fake_processes,
    _plugin,
    _started,
    _wait_until,
)


@pytest.fixture(name="env")
def env_fixture(tmp_path: Path) -> Any:
    environment = SwitchEnv(tmp_path)
    yield environment
    environment.manager.destroy()


def _record_titles(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    titles: list[str] = []
    real = plugins_module.compose_key_face

    def recording(appearance: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        titles.append(appearance["title"]["text"])
        return real(appearance, *args, **kwargs)

    monkeypatch.setattr(plugins_module, "compose_key_face", recording)
    return titles


def test_variable_change_redraws_a_card_shown_by_a_switch(env: SwitchEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    titles = _record_titles(monkeypatch)
    procs = _fake_processes(env.manager)
    proc = _started(env.manager, procs, _plugin(env.tmp_path, "com.t.vars", [{"name": "media_volume"}]))
    env.place(display=_card(_RED, title={"text": "Vol {media_volume}"}))
    assert_that(env.live()).contains_key("sw", "sw:display")

    _answer(proc, "media_volume", 40)

    assert_that(_wait_until(lambda: titles[-1:] == ["Vol 40"])).is_true()
    assert_that(env.live()).contains_key("sw:display")  # redrawn in place, not rebuilt or dropped


def test_a_stopped_variable_plugin_clears_the_text_of_a_card_shown_by_a_switch(
    env: SwitchEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    titles = _record_titles(monkeypatch)
    procs = _fake_processes(env.manager)
    proc = _started(env.manager, procs, _plugin(env.tmp_path, "com.t.vars", [{"name": "media_volume"}]))
    env.place(display=_card(_RED, title={"text": "Vol {media_volume}"}))
    _answer(proc, "media_volume", 40)
    assert_that(_wait_until(lambda: titles[-1:] == ["Vol 40"])).is_true()

    proc.crash()

    assert_that(env.manager.variables.snapshot()).is_empty()
    assert_that(_wait_until(lambda: titles[-1:] == ["Vol "])).is_true()
    assert_that(env.live()).contains_key("sw", "sw:display")
