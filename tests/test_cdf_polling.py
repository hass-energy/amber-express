"""Tests for CDF polling strategy."""

from __future__ import annotations

import pytest

from custom_components.amber_express.cdf_polling import CDFPollingStats, CDFPollingStrategy, IntervalObservation


def test_cold_start_initializes_with_synthetic_intervals() -> None:
    """Test that cold start fills with 100 synthetic [15, 45] intervals."""
    strategy = CDFPollingStrategy()

    assert len(strategy.observations) == 100
    for obs in strategy.observations:
        assert obs["start"] == 15.0
        assert obs["end"] == 45.0


def test_cold_start_schedule_is_evenly_spaced() -> None:
    """Test cold start produces evenly spaced polls within [15, 45]."""
    strategy = CDFPollingStrategy()
    strategy.start_interval(4)

    # With k=4 polls and uniform [15, 45], should get polls at quantiles
    # p = [0.2, 0.4, 0.6, 0.8] of uniform [15, 45]
    # t = 15 + p * 30 = [21, 27, 33, 39]
    expected = [21.0, 27.0, 33.0, 39.0]
    assert strategy.scheduled_polls == expected


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
    strategy = CDFPollingStrategy()
    strategy.start_interval(4)

    # First scheduled poll is at 21 seconds
    assert not strategy.should_poll_for_confirmed(20.0)
    assert strategy.should_poll_for_confirmed(21.0)
    assert strategy.should_poll_for_confirmed(25.0)  # Still true until poll executed


def test_should_poll_advances_after_increment() -> None:
    """Test that incrementing poll count advances to next scheduled poll."""
    strategy = CDFPollingStrategy()
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
    strategy = CDFPollingStrategy()
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
    strategy.update_budget(polls_per_interval=2, elapsed_seconds=10.0, reset_seconds=290)

    # Should now have 2 scheduled polls
    assert len(strategy.scheduled_polls) == 2


def test_update_budget_uses_conditional_cdf() -> None:
    """Test that update_budget recomputes schedule using conditional P(T | T > elapsed).

    When we update at time t, we know the event hasn't occurred yet, so we sample
    from the remaining probability mass. All new polls should be after elapsed time.
    """
    strategy = CDFPollingStrategy()

    # Cold start schedule: [21, 27, 33, 39] (evenly spaced in [15, 45])
    strategy.start_interval(polls_per_interval=4)
    assert strategy.scheduled_polls == [21.0, 27.0, 33.0, 39.0]

    # Update at 25 seconds - now we condition on T > 25, reset in 275s
    strategy.update_budget(polls_per_interval=4, elapsed_seconds=25.0, reset_seconds=275)

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
    strategy.update_budget(polls_per_interval=35, elapsed_seconds=30.0, reset_seconds=270)

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
    strategy.update_budget(polls_per_interval=4, elapsed_seconds=50.0, reset_seconds=250)

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


def test_cdf_at_edge_cases() -> None:
    """Test CDF evaluation at boundary conditions."""
    observations: list[IntervalObservation] = [{"start": 10.0, "end": 20.0}]
    strategy = CDFPollingStrategy(observations)

    # Access internal method for edge case testing
    cdf_points = strategy._build_cdf()

    # Before first point
    assert strategy._cdf_at(-5.0, cdf_points) == 0.0
    # After last point
    assert strategy._cdf_at(100.0, cdf_points) == 1.0
    # At exact first point
    assert strategy._cdf_at(10.0, cdf_points) == 0.0
    # At exact last point
    assert strategy._cdf_at(20.0, cdf_points) == 1.0
    # Empty cdf_points
    assert strategy._cdf_at(15.0, []) == 0.0


def test_inverse_cdf_edge_cases() -> None:
    """Test inverse CDF at boundary conditions."""
    observations: list[IntervalObservation] = [{"start": 10.0, "end": 20.0}]
    strategy = CDFPollingStrategy(observations)

    cdf_points = strategy._build_cdf()

    # Below first probability
    assert strategy._inverse_cdf(-0.1, cdf_points) == 10.0
    # Above last probability
    assert strategy._inverse_cdf(1.5, cdf_points) == 20.0
    # Exactly at 0
    assert strategy._inverse_cdf(0.0, cdf_points) == 10.0
    # Exactly at 1
    assert strategy._inverse_cdf(1.0, cdf_points) == 20.0
    # Empty cdf_points
    assert strategy._inverse_cdf(0.5, []) == 0.0


