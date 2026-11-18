from assertpy import assert_that

from decker.animation.load import LoadMonitor


def test_busy_fraction_over_window() -> None:
    monitor = LoadMonitor()
    # 0.5 s of writing in each of the seconds 100..109, then 0.1 s in 110..119.
    for second in range(100, 110):
        monitor.record_write(second + 0.6, 0.5, 0)
    for second in range(110, 120):
        monitor.record_write(second + 0.6, 0.1, 0)

    assert_that(monitor.busy_fraction(120.0, 5.0)).is_close_to(0.1, 1e-9)
    assert_that(monitor.busy_fraction(120.0, 20.0)).is_close_to(0.3, 1e-9)
    # The window edge falls mid-bucket: the last 30% of second 107 counts.
    assert_that(monitor.busy_fraction(112.7, 5.0)).is_close_to((0.5 * 0.3 + 0.5 * 2 + 0.1 * 3) / 5.0, 1e-9)
    assert_that(monitor.busy_fraction(200.0, 5.0)).is_equal_to(0.0)


def test_write_spanning_a_bucket_boundary_is_split_between_buckets() -> None:
    monitor = LoadMonitor()
    monitor.record_write(10.25, 0.5, 0)

    assert_that(monitor.busy_fraction(10.0, 1.0)).is_close_to(0.25, 1e-9)
    assert_that(monitor.busy_fraction(11.0, 1.0)).is_close_to(0.25, 1e-9)
    assert_that(monitor.busy_fraction(11.0, 2.0)).is_close_to(0.25, 1e-9)


def test_seconds_per_report_ewma_tracks_measured_cost() -> None:
    monitor = LoadMonitor()
    assert_that(monitor.seconds_per_report).is_equal_to(0.00025)

    monitor.record_write(1.0, 0.002, 4)
    assert_that(monitor.seconds_per_report).is_greater_than(0.00025).is_less_than(0.0005)
    for index in range(300):
        monitor.record_write(1.0 + index * 0.01, 0.002, 4)
    assert_that(monitor.seconds_per_report).is_close_to(0.0005, 1e-6)

    monitor.record_write(5.0, 0.1, 0)
    assert_that(monitor.seconds_per_report).is_close_to(0.0005, 1e-6)


def test_lag_over_requires_sustained_lag() -> None:
    monitor = LoadMonitor()
    assert_that(monitor.lag_over(10.0, 0.25, 1.0)).is_false()

    for tick in range(10):
        monitor.record_lag(10.0 + tick * 0.1, 0.3)
    assert_that(monitor.lag_over(10.9, 0.25, 1.0)).is_false()
    monitor.record_lag(11.0, 0.3)
    assert_that(monitor.lag_over(11.0, 0.25, 1.0)).is_true()
    assert_that(monitor.last_lag_s).is_equal_to(0.3)

    monitor.record_lag(11.2, 0.1)
    for tick in range(1, 10):
        monitor.record_lag(11.2 + tick * 0.1, 0.4)
    assert_that(monitor.lag_over(12.1, 0.25, 1.0)).is_false()
    monitor.record_lag(12.3, 0.4)
    assert_that(monitor.lag_over(12.3, 0.25, 1.0)).is_true()


def test_old_samples_are_dropped_but_the_one_in_effect_is_kept() -> None:
    monitor = LoadMonitor()
    monitor.record_write(1.5, 0.5, 0)
    monitor.record_lag(1.0, 0.5)
    monitor.record_lag(500.0, 0.5)

    assert_that(monitor.busy_fraction(2.0, 5.0)).is_close_to(0.1, 1e-9)
    assert_that(monitor.lag_over(500.0, 0.25, 1.0)).is_true()
    monitor.record_write(500.5, 0.1, 0)
    assert_that(monitor.busy_fraction(2.0, 5.0)).is_equal_to(0.0)
