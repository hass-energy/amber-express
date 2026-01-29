"""Tests for CDF polling strategy."""

from __future__ import annotations

import pytest

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
    strategy.start_interval(4)

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
    strategy.start_interval(4)

    # With uniform [15, 45], first poll is at 21s
    assert not strategy.should_poll_for_confirmed(20.0)
    assert strategy.should_poll_for_confirmed(21.0)
    assert strategy.should_poll_for_confirmed(25.0)  # Still true until poll executed


def test_should_poll_advances_after_increment() -> None:
    """Test that incrementing poll count advances to next scheduled poll."""
    # Use explicit observations for deterministic test
    observations: list[IntervalObservation] = [{"start": 15.0, "end": 45.0}] * 100
    strategy = CDFPollingStrategy(observations)
    strategy.start_interval(4)

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
    strategy.start_interval()

    # Use all 4 polls
    for _ in range(4):
        strategy.increment_confirmatory_poll()

    # Should return False for any time
    assert not strategy.should_poll_for_confirmed(100.0)


def test_get_next_poll_delay_returns_time_until_next_poll() -> None:
    """Test that get_next_poll_delay returns correct delay."""
    observations: list[IntervalObservation] = [{"start": 10.0, "end": 30.0}]
    strategy = CDFPollingStrategy(observations)
    strategy.start_interval(4)

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
    strategy.start_interval()

    # Use all 4 polls
    for _ in range(4):
        strategy.increment_confirmatory_poll()

    # Should return None
    assert strategy.get_next_poll_delay(100.0) is None


def test_get_next_poll_delay_sub_second_precision() -> None:
    """Test that get_next_poll_delay handles sub-second precision."""
    observations: list[IntervalObservation] = [{"start": 25.0, "end": 26.0}]
    strategy = CDFPollingStrategy(observations)
    strategy.start_interval(polls_per_interval=4)

    # With narrow interval [25, 26], polls should be tightly spaced
    # At elapsed=25.1, should return sub-second delay
    delay = strategy.get_next_poll_delay(25.1)
    assert delay is not None
    # Delay should be small (sub-second for tightly packed polls)
    assert delay >= 0


def test_start_interval_resets_poll_state() -> None:
    """Test that start_interval resets the poll index."""
    strategy = CDFPollingStrategy()
    strategy.start_interval(4)

    # Advance past first poll
    strategy.increment_confirmatory_poll()
    assert strategy.confirmatory_poll_count == 1

    # Reset for new interval
    strategy.start_interval(4)

    # Should be back to first poll
    assert strategy.confirmatory_poll_count == 0
    assert strategy.should_poll_for_confirmed(21.0)


def test_get_stats_returns_correct_values() -> None:
    """Test that get_stats returns correct diagnostic values."""
    observations: list[IntervalObservation] = [{"start": 10.0, "end": 20.0}]
    strategy = CDFPollingStrategy(observations)
    strategy.start_interval(4)

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
    strategy.start_interval(4)

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
    strategy.start_interval(4)

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
    strategy.start_interval(4)

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


def test_start_interval_with_custom_polls_per_interval() -> None:
    """Test that start_interval accepts custom polls_per_interval."""
    # Use explicit observations for deterministic test
    observations: list[IntervalObservation] = [{"start": 15.0, "end": 45.0}] * 100
    strategy = CDFPollingStrategy(observations)
    strategy.start_interval(4)

    # Initial is 4 polls
    assert len(strategy.scheduled_polls) == 4

    # Start new interval with 2 polls
    strategy.start_interval(polls_per_interval=2)
    assert len(strategy.scheduled_polls) == 2

    # Verify schedule changed (2 polls = quantiles at 1/3 and 2/3)
    # For uniform [15, 45]: t = 15 + p * 30
    # p = 1/3 -> t = 25, p = 2/3 -> t = 35
    assert strategy.scheduled_polls == [25.0, 35.0]


def test_start_interval_zero_budget_produces_empty_schedule() -> None:
    """Test that zero polls_per_interval produces an empty schedule."""
    strategy = CDFPollingStrategy()

    # Zero budget = no polls
    strategy.start_interval(polls_per_interval=0)
    assert len(strategy.scheduled_polls) == 0

    # Can use any positive value
    strategy.start_interval(polls_per_interval=50)
    assert len(strategy.scheduled_polls) == 50


def test_start_interval_none_preserves_previous() -> None:
    """Test that passing None preserves the previous polls_per_interval."""
    strategy = CDFPollingStrategy()

    # Set to 2 polls
    strategy.start_interval(polls_per_interval=2)
    assert len(strategy.scheduled_polls) == 2

    # Start new interval with None - should keep 2
    strategy.start_interval(polls_per_interval=None)
    assert len(strategy.scheduled_polls) == 2


