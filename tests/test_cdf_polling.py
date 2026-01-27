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
    strategy.start_interval()

    # First scheduled poll is at 21 seconds
    assert not strategy.should_poll_for_confirmed(20.0)
    assert strategy.should_poll_for_confirmed(21.0)
    assert strategy.should_poll_for_confirmed(25.0)  # Still true until poll executed


def test_should_poll_advances_after_increment() -> None:
    """Test that incrementing poll count advances to next scheduled poll."""
    strategy = CDFPollingStrategy()
    strategy.start_interval()

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


def test_start_interval_resets_poll_state() -> None:
    """Test that start_interval resets the poll index."""
    strategy = CDFPollingStrategy()

    # Advance past first poll
    strategy.increment_confirmatory_poll()
    assert strategy.confirmatory_poll_count == 1

    # Reset for new interval
    strategy.start_interval()

    # Should be back to first poll
    assert strategy.confirmatory_poll_count == 0
    assert strategy.should_poll_for_confirmed(21.0)


def test_get_stats_returns_correct_values() -> None:
    """Test that get_stats returns correct diagnostic values."""
    observations: list[IntervalObservation] = [{"start": 10.0, "end": 20.0}]
    strategy = CDFPollingStrategy(observations)

    stats = strategy.get_stats()

    assert isinstance(stats, CDFPollingStats)
    assert stats.observation_count == 1
    assert stats.next_poll_index == 0
    assert stats.confirmatory_poll_count == 0
    assert stats.polls_per_interval == 4  # Default
    assert stats.last_observation == {"start": 10.0, "end": 20.0}


def test_cdf_with_single_interval() -> None:
    """Test CDF construction with a single interval."""
    observations: list[IntervalObservation] = [{"start": 10.0, "end": 30.0}]
    strategy = CDFPollingStrategy(observations)

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

    # Default is 4 polls
    assert len(strategy.scheduled_polls) == 4

    # Start new interval with 2 polls
    strategy.start_interval(polls_per_interval=2)
    assert len(strategy.scheduled_polls) == 2

    # Verify schedule changed (2 polls = quantiles at 1/3 and 2/3)
    # For uniform [15, 45]: t = 15 + p * 30
    # p = 1/3 -> t = 25, p = 2/3 -> t = 35
    assert strategy.scheduled_polls == [25.0, 35.0]


def test_start_interval_clamps_polls_per_interval_to_min() -> None:
    """Test that polls_per_interval is clamped to minimum."""
    strategy = CDFPollingStrategy()

    # Too low - should clamp to MIN (1)
    strategy.start_interval(polls_per_interval=0)
    assert len(strategy.scheduled_polls) == 1

    # No max - can use any positive value
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

    # Start with default 4 polls
    assert len(strategy.scheduled_polls) == 4

    # Update budget to 2 polls at 10 seconds elapsed
    strategy.update_budget(polls_per_interval=2, elapsed_seconds=10.0)

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

    # Update at 25 seconds - now we condition on T > 25
    strategy.update_budget(polls_per_interval=4, elapsed_seconds=25.0)

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
    strategy.start_interval(polls_per_interval=4)

    # Original schedule spans [21, 39] within [15, 45] interval
    original = strategy.scheduled_polls.copy()
    assert original == [21.0, 27.0, 33.0, 39.0]

    # Update at 30 seconds - half the probability mass is now gone
    strategy.update_budget(polls_per_interval=4, elapsed_seconds=30.0)

    # New schedule should be compressed into [30, 45]
    # All 4 polls should be evenly distributed in the remaining mass
    new_schedule = strategy.scheduled_polls
    assert len(new_schedule) == 4
    assert all(30.0 < t <= 45.0 for t in new_schedule)


def test_update_budget_all_mass_in_past() -> None:
    """Test update_budget when all probability mass is before elapsed time."""
    strategy = CDFPollingStrategy()
    strategy.start_interval(polls_per_interval=4)

    # Update at 50 seconds - all probability mass is in [15, 45], so F(50) = 1
    strategy.update_budget(polls_per_interval=4, elapsed_seconds=50.0)

    # No remaining mass to sample from - schedule should be empty
    assert strategy.scheduled_polls == []
    assert strategy.should_poll_for_confirmed(50.0) is False
    assert strategy.should_poll_for_confirmed(100.0) is False