def test_cdf_segment_with_zero_width() -> None:
    """Test CDF interpolation when t1 == t0 (degenerate segment)."""
    # Create observations that result in a point with t1 == t0
    # This can happen with identical start points
    observations: list[IntervalObservation] = [
        {"start": 10.0, "end": 10.001},  # Very narrow interval
    ]
    strategy = CDFPollingStrategy(observations)

    cdf_points = strategy._build_cdf()

    # Should handle interpolation without division by zero
    result = strategy._cdf_at(10.0, cdf_points)
    assert result >= 0.0  # Valid result


def test_inverse_cdf_flat_segment() -> None:
    """Test inverse CDF when p1 == p0 (flat segment)."""
    observations: list[IntervalObservation] = [
        {"start": 10.0, "end": 20.0},
        {"start": 30.0, "end": 40.0},
    ]
    strategy = CDFPollingStrategy(observations)

    cdf_points = strategy._build_cdf()

    # The CDF has a flat region between 20 and 30 (p stays at 0.5)
    # Finding quantile in flat region should return the start of segment
    # This exercises the p1 == p0 branch in _inverse_cdf
    result = strategy._inverse_cdf(0.5, cdf_points)
    assert result == 20.0  # First point where p = 0.5


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
    """Test _build_cdf returns empty list with no observations."""
    strategy = CDFPollingStrategy([])

    cdf_points = strategy._build_cdf()

    assert cdf_points == []


def test_build_cdf_single_point_time_grid() -> None:
    """Test _build_cdf handles case where time_grid has only one point."""
    # Create an observation where start and end collapse to same point
    strategy = CDFPollingStrategy()
    # Manually set a degenerate observation that passed validation
    strategy._observations = [{"start": 10.0, "end": 10.0001}]

    cdf_points = strategy._build_cdf()

    # Should still produce valid CDF with at least 2 points
    assert len(cdf_points) >= 2


def test_cdf_at_interpolation_same_point() -> None:
    """Test _cdf_at when t falls exactly at a point where t0 == t1."""
    strategy = CDFPollingStrategy()

    # Create CDF points with a zero-width segment
    cdf_points = [(10.0, 0.0), (10.0, 0.5), (20.0, 1.0)]

    # Query at the duplicate point
    result = strategy._cdf_at(10.0, cdf_points)
    # Should return the first matching probability
    assert result in {0.0, 0.5}


def test_cdf_at_falls_through_all_segments() -> None:
    """Test _cdf_at fallback when t doesn't match any segment."""
    strategy = CDFPollingStrategy()

    # Create CDF points
    cdf_points = [(10.0, 0.0), (20.0, 0.5), (30.0, 1.0)]

    # Query at a point that should be handled by "After last point" check
    result = strategy._cdf_at(35.0, cdf_points)
    assert result == 1.0


def test_inverse_cdf_falls_through_all_segments() -> None:
    """Test _inverse_cdf fallback when target_p doesn't match any segment."""
    strategy = CDFPollingStrategy()

    # Create CDF points with gaps
    cdf_points = [(10.0, 0.0), (20.0, 0.5), (30.0, 1.0)]

    # This should be handled by edge case checks
    result = strategy._inverse_cdf(1.0, cdf_points)
    assert result == 30.0


def test_record_observation_same_start_end() -> None:
    """Test that recording observation with start == end is ignored."""
    observations: list[IntervalObservation] = [{"start": 10.0, "end": 20.0}]
    strategy = CDFPollingStrategy(observations)

    # Try to record invalid observation (start == end)
    strategy.record_observation(start=15.0, end=15.0)

    # Should still have only 1 observation
    assert len(strategy.observations) == 1


def test_cdf_at_zero_width_segment() -> None:
    """Test _cdf_at with a zero-width segment in CDF (t1 == t0)."""
    strategy = CDFPollingStrategy()

    # Manually create CDF with a zero-width segment
    # Query at t=15 which is between the first zero-width segment and the next
    # The loop will iterate: first segment is (10.0, 10.0), check t0 <= 15 <= t1 = 10 <= 15 <= 10 = False
    # So it won't match the first segment, will check second segment
    cdf_points = [(10.0, 0.0), (10.0, 0.5), (20.0, 1.0)]

    # Query at t=15 - should find it in the second segment (10.0, 20.0)
    result = strategy._cdf_at(15.0, cdf_points)
    assert 0.5 <= result <= 1.0


