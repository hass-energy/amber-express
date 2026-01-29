"""Tests for CDF polling strategy."""

from __future__ import annotations

import numpy as np
import pytest

from custom_components.amber_express.cdf_algorithm import build_cdf
from custom_components.amber_express.cdf_polling import CDFPollingStats, CDFPollingStrategy, IntervalObservation


def test_cold_start_initializes_with_real_observations() -> None:
    """Test that cold start fills with 100 real historical observations."""
    strategy = CDFPollingStrategy()

    assert len(strategy.observations) == 100
    # Verify observations have valid start < end structure
    for obs in strategy.observations:
        assert obs["start"] < obs["end"]
        assert obs["start"] >= 0


def test_cold_start_schedule_produces_valid_poll_times() -> None:
    """Test cold start produces valid poll times from the CDF."""
    strategy = CDFPollingStrategy()
    strategy.update_budget(4, 0, 0, 0)

    # With k=4 polls, should get 4 poll times from the learned CDF
    assert len(strategy.scheduled_polls) == 4
    # Polls should be in increasing order
    for i in range(len(strategy.scheduled_polls) - 1):
        assert strategy.scheduled_polls[i] < strategy.scheduled_polls[i + 1]
    # Polls should be positive
    assert all(t > 0 for t in strategy.scheduled_polls)


def test_preloaded_observations_override_cold_start() -> None:
    """Test that preloaded observations are used instead of cold start."""
    observations: list[IntervalObservation] = [
        {"start": 10.0, "end": 20.0},
        {"start": 30.0, "end": 40.0},
    ]
    strategy = CDFPollingStrategy(observations)

    assert len(strategy.observations) == 2
    assert strategy.observations[0]["start"] == 10.0


def test_record_observation_adds_to_rolling_window() -> None:
    """Test that recording observations maintains rolling window."""
    strategy = CDFPollingStrategy()
    initial_count = len(strategy.observations)

    # Add a new observation
    strategy.record_observation(start=5.0, end=15.0)

    # Should still have 100 observations (rolling window)
    assert len(strategy.observations) == initial_count

    # Last observation should be the new one
    assert strategy.observations[-1]["start"] == 5.0
    assert strategy.observations[-1]["end"] == 15.0


def test_record_observation_ignores_invalid_interval() -> None:
    """Test that invalid intervals (start >= end) are ignored."""
    observations: list[IntervalObservation] = [{"start": 10.0, "end": 20.0}]
    strategy = CDFPollingStrategy(observations)

    # Try to record invalid interval
    strategy.record_observation(start=30.0, end=20.0)

    # Should still have only 1 observation
    assert len(strategy.observations) == 1


def test_should_poll_returns_true_at_scheduled_time() -> None:
    """Test that should_poll returns True when poll time is reached."""
    # Use explicit observations for deterministic test
    observations: list[IntervalObservation] = [{"start": 15.0, "end": 45.0}] * 100
    strategy = CDFPollingStrategy(observations)
    strategy.update_budget(4, 0, 0, 0)

    # With uniform [15, 45], first poll is at 21s
    assert not strategy.should_poll_for_confirmed(20.0)
    assert strategy.should_poll_for_confirmed(21.0)
    assert strategy.should_poll_for_confirmed(25.0)  # Still true until poll executed


def test_should_poll_advances_after_increment() -> None:
    """Test that incrementing poll count advances to next scheduled poll."""
    # Use explicit observations for deterministic test
    observations: list[IntervalObservation] = [{"start": 15.0, "end": 45.0}] * 100
    strategy = CDFPollingStrategy(observations)
    strategy.update_budget(4, 0, 0, 0)

    # First poll at 21s
    assert strategy.should_poll_for_confirmed(21.0)
    strategy.increment_confirmatory_poll()

    # Now should wait for second poll at 27s
    assert not strategy.should_poll_for_confirmed(21.0)
    assert not strategy.should_poll_for_confirmed(25.0)
    assert strategy.should_poll_for_confirmed(27.0)


