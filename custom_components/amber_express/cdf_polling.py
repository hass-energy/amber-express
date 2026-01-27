"""CDF-based polling strategy for optimal confirmatory poll timing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, TypedDict


class IntervalObservation(TypedDict):
    """An observed interval where the confirmed price became available."""

    start: float  # Last poll time that returned estimate
    end: float  # First poll time that returned confirmed


@dataclass
class CDFPollingStats:
    """Diagnostic statistics for CDF polling strategy."""

    observation_count: int
    scheduled_polls: list[float]
    next_poll_index: int
    confirmatory_poll_count: int
    polls_per_interval: int
    last_observation: IntervalObservation | None


class CDFPollingStrategy:
    """CDF-based polling strategy that learns optimal poll times from observations.

    Maintains a rolling window of interval observations [a, b] where the confirmed
    price became available somewhere in that interval. Builds an empirical CDF from
    these intervals and uses inverse CDF sampling to schedule polls that minimize
    expected detection delay.
    """

    # Configuration constants
    WINDOW_SIZE = 100  # Rolling window of observations (N)
    DEFAULT_POLLS_PER_INTERVAL = 4  # Default number of polls per 5-minute window (k)
    MIN_POLLS_PER_INTERVAL = 1  # Minimum polls per interval
    MIN_CDF_POINTS = 2  # Minimum points required for a valid CDF
    COLD_START_INTERVAL: ClassVar[IntervalObservation] = {"start": 15.0, "end": 45.0}

    def __init__(self, observations: list[IntervalObservation] | None = None) -> None:
        """Initialize the strategy with optional pre-loaded observations."""
        if observations is not None:
            self._observations = observations[-self.WINDOW_SIZE :]
        else:
            # Cold start: fill with synthetic intervals
            self._observations = [
                self.COLD_START_INTERVAL.copy() for _ in range(self.WINDOW_SIZE)
            ]

        self._scheduled_polls: list[float] = []
        self._next_poll_index = 0
        self._confirmatory_poll_count = 0
        self._polls_per_interval = self.DEFAULT_POLLS_PER_INTERVAL

        # Pre-compute schedule for first interval
        self._compute_poll_schedule()

    def start_interval(self, polls_per_interval: int | None = None) -> None:
        """Reset state for a new 5-minute interval.

        Args:
            polls_per_interval: Number of confirmatory polls to schedule.
                If None, uses the previous value (or default on first call).

        """
        self._next_poll_index = 0
        self._confirmatory_poll_count = 0

        # Update polls per interval if provided
        if polls_per_interval is not None:
            self._polls_per_interval = max(self.MIN_POLLS_PER_INTERVAL, polls_per_interval)
            # Recompute schedule with new k
            self._compute_poll_schedule()

    def record_observation(self, start: float, end: float) -> None:
        """Record a new interval observation and update the CDF.

        Args:
            start: Seconds from interval start when last estimate was received
            end: Seconds from interval start when confirmed was received

        """
        # Ensure valid interval (start < end)
        if start >= end:
            # Invalid observation, skip
            return

        observation: IntervalObservation = {"start": start, "end": end}
        self._observations.append(observation)

        # Maintain rolling window
        if len(self._observations) > self.WINDOW_SIZE:
            self._observations = self._observations[-self.WINDOW_SIZE :]

        # Recompute poll schedule for future intervals
        self._compute_poll_schedule()

    def should_poll_for_confirmed(self, elapsed_seconds: float) -> bool:
        """Check if we should poll for confirmed price given elapsed time.

        Args:
            elapsed_seconds: Seconds since the interval started

        Returns:
            True if we should poll now, False otherwise

        """
        if self._next_poll_index >= len(self._scheduled_polls):
            return False

        next_poll_time = self._scheduled_polls[self._next_poll_index]
        return elapsed_seconds >= next_poll_time

    def increment_confirmatory_poll(self) -> None:
        """Track that we made a confirmatory poll attempt."""
        self._confirmatory_poll_count += 1
        # Advance to next scheduled poll
        if self._next_poll_index < len(self._scheduled_polls):
            self._next_poll_index += 1

    @property
    def confirmatory_poll_count(self) -> int:
        """Get the number of confirmatory polls made this interval."""
        return self._confirmatory_poll_count

    @property
    def scheduled_polls(self) -> list[float]:
        """Get the currently scheduled poll times."""
        return self._scheduled_polls.copy()

    @property
    def observations(self) -> list[IntervalObservation]:
        """Get the current observations (for persistence)."""
        return self._observations.copy()

    def get_stats(self) -> CDFPollingStats:
        """Get diagnostic statistics."""
        return CDFPollingStats(
            observation_count=len(self._observations),
            scheduled_polls=self._scheduled_polls.copy(),
            next_poll_index=self._next_poll_index,
            confirmatory_poll_count=self._confirmatory_poll_count,
            polls_per_interval=self._polls_per_interval,
            last_observation=self._observations[-1] if self._observations else None,
        )

    def _compute_poll_schedule(self) -> None:
        """Compute optimal poll times using inverse CDF sampling."""
        if not self._observations:
            self._scheduled_polls = []
            return

        # Build the CDF
        cdf_points = self._build_cdf()

        if len(cdf_points) < self.MIN_CDF_POINTS:
            self._scheduled_polls = []
            return

        # Compute poll times via inverse CDF
        k = self._polls_per_interval
        target_probabilities = [j / (k + 1) for j in range(1, k + 1)]

        self._scheduled_polls = [
            self._inverse_cdf(p, cdf_points) for p in target_probabilities
        ]

    def _build_cdf(self) -> list[tuple[float, float]]:
        """Build piecewise linear CDF from interval observations.

        Returns:
            List of (time, cumulative_probability) points defining the CDF.

        """
        if not self._observations:
            return []

        n = len(self._observations)

        # Collect all unique endpoints
        endpoints: set[float] = set()
        for obs in self._observations:
            endpoints.add(obs["start"])
            endpoints.add(obs["end"])

        # Sort to form time grid
        time_grid = sorted(endpoints)

        if len(time_grid) < self.MIN_CDF_POINTS:
            return []

        # For each segment, compute the CDF slope (sum of contributing densities)
        # Each interval [a_i, b_i] contributes density 1/(N * (b_i - a_i)) when t in [a_i, b_i)
        cdf_points: list[tuple[float, float]] = [(time_grid[0], 0.0)]
        cumulative = 0.0

        for i in range(len(time_grid) - 1):
            t_start = time_grid[i]
            t_end = time_grid[i + 1]
            segment_length = t_end - t_start

            # Compute slope: sum of densities from intervals covering this segment
            slope = 0.0
            for obs in self._observations:
                a, b = obs["start"], obs["end"]
                if a <= t_start < b:
                    # This interval contributes to this segment
                    slope += 1.0 / (n * (b - a))

            # Integrate: add slope * segment_length to cumulative
            cumulative += slope * segment_length
            cdf_points.append((t_end, cumulative))

        # Normalize so CDF ends at 1.0
        if cumulative > 0:
            cdf_points = [(t, p / cumulative) for t, p in cdf_points]

        return cdf_points

    def _inverse_cdf(
        self, target_p: float, cdf_points: list[tuple[float, float]]
    ) -> float:
        """Compute inverse CDF (quantile function) via linear interpolation.

        Args:
            target_p: Target probability in [0, 1]
            cdf_points: List of (time, cumulative_probability) points

        Returns:
            Time t such that F(t) = target_p

        """
        if not cdf_points:
            return 0.0

        # Handle edge cases
        if target_p <= cdf_points[0][1]:
            return cdf_points[0][0]
        if target_p >= cdf_points[-1][1]:
            return cdf_points[-1][0]

        # Find segment containing target_p
        for i in range(len(cdf_points) - 1):
            t0, p0 = cdf_points[i]
            t1, p1 = cdf_points[i + 1]

            if p0 <= target_p <= p1:
                # Linear interpolation
                if p1 == p0:
                    return t0
                fraction = (target_p - p0) / (p1 - p0)
                return t0 + fraction * (t1 - t0)

        # Should not reach here, but return last point as fallback
        return cdf_points[-1][0]
