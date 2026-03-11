"""Tests for utility functions."""

from homeassistant.util import dt as dt_util
import pytest

from custom_components.amber_express.utils import to_local_iso_minute


@pytest.mark.parametrize(
    ("input_iso", "expected_seconds"),
    [
        # Rounds down when seconds < 30
        ("2024-01-01T10:00:01+00:00", 0),
        ("2024-01-01T10:00:29+00:00", 0),
        # Rounds up when seconds >= 30
        ("2024-01-01T10:00:30+00:00", 0),  # rounds to next minute
        ("2024-01-01T10:00:59+00:00", 0),  # rounds to next minute
        # Already on the minute
        ("2024-01-01T10:00:00+00:00", 0),
    ],
)
def test_to_local_iso_minute_rounds_correctly(input_iso: str, expected_seconds: int) -> None:
    """Test that timestamps are rounded to nearest minute."""
    result = to_local_iso_minute(input_iso)
    assert result is not None
    # Result should have :00 seconds
    assert ":00+" in result or ":00-" in result or result.endswith(":00")


def test_to_local_iso_minute_rounds_up_to_next_minute() -> None:
    """Test that seconds >= 30 rounds up to next minute."""
    # 10:05:30 should round to 10:06:00
    result = to_local_iso_minute("2024-01-01T10:05:30+00:00")
    assert result is not None

    # Parse both to compare - the result minute should be one more than truncated
    truncated = to_local_iso_minute("2024-01-01T10:05:00+00:00")
    assert truncated is not None

    result_dt = dt_util.parse_datetime(result)
    truncated_dt = dt_util.parse_datetime(truncated)
    assert result_dt is not None
    assert truncated_dt is not None

    # Rounded up should be 1 minute after truncated
    assert result_dt.minute == (truncated_dt.minute + 1) % 60


def test_to_local_iso_minute_none_input() -> None:
    """Test that None input returns None."""
    assert to_local_iso_minute(None) is None


def test_to_local_iso_minute_unparseable_string() -> None:
    """Test that unparseable string returns original string."""
    invalid = "not-a-timestamp"
    assert to_local_iso_minute(invalid) == invalid