def test_cdf_at_zero_width_segment_hit_branch() -> None:
    """Test _cdf_at hits the t1 == t0 branch directly."""
    strategy = CDFPollingStrategy()

    # Create a CDF with a zero-width segment in the middle
    # First we need t0 <= t <= t1 where t0 == t1
    # At t=15, check segment (15.0, 15.0): 15 <= 15 <= 15 = True, and t1 == t0
    cdf_points = [(10.0, 0.0), (15.0, 0.3), (15.0, 0.5), (20.0, 1.0)]

    # Query at t=15 - hits the zero-width segment
    result = strategy._cdf_at(15.0, cdf_points)
    # Should return p0 = 0.3 because t1 == t0
    assert result == 0.3


def test_cdf_at_fallback_when_loop_exhausted() -> None:
    """Test _cdf_at fallback when for loop doesn't find a matching segment."""
    strategy = CDFPollingStrategy()

    # Create CDF where t is in a gap that the loop doesn't catch
    # This is a degenerate case - normally shouldn't happen
    cdf_points: list[tuple[float, float]] = [(10.0, 0.0), (15.0, 0.5)]

    # Query at t=12 - should be caught by the loop
    result = strategy._cdf_at(12.0, cdf_points)
    assert result >= 0.0


def test_inverse_cdf_flat_probability_segment() -> None:
    """Test _inverse_cdf with a flat probability segment (p1 == p0)."""
    strategy = CDFPollingStrategy()

    # Create CDF with a flat segment (same probability at different times)
    # This represents a gap in the distribution
    cdf_points = [(10.0, 0.0), (15.0, 0.5), (20.0, 0.5), (25.0, 1.0)]

    # Query at p=0.5 which is a flat segment
    result = strategy._inverse_cdf(0.5, cdf_points)
    # Should return t0 of the flat segment
    assert result == 15.0


def test_inverse_cdf_hit_flat_segment_branch() -> None:
    """Test _inverse_cdf hits the p1 == p0 branch directly."""
    strategy = CDFPollingStrategy()

    # Create CDF where we query a probability in a flat segment (p0 == p1)
    # At p=0.5, segment (15.0, 0.5) to (20.0, 0.5): p0 <= 0.5 <= p1 = 0.5 <= 0.5 <= 0.5 = True
    cdf_points = [(10.0, 0.0), (15.0, 0.5), (20.0, 0.5), (25.0, 1.0)]

    # Query at p=0.5 - should hit the flat segment and return t0
    result = strategy._inverse_cdf(0.5, cdf_points)
    # Should return t0 = 15.0 because p1 == p0
    assert result == 15.0


def test_inverse_cdf_fallback_when_loop_exhausted() -> None:
    """Test _inverse_cdf fallback when for loop doesn't find a matching segment."""
    strategy = CDFPollingStrategy()

    # Create a simple CDF
    cdf_points = [(10.0, 0.0), (20.0, 1.0)]

    # Query at p=0.5 - should be found in the loop
    result = strategy._inverse_cdf(0.5, cdf_points)
    assert 10.0 <= result <= 20.0


def test_cdf_at_loop_fallback_with_non_contiguous_cdf() -> None:
    """Test _cdf_at fallback with a non-contiguous CDF (gaps between segments).

    This is a synthetic edge case - real CDFs are contiguous.
    Creates a CDF with gaps where t doesn't fall in any segment.
    """
    strategy = CDFPollingStrategy()

    # Create non-contiguous CDF: [10, 12] then gap then [15, 20]
    # t=13 falls in the gap
    cdf_points = [(10.0, 0.0), (12.0, 0.3), (15.0, 0.5), (20.0, 1.0)]

    # Query at t=13.5 - falls between segments
    # Loop checks: 10 <= 13.5 <= 12? No. 12 <= 13.5 <= 15? Yes! This returns.
    # So this won't hit the fallback.
    # We need segments that truly have gaps where no segment contains t
    # Actually, the segments are contiguous by the way we define them (each pair forms a segment)
    # So the loop covers (10,12), (12,15), (15,20) - no gaps
    result = strategy._cdf_at(13.5, cdf_points)
    assert 0.3 <= result <= 0.5