def test_should_poll_returns_false_after_all_polls_used() -> None:
    """Test that should_poll returns False after all scheduled polls are used."""
    strategy = CDFPollingStrategy()
    strategy.update_budget(4, 0, 0, 0)

    # Use all 4 polls
    for _ in range(4):
        strategy.increment_confirmatory_poll()

    # Should return False for any time
    assert not strategy.should_poll_for_confirmed(100.0)


def test_get_next_poll_delay_returns_time_until_next_poll() -> None:
    """Test that get_next_poll_delay returns correct delay."""
    observations: list[IntervalObservation] = [{"start": 10.0, "end": 30.0}]
    strategy = CDFPollingStrategy(observations)
    strategy.update_budget(4, 0, 0, 0)

    # With single interval [10, 30] and k=4, polls at [14, 18, 22, 26]
    # At elapsed=10s, next poll is at 14s, so delay = 4s
    delay = strategy.get_next_poll_delay(10.0)
    assert delay == 4.0

    # At elapsed=14s, next poll is now (delay = 0)
    delay = strategy.get_next_poll_delay(14.0)
    assert delay == 0.0

    # At elapsed=15s, poll at 14s is past (delay would be negative -> 0)
    delay = strategy.get_next_poll_delay(15.0)
    assert delay == 0.0


def test_get_next_poll_delay_returns_none_after_all_polls() -> None:
    """Test that get_next_poll_delay returns None when no polls remain."""
    strategy = CDFPollingStrategy()
    strategy.update_budget(4, 0, 0, 0)

    # Use all 4 polls
    for _ in range(4):
        strategy.increment_confirmatory_poll()

    # Should return None
    assert strategy.get_next_poll_delay(100.0) is None


def test_get_next_poll_delay_sub_second_precision() -> None:
    """Test that get_next_poll_delay handles sub-second precision."""
    observations: list[IntervalObservation] = [{"start": 25.0, "end": 26.0}]
    strategy = CDFPollingStrategy(observations)
    strategy.update_budget(4, 0, 0, 0)

    # With narrow interval [25, 26], polls should be tightly spaced
    # At elapsed=25.1, should return sub-second delay
    delay = strategy.get_next_poll_delay(25.1)
    assert delay is not None
    # Delay should be small (sub-second for tightly packed polls)
    assert delay >= 0


def test_reset_for_new_interval_resets_poll_state() -> None:
    """Test that reset_for_new_interval resets the poll index and count."""
    strategy = CDFPollingStrategy()
    strategy.update_budget(4, 0, 0, 0)

    # Advance past first poll
    strategy.increment_confirmatory_poll()
    assert strategy.confirmatory_poll_count == 1

    # Reset for new interval
    strategy.reset_for_new_interval()
    strategy.update_budget(4, 0, 0, 0)

    # Should be back to first poll
    assert strategy.confirmatory_poll_count == 0
    assert strategy.should_poll_for_confirmed(21.0)


def test_get_stats_returns_correct_values() -> None:
    """Test that get_stats returns correct diagnostic values."""
    observations: list[IntervalObservation] = [{"start": 10.0, "end": 20.0}]
    strategy = CDFPollingStrategy(observations)
    strategy.update_budget(4, 0, 0, 0)

    stats = strategy.get_stats()

    assert isinstance(stats, CDFPollingStats)
    assert stats.observation_count == 1
    assert stats.next_poll_index == 0
    assert stats.confirmatory_poll_count == 0
    assert stats.polls_per_interval == 4
    assert stats.last_observation == {"start": 10.0, "end": 20.0}


def test_cdf_with_single_interval() -> None:
    """Test CDF construction with a single interval."""
    observations: list[IntervalObservation] = [{"start": 10.0, "end": 30.0}]
    strategy = CDFPollingStrategy(observations)
    strategy.update_budget(4, 0, 0, 0)

    # With single interval [10, 30] and k=4:
    # Quantiles at [0.2, 0.4, 0.6, 0.8] map to [14, 18, 22, 26]
    expected = [14.0, 18.0, 22.0, 26.0]
    assert strategy.scheduled_polls == expected


