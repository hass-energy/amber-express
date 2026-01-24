"""Tests for the PollingOffsetTracker class."""

import pytest

from custom_components.amber_express.polling_offset import PollingOffsetStats, PollingOffsetTracker


def test_default_offset() -> None:
    """Test that tracker starts with default offset."""
    tracker = PollingOffsetTracker()
    assert tracker.offset == PollingOffsetTracker.OFFSET_DEFAULT
    assert isinstance(tracker.offset, int)


def test_start_interval_resets_poll_count() -> None:
    """Test that start_interval resets the confirmatory poll count."""
    tracker = PollingOffsetTracker()
    tracker.increment_confirmatory_poll()
    tracker.increment_confirmatory_poll()
    assert tracker.confirmatory_poll_count == 2

    tracker.start_interval()
    assert tracker.confirmatory_poll_count == 0


def test_increment_confirmatory_poll() -> None:
    """Test incrementing confirmatory poll count."""
    tracker = PollingOffsetTracker()
    assert tracker.confirmatory_poll_count == 0

    tracker.increment_confirmatory_poll()
    assert tracker.confirmatory_poll_count == 1

    tracker.increment_confirmatory_poll()
    assert tracker.confirmatory_poll_count == 2


def test_overshoot_subtracts_5_seconds() -> None:
    """Test that overshoot (confirmed on first try) subtracts 5 seconds."""
    tracker = PollingOffsetTracker()
    initial_offset = tracker.offset  # 15

    # Simulate first confirmatory poll getting confirmed
    tracker.increment_confirmatory_poll()
    tracker.record_confirmed(last_estimate_elapsed=10.0, confirmed_elapsed=20.0)

    # Should subtract 5 seconds
    assert tracker.offset == initial_offset - 5
    assert tracker.offset == 10


def test_overshoot_with_zero_polls_also_subtracts() -> None:
    """Test that confirming on estimate poll (0 confirmatory polls) also subtracts."""
    tracker = PollingOffsetTracker()
    initial_offset = tracker.offset  # 15

    # No confirmatory polls - confirmed on estimate poll
    tracker.record_confirmed(last_estimate_elapsed=None, confirmed_elapsed=5.0)

    # Should subtract 5 seconds
    assert tracker.offset == initial_offset - 5
    assert tracker.offset == 10


def test_undershoot_sets_midpoint() -> None:
    """Test that undershoot (had to retry) sets offset to midpoint."""
    tracker = PollingOffsetTracker()

    # Simulate multiple confirmatory polls before confirmed
    tracker.increment_confirmatory_poll()  # Poll 1
    tracker.increment_confirmatory_poll()  # Poll 2 (retry)
    tracker.record_confirmed(last_estimate_elapsed=15.0, confirmed_elapsed=25.0)

    # Midpoint = (15 + 25) / 2 = 20
    assert tracker.offset == 20


def test_undershoot_rounds_midpoint() -> None:
    """Test that undershoot rounds the midpoint to nearest integer."""
    tracker = PollingOffsetTracker()

    tracker.increment_confirmatory_poll()
    tracker.increment_confirmatory_poll()  # Retry
    tracker.record_confirmed(last_estimate_elapsed=16.5, confirmed_elapsed=21.3)

    # Midpoint = (16.5 + 21.3) / 2 = 18.9 -> rounds to 19
    assert tracker.offset == 19


def test_undershoot_without_estimate_elapsed_no_change() -> None:
    """Test that undershoot without last_estimate_elapsed doesn't change offset."""
    tracker = PollingOffsetTracker()
    initial_offset = tracker.offset

    tracker.increment_confirmatory_poll()
    tracker.increment_confirmatory_poll()  # Retry
    tracker.record_confirmed(last_estimate_elapsed=None, confirmed_elapsed=30.0)

    # No change since we don't have estimate elapsed
    assert tracker.offset == initial_offset


def test_offset_respects_min_bound() -> None:
    """Test that offset doesn't go below minimum."""
    tracker = PollingOffsetTracker()
    tracker._offset = 3  # Near minimum

    # Overshoot multiple times
    for _ in range(5):
        tracker.start_interval()
        tracker.increment_confirmatory_poll()
        tracker.record_confirmed(last_estimate_elapsed=0.0, confirmed_elapsed=10.0)

    assert tracker.offset >= PollingOffsetTracker.OFFSET_MIN
    assert tracker.offset == 0


def test_offset_respects_max_bound() -> None:
    """Test that offset doesn't go above maximum."""
    tracker = PollingOffsetTracker()

    # Undershoot with high values
    tracker.increment_confirmatory_poll()
    tracker.increment_confirmatory_poll()
    tracker.record_confirmed(last_estimate_elapsed=350.0, confirmed_elapsed=400.0)

    # Midpoint would be 375, but capped at 180
    assert tracker.offset <= PollingOffsetTracker.OFFSET_MAX
    assert tracker.offset == 180


def test_offset_is_always_integer() -> None:
    """Test that offset is always an integer."""
    tracker = PollingOffsetTracker()

    # Undershoot with values that would give non-integer midpoint
    tracker.increment_confirmatory_poll()
    tracker.increment_confirmatory_poll()
    tracker.record_confirmed(last_estimate_elapsed=10.0, confirmed_elapsed=15.0)

    # Midpoint = 12.5 -> rounds to 12 or 13
    assert isinstance(tracker.offset, int)


