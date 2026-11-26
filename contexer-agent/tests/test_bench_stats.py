"""A benchmark rate says how sure it is, and two results are only called different when they are."""

from __future__ import annotations

import pytest

from contexer.bench.stats import Rate, compare, difference, sentence


def test_the_interval_is_the_wilson_score_interval() -> None:
    # Reference values: 5 of 10 is 0.2366 to 0.7634 in every table of the Wilson interval.
    assert Rate(5, 10).interval() == pytest.approx((0.2366, 0.7634), abs=0.0005)
    # A perfect score still leaves room below it, and no failure seen still leaves room above zero.
    assert Rate(40, 40).interval() == pytest.approx((0.9124, 1.0), abs=0.0005)
    assert Rate(0, 44).interval() == pytest.approx((0.0, 0.0803), abs=0.0005)
    low, high = Rate(25, 40).interval() or (0.0, 0.0)
    assert low == pytest.approx(0.4703, abs=0.0005) and high == pytest.approx(0.7578, abs=0.0005)


def test_a_rate_with_no_runs_has_no_interval_and_says_so() -> None:
    assert Rate(0, 0).interval() is None
    assert Rate(0, 0).text() == "0/0, nothing ran"


def test_a_rate_is_written_with_its_count_and_its_interval() -> None:
    assert Rate(40, 40).text() == "40/40, 100% (95% interval 91% to 100%)"
    assert Rate(0, 44).text() == "0/44, 0% (95% interval 0% to 8%)"
    assert Rate(25, 40).text() == "25/40, 62% (95% interval 47% to 76%)"
    assert sentence({"seeded bugs found": Rate(25, 40), "clean runs with a false alarm": Rate(0, 22)}) == (
        "seeded bugs found 25/40, 62% (95% interval 47% to 76%); "
        "clean runs with a false alarm 0/22, 0% (95% interval 0% to 15%)"
    )


def test_the_difference_of_two_rates_is_newcombes_interval() -> None:
    # Newcombe 1998, the worked example 56/70 against 48/80: +0.0524 to +0.3339.
    assert difference(Rate(56, 70), Rate(48, 80)) == pytest.approx((0.0524, 0.3339), abs=0.0005)
    assert difference(Rate(1, 1), Rate(0, 0)) is None


def test_two_runs_of_the_same_configuration_cannot_be_told_apart() -> None:
    assert compare(Rate(25, 40), Rate(25, 40)).startswith("cannot be told apart")
    # The two tester runs in RESULTS.md: 24 of 35 and then 21 of the same 35. Not a regression that was shown.
    assert compare(Rate(21, 35), Rate(24, 35)).startswith("cannot be told apart")
    assert compare(Rate(0, 44), Rate(0, 44)).startswith("cannot be told apart")
    assert "-20 to +20 points" in compare(Rate(25, 40), Rate(25, 40))


def test_a_difference_larger_than_the_noise_is_named_with_its_direction() -> None:
    assert compare(Rate(40, 40), Rate(20, 40)).startswith("higher")
    assert compare(Rate(20, 40), Rate(40, 40)).startswith("lower")
    assert compare(Rate(56, 70), Rate(48, 80)) == "higher (95% interval for the difference: +5 to +33 points)"


def test_a_rate_with_no_runs_is_not_compared() -> None:
    assert compare(Rate(3, 6), Rate(0, 0)) == "not compared: one of the two has no runs"