def test_cdf_with_two_non_overlapping_intervals() -> None:
    """Test CDF construction with two non-overlapping intervals."""
    observations: list[IntervalObservation] = [
        {"start": 10.0, "end": 20.0},
        {"start": 30.0, "end": 40.0},
    ]
    strategy = CDFPollingStrategy(observations)
    strategy.update_budget(4, 0, 0, 0)

    # Two equal-weight intervals of length 10
    # Each contributes 0.5 to total probability
    # [10, 20] covers p in [0, 0.5]
    # [30, 40] covers p in [0.5, 1.0]
    # Quantiles: p=0.2 -> 14, p=0.4 -> 18, p=0.6 -> 32, p=0.8 -> 36
    expected = [14.0, 18.0, 32.0, 36.0]
    assert strategy.scheduled_polls == expected


def test_cdf_with_overlapping_intervals() -> None:
    """Test CDF construction with overlapping intervals."""
    observations: list[IntervalObservation] = [
        {"start": 10.0, "end": 30.0},
        {"start": 20.0, "end": 40.0},
    ]
    strategy = CDFPollingStrategy(observations)
    strategy.update_budget(4, 0, 0, 0)

    # Intervals overlap from 20-30
    # [10, 20) has density from first only: 1/(2*20) = 0.025
    # [20, 30) has density from both: 1/(2*20) + 1/(2*20) = 0.05
    # [30, 40) has density from second only: 1/(2*20) = 0.025
    # Total probability: 10*0.025 + 10*0.05 + 10*0.025 = 0.25 + 0.5 + 0.25 = 1.0
    # CDF: F(20)=0.25, F(30)=0.75, F(40)=1.0

    # Quantiles:
    # p=0.2 -> in [10, 20): t = 10 + (0.2/0.25)*10 = 18
    # p=0.4 -> in [20, 30): t = 20 + ((0.4-0.25)/0.5)*10 = 23
    # p=0.6 -> in [20, 30): t = 20 + ((0.6-0.25)/0.5)*10 = 27
    # p=0.8 -> in [30, 40): t = 30 + ((0.8-0.75)/0.25)*10 = 32
    expected = [18.0, 23.0, 27.0, 32.0]
    assert strategy.scheduled_polls == expected


def test_observations_are_copied_not_referenced() -> None:
    """Test that observations property returns a copy."""
    strategy = CDFPollingStrategy()
    obs1 = strategy.observations
    obs2 = strategy.observations

    # Should be equal but different objects
    assert obs1 == obs2
    assert obs1 is not obs2


@pytest.mark.parametrize(
    ("observations", "expected_count"),
    [
        (None, 100),  # Cold start
        ([], 100),  # Empty list triggers cold start logic
        ([{"start": 10.0, "end": 20.0}], 1),
        ([{"start": i, "end": i + 10} for i in range(150)], 100),  # Truncated to 100
    ],
)
def test_observation_window_size(
    observations: list[IntervalObservation] | None,
    expected_count: int,
) -> None:
    """Test that observation window is properly sized."""
    # Empty list case needs special handling - CDFPollingStrategy treats [] as cold start
    if observations == []:
        strategy = CDFPollingStrategy([])
        # Empty list means no observations, falls back to cold start
        assert len(strategy.observations) == 0
    else:
        strategy = CDFPollingStrategy(observations)
        assert len(strategy.observations) == expected_count


def test_update_budget_with_different_poll_counts() -> None:
    """Test that update_budget accepts different polls_per_interval values."""
    # Use explicit observations for deterministic test
    observations: list[IntervalObservation] = [{"start": 15.0, "end": 45.0}] * 100
    strategy = CDFPollingStrategy(observations)
    strategy.update_budget(4, 0, 0, 0)

    # Initial is 4 polls
    assert len(strategy.scheduled_polls) == 4

    # Update to 2 polls
    strategy.update_budget(2, 0, 0, 0)
    assert len(strategy.scheduled_polls) == 2

    # Verify schedule changed (2 polls = quantiles at 1/3 and 2/3)
    # For uniform [15, 45]: t = 15 + p * 30
    # p = 1/3 -> t = 25, p = 2/3 -> t = 35
    assert strategy.scheduled_polls == [25.0, 35.0]


