import pytest
from assertpy import assert_that

from decker.animation.controller import (
    LADDER,
    Demand,
    Level,
    LevelController,
    LoadSample,
    ladder_for,
)

SECONDS_PER_REPORT = 0.00025
KEYS = 32
L0, L1, L2, L3 = LADDER[0], LADDER[1], LADDER[2], LADDER[3]


def _demand_for(native_fps: int) -> Demand:
    def demand(level: Level) -> float:
        fps = native_fps if level.fps_cap is None else min(native_fps, level.fps_cap)
        reports_per_frame = {100: 6.75, 90: 3.0, 75: 2.0}[level.quality]
        return KEYS * reports_per_frame * fps

    return demand


def _controller_at(level_index: int) -> LevelController:
    controller = LevelController(LADDER)
    controller.replan(lambda level: 0.0 if level is LADDER[0] else 1e9, SECONDS_PER_REPORT)
    # Walk down to the wanted rung via fast-path steps.
    for step in range(level_index):
        controller.tick(LoadSample(float(step), 0.9, 0.9, 0.0), _demand_for(10), SECONDS_PER_REPORT)
    assert_that(controller.level).is_equal_to(LADDER[level_index])
    return controller


@pytest.mark.parametrize(("native_fps", "expected"), [(10, L0), (24, L1), (50, L2)])
def test_replan_for_10fps_picks_L0_24fps_picks_L1_50fps_picks_q90_30(native_fps: int, expected: Level) -> None:
    controller = LevelController(LADDER)

    assert_that(controller.replan(_demand_for(native_fps), SECONDS_PER_REPORT)).is_equal_to(expected)
    assert_that(controller.level).is_equal_to(expected)


def test_replan_picks_last_rung_when_nothing_fits_and_moves_up_without_cooldown() -> None:
    controller = LevelController(LADDER)

    assert_that(controller.replan(lambda _: 1e9, SECONDS_PER_REPORT)).is_equal_to(LADDER[-1])
    assert_that(controller.replan(_demand_for(10), SECONDS_PER_REPORT)).is_equal_to(L0)


def test_steps_down_one_rung_when_5s_busy_exceeds_75_percent() -> None:
    controller = _controller_at(0)

    level = controller.tick(LoadSample(10.0, 0.80, 0.80, 0.0), _demand_for(24), SECONDS_PER_REPORT)

    assert_that(level).is_equal_to(L1)


def test_does_not_step_down_at_or_below_75_percent_and_stops_at_last_rung() -> None:
    controller = _controller_at(0)
    assert_that(controller.tick(LoadSample(1.0, 0.75, 0.75, 0.0), _demand_for(10), SECONDS_PER_REPORT)).is_equal_to(L0)

    bottom = LevelController(LADDER)
    bottom.replan(lambda _: 1e9, SECONDS_PER_REPORT)
    assert_that(bottom.tick(LoadSample(1.0, 0.99, 0.99, 1.0), _demand_for(10), SECONDS_PER_REPORT)).is_equal_to(
        LADDER[-1]
    )


def test_does_not_step_up_before_30s_after_a_step_down() -> None:
    controller = _controller_at(0)
    demand = _demand_for(10)
    controller.tick(LoadSample(100.0, 0.80, 0.80, 0.0), demand, SECONDS_PER_REPORT)
    assert_that(controller.level).is_equal_to(L1)

    early = controller.tick(LoadSample(129.0, 0.24, 0.24, 0.0), demand, SECONDS_PER_REPORT)
    later = controller.tick(LoadSample(130.0, 0.24, 0.24, 0.0), demand, SECONDS_PER_REPORT)

    assert_that(early).is_equal_to(L1)
    assert_that(later).is_equal_to(L0)


def test_does_not_step_up_when_projection_exceeds_65_percent() -> None:
    controller = _controller_at(1)

    level = controller.tick(LoadSample(500.0, 0.58, 0.40, 0.0), _demand_for(24), SECONDS_PER_REPORT)

    assert_that(level).is_equal_to(L1)


def test_steps_up_when_20s_busy_below_50_percent_and_projection_fits() -> None:
    controller = _controller_at(1)

    level = controller.tick(LoadSample(500.0, 0.24, 0.24, 0.0), _demand_for(10), SECONDS_PER_REPORT)

    assert_that(level).is_equal_to(L0)


def test_does_not_step_up_when_20s_busy_is_50_percent_or_more() -> None:
    controller = _controller_at(1)

    level = controller.tick(LoadSample(500.0, 0.30, 0.50, 0.0), _demand_for(10), SECONDS_PER_REPORT)

    assert_that(level).is_equal_to(L1)


def test_does_not_step_up_when_current_demand_is_zero() -> None:
    controller = _controller_at(1)

    level = controller.tick(LoadSample(500.0, 0.0, 0.0, 0.0), lambda _: 0.0, SECONDS_PER_REPORT)

    assert_that(level).is_equal_to(L1)


def test_lag_over_250ms_steps_down_immediately_even_if_busy_is_low() -> None:
    controller = _controller_at(0)

    level = controller.tick(LoadSample(5.0, 0.10, 0.10, 0.251), _demand_for(10), SECONDS_PER_REPORT)

    assert_that(level).is_equal_to(L1)


@pytest.mark.parametrize(("native_fps", "expected"), [(10, L0), (24, L1), (50, L2)])
def test_no_oscillation_over_a_600s_simulated_steady_load(native_fps: int, expected: Level) -> None:
    controller = LevelController(LADDER)
    demand = _demand_for(native_fps)
    changes_after_settling = 0

    for second in range(600):
        busy = demand(controller.level) * SECONDS_PER_REPORT
        before = controller.level
        controller.tick(LoadSample(float(second), busy, busy, 0.0), demand, SECONDS_PER_REPORT)
        if second >= 60:
            changes_after_settling += controller.level != before

    assert_that(controller.level).is_equal_to(expected)
    assert_that(changes_after_settling).is_equal_to(0)


def test_does_not_step_up_when_only_the_projection_blocks_it() -> None:
    controller = _controller_at(1)

    level = controller.tick(LoadSample(500.0, 0.45, 0.45, 0.0), _demand_for(24), SECONDS_PER_REPORT)

    assert_that(level).is_equal_to(L1)


def test_bmp_ladder_has_no_quality_change() -> None:
    ladder = ladder_for(bmp=True)

    assert_that({level.quality for level in ladder}).is_equal_to({100})
    assert_that([level.fps_cap for level in ladder]).is_equal_to([None, 30, 20, 15, 10, 5])
    assert_that(ladder_for(bmp=False)).is_equal_to(LADDER)