def test_should_poll_before_offset() -> None:
    """Test that should_poll returns False before offset is reached."""
    tracker = PollingOffsetTracker()
    tracker._offset = 30

    assert not tracker.should_poll_for_confirmed(0.0)
    assert not tracker.should_poll_for_confirmed(10.0)
    assert not tracker.should_poll_for_confirmed(29.0)


def test_should_poll_at_offset() -> None:
    """Test that should_poll returns True at offset."""
    tracker = PollingOffsetTracker()
    tracker._offset = 30

    assert tracker.should_poll_for_confirmed(30.0)


def test_should_poll_after_offset_cold_start() -> None:
    """Test that should_poll uses 5-second intervals on cold start."""
    tracker = PollingOffsetTracker()
    tracker._offset = 30

    # Cold start: 5-second intervals
    assert tracker.poll_interval == 5
    assert tracker.should_poll_for_confirmed(30.0)  # At offset
    assert tracker.should_poll_for_confirmed(35.0)  # +5s
    assert tracker.should_poll_for_confirmed(40.0)  # +10s
    assert not tracker.should_poll_for_confirmed(32.0)  # +2s (between intervals)
    assert not tracker.should_poll_for_confirmed(33.0)  # +3s (between intervals)


def test_should_poll_after_offset_with_history() -> None:
    """Test that should_poll uses 2-second intervals with historical data."""
    tracker = PollingOffsetTracker()
    tracker._offset = 30
    # Simulate having recorded a confirmed price
    tracker._last_confirmed_elapsed = 25.0

    # With history: 2-second intervals
    assert tracker.poll_interval == 2
    assert tracker.should_poll_for_confirmed(30.0)  # At offset
    assert tracker.should_poll_for_confirmed(32.0)  # +2s
    assert tracker.should_poll_for_confirmed(34.0)  # +4s
    assert tracker.should_poll_for_confirmed(36.0)  # +6s


def test_should_poll_returns_false_between_intervals() -> None:
    """Test that should_poll returns False between intervals."""
    tracker = PollingOffsetTracker()
    tracker._offset = 30
    # Simulate having recorded a confirmed price for 2-second intervals
    tracker._last_confirmed_elapsed = 25.0

    # Should not poll between 2-second intervals
    assert not tracker.should_poll_for_confirmed(31.0)  # +1s
    assert not tracker.should_poll_for_confirmed(33.0)  # +3s
    assert not tracker.should_poll_for_confirmed(35.5)  # +5.5s


def test_get_stats_initial() -> None:
    """Test stats on initial state."""
    tracker = PollingOffsetTracker()
    stats = tracker.get_stats()

    assert stats.offset == PollingOffsetTracker.OFFSET_DEFAULT
    assert stats.last_estimate_elapsed is None
    assert stats.last_confirmed_elapsed is None
    assert stats.confirmatory_poll_count == 0


def test_get_stats_after_confirmed() -> None:
    """Test stats after recording confirmed."""
    tracker = PollingOffsetTracker()
    tracker.increment_confirmatory_poll()
    tracker.increment_confirmatory_poll()
    tracker.record_confirmed(last_estimate_elapsed=15.0, confirmed_elapsed=25.0)

    stats = tracker.get_stats()
    assert stats.offset == 20  # Midpoint
    assert stats.last_estimate_elapsed == 15.0
    assert stats.last_confirmed_elapsed == 25.0
    assert stats.confirmatory_poll_count == 2


@pytest.mark.parametrize(
    ("poll_count", "expected_decrease"),
    [
        (0, True),  # Confirmed on estimate poll = overshoot = decrease
        (1, True),  # First confirmatory poll = overshoot = decrease
        (2, False),  # Retry = undershoot = midpoint (may increase or decrease)
        (3, False),  # Multiple retries = undershoot
    ],
)
def test_offset_direction_based_on_poll_count(
    poll_count: int,
    expected_decrease: bool,
) -> None:
    """Test that overshoot decreases and undershoot sets midpoint."""
    tracker = PollingOffsetTracker()
    initial_offset = tracker.offset

    for _ in range(poll_count):
        tracker.increment_confirmatory_poll()
    tracker.record_confirmed(last_estimate_elapsed=10.0, confirmed_elapsed=30.0)

    if expected_decrease:
        assert tracker.offset < initial_offset
    else:
        # Undershoot: midpoint = (10 + 30) / 2 = 20, which is > 15
        assert tracker.offset == 20


def test_offset_property_returns_int() -> None:
    """Test that offset property returns an integer."""
    tracker = PollingOffsetTracker()
    assert isinstance(tracker.offset, int)
    assert tracker.offset == PollingOffsetTracker.OFFSET_DEFAULT


def test_stats_dataclass() -> None:
    """Test PollingOffsetStats dataclass."""
    stats = PollingOffsetStats(
        offset=30,
        last_estimate_elapsed=15.0,
        last_confirmed_elapsed=25.0,
        confirmatory_poll_count=2,
    )

    assert stats.offset == 30
    assert stats.last_estimate_elapsed == 15.0
    assert stats.last_confirmed_elapsed == 25.0
    assert stats.confirmatory_poll_count == 2