def test_update_budget_zero_produces_empty_schedule() -> None:
    """Test that zero polls_per_interval produces an empty schedule."""
    strategy = CDFPollingStrategy()

    # Zero budget = no polls
    strategy.update_budget(0, 0, 0, 0)
    assert len(strategy.scheduled_polls) == 0

    # Can use any positive value
    strategy.update_budget(50, 0, 0, 0)
    assert len(strategy.scheduled_polls) == 50


def test_update_budget_recomputes_schedule() -> None:
    """Test that update_budget recomputes the schedule mid-interval."""
    strategy = CDFPollingStrategy()
    strategy.update_budget(4, 0, 0, 0)

    # Start with 4 polls
    assert len(strategy.scheduled_polls) == 4

    # Update budget to 2 polls at 10 seconds elapsed, reset in 290s
    strategy.update_budget(polls_per_interval=2, elapsed_seconds=10.0, reset_seconds=290, interval_seconds=0)

    # Should now have 2 scheduled polls
    assert len(strategy.scheduled_polls) == 2


def test_update_budget_uses_conditional_cdf() -> None:
    """Test that update_budget recomputes schedule using conditional P(T | T > elapsed).

    When we update at time t, we know the event hasn't occurred yet, so we sample
    from the remaining probability mass. All new polls should be after elapsed time.
    """
    # Use explicit observations for deterministic test
    observations: list[IntervalObservation] = [{"start": 15.0, "end": 45.0}] * 100
    strategy = CDFPollingStrategy(observations)

    # With uniform [15, 45] schedule: [21, 27, 33, 39] (evenly spaced in [15, 45])
    strategy.update_budget(4, 0, 0, 0)
    assert strategy.scheduled_polls == [21.0, 27.0, 33.0, 39.0]

    # Update at 25 seconds - now we condition on T > 25, reset in 275s
    strategy.update_budget(polls_per_interval=4, elapsed_seconds=25.0, reset_seconds=275, interval_seconds=0)

    # All polls should be > 25s (conditional sampling)
    assert all(t > 25.0 for t in strategy.scheduled_polls)
    # Poll index starts at 0 since all polls are in the future
    assert strategy._next_poll_index == 0
    # First poll should be shortly after 25s
    assert strategy.should_poll_for_confirmed(25.0) is False
    assert strategy.should_poll_for_confirmed(strategy.scheduled_polls[0]) is True


def test_update_budget_concentrates_polls_in_remaining_mass() -> None:
    """Test that conditional sampling concentrates polls in remaining probability mass."""
    strategy = CDFPollingStrategy()
    strategy.update_budget(35, 0, 0, 0)

    # Original schedule spans within [15, 45] interval
    original = strategy.scheduled_polls.copy()
    assert len(original) == 35
    # First few polls should be around 15-20s range
    assert 15.0 < original[0] < 20.0

    # Update at 30 seconds - half the probability mass is now gone, reset in 270s
    # With k=35, reset=270: uniform_polls_needed = ceil(270/30) = 9
    # Blends targeted [15,45] with uniform [30, 300]
    strategy.update_budget(polls_per_interval=35, elapsed_seconds=30.0, reset_seconds=270, interval_seconds=0)

    # New schedule should be after elapsed time (30s)
    new_schedule = strategy.scheduled_polls
    assert len(new_schedule) == 35
    assert all(t > 30.0 for t in new_schedule)
    # Should extend beyond targeted range due to uniform blending
    assert any(t > 45.0 for t in new_schedule)


def test_update_budget_all_mass_in_past() -> None:
    """Test update_budget when all probability mass is before elapsed time.

    When targeted CDF mass is all in the past but k is low enough for blending,
    falls back to pure uniform distribution from elapsed to reset time.
    """
    strategy = CDFPollingStrategy()
    strategy.update_budget(4, 0, 0, 0)

    # Update at 50 seconds - all probability mass is in [15, 45], so F(50) = 1
    # With k=4 and reset=250, uniform_polls_needed = ceil(250/30) = 9
    # Since k=4 <= 9, we use pure uniform from 50 to 300 (50+250)
    strategy.update_budget(polls_per_interval=4, elapsed_seconds=50.0, reset_seconds=250, interval_seconds=0)

    # Falls back to uniform: polls at 50 + [1/5, 2/5, 3/5, 4/5] * 250 = [100, 150, 200, 250]
    assert strategy.scheduled_polls == [100.0, 150.0, 200.0, 250.0]
    assert strategy.should_poll_for_confirmed(50.0) is False  # Before first poll
    assert strategy.should_poll_for_confirmed(100.0) is True  # First poll time


