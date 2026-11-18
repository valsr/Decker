from assertpy import assert_that

from scripts.bench_usb_writes import key_counts, percentile, reports_for, summarize


def test_reports_for_rounds_up_and_is_at_least_one():
    assert_that(reports_for(1016, 1016)).is_equal_to(1)
    assert_that(reports_for(1017, 1016)).is_equal_to(2)
    assert_that(reports_for(0, 1016)).is_equal_to(1)


def test_percentile_uses_nearest_rank():
    values = [float(i) for i in range(1, 101)]
    assert_that(percentile(values, 0.5)).is_equal_to(50.0)
    assert_that(percentile(values, 0.99)).is_equal_to(99.0)
    assert_that(percentile([], 0.5)).is_equal_to(0.0)


def test_summarize_computes_rates_and_latency():
    stats = summarize([0.001, 0.002, 0.003, 0.004], [2032, 2032, 1016, 1016], elapsed=2.0, payload=1016)

    assert_that(stats.frames_per_s).is_equal_to(2.0)
    assert_that(stats.reports_per_s).is_equal_to(3.0)
    assert_that(stats.mb_per_s).is_close_to(6096 / 2.0 / 1e6, 1e-9)
    assert_that(stats.mean_ms).is_close_to(2.5, 1e-9)
    assert_that(stats.p50_ms).is_close_to(2.0, 1e-9)
    assert_that(stats.p99_ms).is_close_to(4.0, 1e-9)


def test_summarize_of_nothing_is_all_zero():
    assert_that(summarize([], [], 1.0, 1016).frames_per_s).is_equal_to(0.0)


def test_key_counts_are_distinct_and_capped_by_the_deck():
    assert_that(key_counts(32)).is_equal_to([1, 8, 32])
    assert_that(key_counts(6)).is_equal_to([1, 6])
    assert_that(key_counts(15)).is_equal_to([1, 8, 15])