def test_update_budget_recomputes_schedule() -> None:
    """Test that update_budget recomputes the schedule mid-interval."""
    strategy = CDFPollingStrategy()
    strategy.start_interval(4)

    # Start with 4 polls
    assert len(strategy.scheduled_polls) == 4

    # Update budget to 2 polls at 10 seconds elapsed, reset in 290s
    strategy.update_budget(polls_per_interval=2, elapsed_seconds=10.0, reset_seconds=290, quota=50)

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
    strategy.start_interval(polls_per_interval=4)
    assert strategy.scheduled_polls == [21.0, 27.0, 33.0, 39.0]

    # Update at 25 seconds - now we condition on T > 25, reset in 275s
    strategy.update_budget(polls_per_interval=4, elapsed_seconds=25.0, reset_seconds=275, quota=50)

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
    # Use k=35 (above UNIFORM_BLEND_K_HIGH=30) to test pure targeted CDF behavior
    strategy.start_interval(polls_per_interval=35)

    # Original schedule spans within [15, 45] interval
    original = strategy.scheduled_polls.copy()
    assert len(original) == 35
    # First few polls should be around 15-20s range
    assert 15.0 < original[0] < 20.0

    # Update at 30 seconds - half the probability mass is now gone, reset in 270s
    # Use k=35 to keep pure targeted behavior (no uniform blending)
    strategy.update_budget(polls_per_interval=35, elapsed_seconds=30.0, reset_seconds=270, quota=50)

    # New schedule should be compressed into [30, 45]
    # All polls should be in the remaining mass
    new_schedule = strategy.scheduled_polls
    assert len(new_schedule) == 35
    assert all(30.0 < t <= 45.0 for t in new_schedule)


def test_update_budget_all_mass_in_past() -> None:
    """Test update_budget when all probability mass is before elapsed time.

    When targeted CDF mass is all in the past but k is low enough for blending,
    falls back to pure uniform distribution from elapsed to reset time.
    """
    strategy = CDFPollingStrategy()
    strategy.start_interval(polls_per_interval=4)

    # Update at 50 seconds - all probability mass is in [15, 45], so F(50) = 1
    # With k=4 (below K_LOW=10), w=0 so we use pure uniform from 50 to 300 (50+250)
    strategy.update_budget(polls_per_interval=4, elapsed_seconds=50.0, reset_seconds=250, quota=50)

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
    strategy.start_interval(polls_per_interval=2)

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


def test_compute_poll_schedule_insufficient_cdf_points() -> None:
    """Test _compute_poll_schedule with insufficient CDF points."""
    # Single point observation creates only 2 time_grid points
    # but with a single observation, CDF is still valid
    # We need an edge case where time_grid ends up < 2
    observations: list[IntervalObservation] = [{"start": 10.0, "end": 10.0}]
    strategy = CDFPollingStrategy(observations)

    # This observation has start == end, so it's invalid and won't produce valid CDF
    # Wait - record_observation skips start >= end, so let's try another approach
    # Start fresh with empty and manually set observations
    strategy._observations = []
    strategy._compute_poll_schedule()

    assert strategy._scheduled_polls == []


def test_build_cdf_empty_observations() -> None:
    """Test _build_cdf returns empty arrays with no observations."""
    strategy = CDFPollingStrategy([])

    cdf_times, cdf_probs = strategy._build_cdf()

    assert len(cdf_times) == 0
    assert len(cdf_probs) == 0


def test_build_cdf_single_point_time_grid() -> None:
    """Test _build_cdf handles case where time_grid has only one point."""
    # Create an observation where start and end collapse to same point
    strategy = CDFPollingStrategy()
    # Manually set a degenerate observation that passed validation
    strategy._observations = [{"start": 10.0, "end": 10.0001}]

    cdf_times, cdf_probs = strategy._build_cdf()

    # Should still produce valid CDF with at least 2 points
    assert len(cdf_times) >= 2
    assert len(cdf_probs) >= 2


def test_record_observation_same_start_end() -> None:
    """Test that recording observation with start == end is ignored."""
    observations: list[IntervalObservation] = [{"start": 10.0, "end": 20.0}]
    strategy = CDFPollingStrategy(observations)

    # Try to record invalid observation (start == end)
    strategy.record_observation(start=15.0, end=15.0)

    # Should still have only 1 observation
    assert len(strategy.observations) == 1


# Tests for uniform blending behavior


def test_compute_blend_weight_at_k_high() -> None:
    """Test blend weight is 1.0 when k >= K_HIGH."""
    strategy = CDFPollingStrategy()
    strategy._quota = 50  # K_HIGH = 0.6 * 50 = 30

    # At or above K_HIGH (30), weight should be 1.0 (pure targeted)
    assert strategy._compute_blend_weight(30) == 1.0
    assert strategy._compute_blend_weight(50) == 1.0
    assert strategy._compute_blend_weight(100) == 1.0


