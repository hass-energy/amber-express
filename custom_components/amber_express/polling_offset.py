"""Polling offset tracker for smart polling optimization."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PollingOffsetStats:
    """Diagnostic statistics for polling offset."""

    offset: int
    last_estimate_elapsed: float | None
    last_confirmed_elapsed: float | None
    confirmatory_poll_count: int


class PollingOffsetTracker:
    """Tracks and adjusts polling offset for confirmatory polling.

    Simple algorithm:
    - Overshoot (confirmed on first try): subtract 5 seconds from offset
    - Undershoot (had to retry): set offset to midpoint between last estimate and confirmed
    """

    # Offset bounds
    OFFSET_MIN = 0  # Minimum offset (poll immediately after estimate)
    OFFSET_MAX = 180  # Maximum offset (3 minutes)
    OFFSET_DEFAULT = 15  # Default offset on cold start

    # Overshoot adjustment
    OVERSHOOT_DECREMENT = 5  # Subtract 5 seconds when we overshoot

    # Polling interval after offset
    CONFIRMATORY_POLL_INTERVAL_COLD = 5  # Seconds between polls on cold start
    CONFIRMATORY_POLL_INTERVAL_WARM = 2  # Seconds between polls with historical data

    def __init__(self) -> None:
        """Initialize the tracker."""
        self._offset: int = self.OFFSET_DEFAULT
        self._confirmatory_poll_count: int = 0
        self._last_estimate_elapsed: float | None = None
        self._last_confirmed_elapsed: float | None = None

    def start_interval(self) -> None:
        """Reset state for a new 5-minute interval."""
        self._confirmatory_poll_count = 0

    def record_confirmed(
        self,
        last_estimate_elapsed: float | None,
        confirmed_elapsed: float,
    ) -> None:
        """Record confirmed price and adjust offset.

        Args:
            last_estimate_elapsed: Seconds from interval start when last estimate was received
            confirmed_elapsed: Seconds from interval start when confirmed was received

        """
        self._last_estimate_elapsed = last_estimate_elapsed
        self._last_confirmed_elapsed = confirmed_elapsed

        if self._confirmatory_poll_count <= 1:
            # Overshoot: we waited too long, subtract 5 seconds
            self._offset = max(self._offset - self.OVERSHOOT_DECREMENT, self.OFFSET_MIN)
        elif last_estimate_elapsed is not None:
            # Undershoot: set to midpoint between estimate and confirmed (rounded)
            midpoint = (last_estimate_elapsed + confirmed_elapsed) / 2
            self._offset = max(self.OFFSET_MIN, min(self.OFFSET_MAX, round(midpoint)))

    @property
    def poll_interval(self) -> int:
        """Get the confirmatory poll interval based on whether we have historical data."""
        if self._last_confirmed_elapsed is not None:
            return self.CONFIRMATORY_POLL_INTERVAL_WARM
        return self.CONFIRMATORY_POLL_INTERVAL_COLD

    def should_poll_for_confirmed(self, elapsed_seconds: float) -> bool:
        """Check if we should poll for confirmed price given elapsed time.

        Args:
            elapsed_seconds: Seconds since the interval started

        Returns:
            True if we should poll now, False otherwise

        """
        if elapsed_seconds < self._offset:
            return False
        time_since_offset = elapsed_seconds - self._offset
        return (time_since_offset % self.poll_interval) < 1

    def increment_confirmatory_poll(self) -> None:
        """Track that we made a confirmatory poll attempt."""
        self._confirmatory_poll_count += 1

    @property
    def offset(self) -> int:
        """Get the current offset in seconds."""
        return self._offset

    @property
    def confirmatory_poll_count(self) -> int:
        """Get the number of confirmatory polls made this interval."""
        return self._confirmatory_poll_count

    def get_stats(self) -> PollingOffsetStats:
        """Get diagnostic statistics."""
        return PollingOffsetStats(
            offset=self._offset,
            last_estimate_elapsed=self._last_estimate_elapsed,
            last_confirmed_elapsed=self._last_confirmed_elapsed,
            confirmatory_poll_count=self._confirmatory_poll_count,
        )