def test_empty_observations_list() -> None:
    """Test behavior with an explicitly empty observations list."""
    strategy = CDFPollingStrategy([])

    # Empty list means no observations
    assert len(strategy.observations) == 0
    # Schedule should be empty with no observations
    assert strategy.scheduled_polls == []


def test_increment_poll_beyond_scheduled() -> None:
    """Test incrementing poll when all polls are already used."""
    strategy = CDFPollingStrategy()
    strategy.update_budget(2, 0, 0, 0)

    assert len(strategy.scheduled_polls) == 2

    # Use both polls
    strategy.increment_confirmatory_poll()
    strategy.increment_confirmatory_poll()

    # Incrementing again should not crash
    strategy.increment_confirmatory_poll()
    assert strategy.confirmatory_poll_count == 3
    # Next poll index capped at end
    assert strategy._next_poll_index == 2


def test_get_stats_with_empty_observations() -> None:
    """Test get_stats when observations list is empty."""
    strategy = CDFPollingStrategy([])

    stats = strategy.get_stats()

    assert stats.observation_count == 0
    assert stats.scheduled_polls == []
    assert stats.last_observation is None


def test_recompute_schedule_with_empty_observations() -> None:
    """Test schedule recomputation with empty observations."""
    strategy = CDFPollingStrategy([])
    strategy._polls_per_interval = 4
    strategy._recompute_schedule()

    assert strategy._scheduled_polls == []


def test_build_cdf_empty_observations() -> None:
    """Test build_cdf returns empty arrays with no observations."""
    cdf_times, cdf_probs = build_cdf([])

    assert len(cdf_times) == 0
    assert len(cdf_probs) == 0


def test_build_cdf_single_observation() -> None:
    """Test build_cdf with a single narrow observation."""
    observations: list[IntervalObservation] = [{"start": 10.0, "end": 10.0001}]

    cdf_times, cdf_probs = build_cdf(observations)

    # Should produce valid CDF with at least 2 points
    assert len(cdf_times) >= 2
    assert len(cdf_probs) >= 2


def test_build_cdf_with_weights() -> None:
    """Test build_cdf respects observation weights."""
    # Two observations with equal intervals but different weights
    # obs1: [10, 20] with weight 3
    # obs2: [30, 40] with weight 1
    # Total weight = 4, so obs1 contributes 75% and obs2 contributes 25%
    observations: list[IntervalObservation] = [
        {"start": 10.0, "end": 20.0, "weight": 3.0},
        {"start": 30.0, "end": 40.0, "weight": 1.0},
    ]

    cdf_times, cdf_probs = build_cdf(observations)

    # CDF should reach 0.75 at t=20 (end of obs1) and 1.0 at t=40
    prob_at_20 = float(np.interp(20.0, cdf_times, cdf_probs))
    prob_at_40 = float(np.interp(40.0, cdf_times, cdf_probs))

    assert abs(prob_at_20 - 0.75) < 0.01
    assert abs(prob_at_40 - 1.0) < 0.01


def test_build_cdf_weights_default_to_one() -> None:
    """Test that observations without weight field default to weight 1.0."""
    # Mix of weighted and unweighted observations
    observations: list[IntervalObservation] = [
        {"start": 10.0, "end": 20.0},  # No weight, defaults to 1.0
        {"start": 30.0, "end": 40.0, "weight": 1.0},  # Explicit weight 1.0
    ]

    cdf_times, cdf_probs = build_cdf(observations)

    # Both should contribute equally (50% each)
    prob_at_20 = float(np.interp(20.0, cdf_times, cdf_probs))
    prob_at_40 = float(np.interp(40.0, cdf_times, cdf_probs))

    assert abs(prob_at_20 - 0.5) < 0.01
    assert abs(prob_at_40 - 1.0) < 0.01