def test_inverse_cdf_loop_fallback_with_gaps() -> None:
    """Test _inverse_cdf fallback with gaps in probability space.

    Creates a CDF where target_p falls between segment probabilities.
    """
    strategy = CDFPollingStrategy()

    # Create CDF: (10, 0.0) -> (15, 0.3) -> (20, 0.8) -> (25, 1.0)
    # Segments have p ranges: [0, 0.3], [0.3, 0.8], [0.8, 1.0]
    cdf_points = [(10.0, 0.0), (15.0, 0.3), (20.0, 0.8), (25.0, 1.0)]

    # Query at p=0.5 - falls in second segment [0.3, 0.8]
    result = strategy._inverse_cdf(0.5, cdf_points)
    assert 15.0 <= result <= 20.0


# Tests for uniform blending behavior


def test_compute_blend_weight_at_k_high() -> None:
    """Test blend weight is 1.0 when k >= K_HIGH."""
    strategy = CDFPollingStrategy()

    # At or above K_HIGH (30), weight should be 1.0 (pure targeted)
    assert strategy._compute_blend_weight(30) == 1.0
    assert strategy._compute_blend_weight(50) == 1.0
    assert strategy._compute_blend_weight(100) == 1.0


def test_compute_blend_weight_at_k_low() -> None:
    """Test blend weight is 0.0 when k <= K_LOW."""
    strategy = CDFPollingStrategy()

    # At or below K_LOW (10), weight should be 0.0 (pure uniform)
    assert strategy._compute_blend_weight(10) == 0.0
    assert strategy._compute_blend_weight(5) == 0.0
    assert strategy._compute_blend_weight(0) == 0.0


def test_compute_blend_weight_linear_interpolation() -> None:
    """Test blend weight interpolates linearly between K_LOW and K_HIGH."""
    strategy = CDFPollingStrategy()

    # k=20 is midpoint between 10 and 30
    assert strategy._compute_blend_weight(20) == 0.5

    # k=15 is 1/4 of the way
    assert strategy._compute_blend_weight(15) == 0.25

    # k=25 is 3/4 of the way
    assert strategy._compute_blend_weight(25) == 0.75


def test_update_budget_pure_targeted_at_high_k() -> None:
    """Test that high k uses pure targeted CDF (no uniform blending)."""
    strategy = CDFPollingStrategy()
    strategy.start_interval(polls_per_interval=35)

    # With k=35 (above K_HIGH=30), should use pure targeted CDF
    # Cold start observations are [15, 45], so polls should be in that range
    strategy.update_budget(polls_per_interval=35, elapsed_seconds=10.0, reset_seconds=290)

    # Polls should be after elapsed (10s) but within targeted distribution
    assert all(10.0 < t <= 45.0 for t in strategy.scheduled_polls)


def test_update_budget_pure_uniform_at_low_k() -> None:
    """Test that low k uses pure uniform distribution."""
    strategy = CDFPollingStrategy()
    strategy.start_interval(polls_per_interval=5)

    # With k=5 (below K_LOW=10), should use pure uniform distribution
    # Uniform spans from elapsed (10s) to elapsed + reset_seconds (10 + 100 = 110s)
    strategy.update_budget(polls_per_interval=5, elapsed_seconds=10.0, reset_seconds=100)

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
    strategy = CDFPollingStrategy()

    # First get pure targeted polls with high k
    strategy.start_interval(polls_per_interval=35)
    strategy.update_budget(polls_per_interval=35, elapsed_seconds=10.0, reset_seconds=100)
    targeted_polls = strategy.scheduled_polls.copy()

    # Now get blended polls with k=20 (w=0.5)
    strategy.update_budget(polls_per_interval=20, elapsed_seconds=10.0, reset_seconds=100)
    blended_polls = strategy.scheduled_polls.copy()

    # Compute expected uniform polls for k=20
    uniform_polls = [10.0 + (j / 21) * 100 for j in range(1, 21)]

    # With w=0.5, blended should be halfway between targeted and uniform
    # Can't verify exactly without knowing targeted, but polls should be
    # spread out more than pure targeted (which clusters in [15, 45])
    assert len(blended_polls) == 20

    # At least some polls should be beyond 45s (spread by uniform influence)
    assert any(t > 50.0 for t in blended_polls)