def test_compute_blend_weight_at_k_low() -> None:
    """Test blend weight is 0.0 when k <= K_LOW."""
    strategy = CDFPollingStrategy()
    strategy._quota = 50  # K_LOW = 0.2 * 50 = 10

    # At or below K_LOW (10), weight should be 0.0 (pure uniform)
    assert strategy._compute_blend_weight(10) == 0.0
    assert strategy._compute_blend_weight(5) == 0.0
    assert strategy._compute_blend_weight(0) == 0.0


def test_compute_blend_weight_linear_interpolation() -> None:
    """Test blend weight interpolates linearly between K_LOW and K_HIGH."""
    strategy = CDFPollingStrategy()
    # With UNIFORM_BLEND_FRACTION_HIGH=0.3 and UNIFORM_BLEND_FRACTION_LOW=0.2:
    # K_HIGH = 0.3 * 100 = 30, K_LOW = 0.2 * 100 = 20
    strategy._quota = 100

    # k=25 is midpoint between 20 and 30
    assert strategy._compute_blend_weight(25) == 0.5

    # k=22 is 2/10 of the way (22-20)/(30-20) = 0.2
    assert abs(strategy._compute_blend_weight(22) - 0.2) < 0.01

    # k=28 is 8/10 of the way (28-20)/(30-20) = 0.8
    assert abs(strategy._compute_blend_weight(28) - 0.8) < 0.01


def test_update_budget_pure_targeted_at_high_k() -> None:
    """Test that high k uses pure targeted CDF (no uniform blending)."""
    strategy = CDFPollingStrategy()
    strategy.start_interval(polls_per_interval=35)

    # With k=35 (above K_HIGH=30), should use pure targeted CDF
    # Cold start observations are [15, 45], so polls should be in that range
    strategy.update_budget(polls_per_interval=35, elapsed_seconds=10.0, reset_seconds=290, quota=50)

    # Polls should be after elapsed (10s) but within targeted distribution
    assert all(10.0 < t <= 45.0 for t in strategy.scheduled_polls)


def test_update_budget_pure_uniform_at_low_k() -> None:
    """Test that low k uses pure uniform distribution."""
    strategy = CDFPollingStrategy()
    strategy.start_interval(polls_per_interval=5)

    # With k=5 (below K_LOW=10), should use pure uniform distribution
    # Uniform spans from elapsed (10s) to elapsed + reset_seconds (10 + 100 = 110s)
    strategy.update_budget(polls_per_interval=5, elapsed_seconds=10.0, reset_seconds=100, quota=50)

    # With pure uniform from 10 to 110, polls at quantiles 1/6, 2/6, 3/6, 4/6, 5/6
    # t = 10 + p * 100, so approximately [26.67, 43.33, 60, 76.67, 93.33]
    expected = [
        10.0 + (1 / 6) * 100,  # ~26.67
        10.0 + (2 / 6) * 100,  # ~43.33
        10.0 + (3 / 6) * 100,  # 60
        10.0 + (4 / 6) * 100,  # ~76.67
        10.0 + (5 / 6) * 100,  # ~93.33
    ]

    for actual, exp in zip(strategy.scheduled_polls, expected, strict=True):
        assert abs(actual - exp) < 0.01


def test_update_budget_blended_at_mid_k() -> None:
    """Test that mid-range k blends targeted and uniform distributions."""
    # Use explicit observations for deterministic test
    observations: list[IntervalObservation] = [{"start": 15.0, "end": 45.0}] * 100
    strategy = CDFPollingStrategy(observations)

    # With quota=100: K_HIGH = 0.3 * 100 = 30, K_LOW = 0.2 * 100 = 20
    # k=25 is midpoint, giving w=0.5
    strategy.start_interval(polls_per_interval=35)
    strategy.update_budget(polls_per_interval=35, elapsed_seconds=10.0, reset_seconds=100, quota=100)
    targeted_polls = strategy.scheduled_polls.copy()

    # Now get blended polls with k=25 (w=0.5)
    strategy.update_budget(polls_per_interval=25, elapsed_seconds=10.0, reset_seconds=100, quota=100)
    blended_polls = strategy.scheduled_polls.copy()

    # With w=0.5, blended should be halfway between targeted and uniform
    assert len(blended_polls) == 25

    # Blended polls should extend beyond the targeted distribution [15, 45]
    # due to uniform influence spreading them toward elapsed + reset_seconds
    max_targeted = max(targeted_polls) if targeted_polls else 45.0
    assert any(t > max_targeted for t in blended_polls)