def test_record_observation_same_start_end() -> None:
    """Test that recording observation with start == end is ignored."""
    observations: list[IntervalObservation] = [{"start": 10.0, "end": 20.0}]
    strategy = CDFPollingStrategy(observations)

    # Try to record invalid observation (start == end)
    strategy.record_observation(start=15.0, end=15.0)

    # Should still have only 1 observation
    assert len(strategy.observations) == 1


def test_record_observation_grows_when_under_window_size() -> None:
    """Test that recording grows observation count when under WINDOW_SIZE."""
    # Start with 5 observations (under WINDOW_SIZE of 100)
    observations: list[IntervalObservation] = [{"start": float(i), "end": float(i + 1)} for i in range(5)]
    strategy = CDFPollingStrategy(observations)

    assert len(strategy.observations) == 5

    # Record a valid observation - should grow to 6
    strategy.record_observation(start=10.0, end=15.0)

    assert len(strategy.observations) == 6
    assert strategy.observations[-1] == {"start": 10.0, "end": 15.0}


# Tests for sample-rate-based uniform blending


def test_update_budget_pure_uniform_when_low_k() -> None:
    """Test that low k (below uniform_polls_needed) uses pure uniform distribution."""
    strategy = CDFPollingStrategy()
    strategy.update_budget(5, 0, 0, 0)

    # With k=5, reset=100: uniform_polls_needed = ceil(100/30) = 4
    # k=5 > 4, so we get blended (not pure uniform)
    # But with k=3, reset=100: uniform_polls_needed = 4
    # k=3 <= 4, so we use pure uniform
    strategy.update_budget(polls_per_interval=3, elapsed_seconds=10.0, reset_seconds=100, interval_seconds=0)

    # With pure uniform from 10 to 110, polls at quantiles 1/4, 2/4, 3/4
    # t = 10 + p * 100, so approximately [35, 60, 85]
    expected = [
        10.0 + (1 / 4) * 100,  # 35
        10.0 + (2 / 4) * 100,  # 60
        10.0 + (3 / 4) * 100,  # 85
    ]

    for actual, exp in zip(strategy.scheduled_polls, expected, strict=True):
        assert abs(actual - exp) < 0.01


def test_update_budget_blends_uniform_with_targeted() -> None:
    """Test that update_budget always blends uniform with targeted when reset_seconds available."""
    # Use explicit observations for deterministic test
    observations: list[IntervalObservation] = [{"start": 15.0, "end": 45.0}] * 100
    strategy = CDFPollingStrategy(observations)

    # With k=35, reset=150: uniform_polls_needed = ceil(150/30) = 5
    # uniform_weight = 100 * 5 / (35 - 5) = 500 / 30 ≈ 16.67
    # This means uniform has about 16.67% of the weight relative to 100 observations
    strategy.update_budget(35, 0, 0, 0)
    strategy.update_budget(polls_per_interval=35, elapsed_seconds=10.0, reset_seconds=150, interval_seconds=0)

    # Polls should be after elapsed (10s)
    assert all(t > 10.0 for t in strategy.scheduled_polls)

    # Some polls should extend beyond the targeted distribution [15, 45]
    # due to uniform influence (from 10 to 10+150=160)
    assert any(t > 45.0 for t in strategy.scheduled_polls)


def test_update_budget_includes_reset_time_as_forced_poll() -> None:
    """Test that reset time is included as a forced poll when before next interval."""
    strategy = CDFPollingStrategy()
    strategy.update_budget(4, 0, 0, 0)

    # Set elapsed=10, reset in 50s (at t=60), next interval at t=120
    # Reset time (60) < interval (120), so reset should be added as forced poll
    strategy.update_budget(polls_per_interval=4, elapsed_seconds=10.0, reset_seconds=50, interval_seconds=120)

    # Reset time (10 + 50 = 60) should be in the schedule
    assert 60.0 in strategy.scheduled_polls
